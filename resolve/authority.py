"""Authoritative identifiers: identity that needs no scoring.

Most of this pipeline guesses. Normalization and IDF-weighted matching produce a
*likelihood* that two names denote one organization, and the ambiguous middle
goes to a human. But some identity is not a guess. When the Nebraska Legislature
gives a lobbying principal id 2590, every record carrying 2590 is that same
registered principal, by construction. There is nothing to infer.

Short-circuiting on those ids matters for two reasons the live data makes plain:

**It recovers links no name matcher could ever make.** Principal 2590 appears in
the roster as "Time Warner Cable" and in the bill-position table as "Charter
Communications Operating, L...". The entity was renamed and the id outlived the
name. No normalization, no fuzzy score, and no amount of tuning connects those
two strings -- but the id does, exactly.

**It repairs truncated names.** The bill-position table cuts names off in the
markup ("Associated Beverage Distributors of..."), and 28% of a real sample came
back truncated. Those strings are unmatchable as text. Grouped by id, they
inherit the full name from the detail page and the cluster they belong to.

The knock-on effect is the valuable part: because aliases sharing an id are
unioned FIRST, a later match against any one of them attaches the whole group.
One human decision on one alias propagates to every record carrying that id,
including the truncated ones, without anyone re-reviewing them.

Scope, stated precisely: an id is authoritative WITHIN its source only. That
principal 2590 is one registered principal says nothing about whether it is the
same real-world company as contract vendor "CHARTER COMMUNICATIONS". Linking
across sources still requires matching, and still requires a person.
"""

from __future__ import annotations

from collections import defaultdict


def authoritative_groups(parties_by_key):
    """{normalized_key: [Party]} -> {(source, source_id): {keys}}.

    Only groups spanning more than one key are returned; a single key needs no
    linking. Parties without a source_id are skipped -- contracts and campaign
    finance publish no entity id, which is the whole reason they need matching.
    """
    groups = defaultdict(set)
    for key, parties in parties_by_key.items():
        for party in parties:
            source_id = getattr(party, "source_id", "")
            if source_id:
                groups[(party.source, source_id)].add(key)
    return {identity: keys for identity, keys in groups.items() if len(keys) > 1}


def short_circuit(clusters, parties_by_key):
    """Union every key sharing an authoritative id. Mutates `clusters`.

    Returns one record per link made, so the output can distinguish an entity
    assembled from a hard id from one assembled by a name match. A reader should
    never have to guess which kind of claim they are looking at.
    """
    links = []
    for (source, source_id), keys in sorted(authoritative_groups(parties_by_key).items()):
        ordered = sorted(keys)
        anchor = ordered[0]
        for other in ordered[1:]:
            clusters.union(anchor, other)
            links.append(
                {
                    "left_key": anchor,
                    "right_key": other,
                    "match_kind": "authoritative_id",
                    "score": 1.0,
                    "decision": "hard_id",
                    "reason": (
                        f"same {source} id {source_id} -- identity by construction, "
                        "not by name similarity"
                    ),
                }
            )
    return links
