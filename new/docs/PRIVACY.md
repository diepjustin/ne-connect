# Privacy and ethics

Everything in this index is a public record. That settles the legal question and
not much else. A tool that joins six public datasets makes something that did not
previously exist: a searchable profile of a private person assembled in one click.
Decide deliberately how far that goes.

## Positions taken

**Organizations: index freely.** Companies, PACs, committees, agencies, unions, and
nonprofits that take state money or spend on politics are the point of the tool.

**Public officials and public employees: index freely.** Elected officials,
appointees, registered lobbyists, and state employees in the published salary
roster are public in their public roles. Their C-1 disclosures exist precisely to be
read.

**Private individuals who appear only as small donors: handle with care.** A
person who gave $300 to a school board candidate is in the public record and their
contribution should be searchable. But they should not acquire a profile page that
aggregates their employer, their neighbors' donations, and every LLC at their
address.

## Concrete rules

1. **Entity pages exist for organizations and public figures. Individuals who
   appear only in contribution records get search results, not a profile page.**
   Their contributions are findable; a dossier is not assembled for them.
2. **Home addresses are never displayed.** Contribution records often carry them.
   Store what's needed for matching; display city, state, and ZIP only.
3. **No reverse-address search in the public UI.** "Everyone at 1234 Elm St" is a
   reporting technique, not a public feature. If it's built, it's a local-only tool
   in `pipeline/`, not on the site.
4. **No bulk export of individual donors.** Per-search CSV export is fine. A
   "download all 240,000 contributors" button is not.
5. **The co-occurrence panel never links two private individuals to each other.**
   Organization-to-organization and person-to-organization only.
6. **No inference about anyone.** The tool does not guess employer, party,
   ethnicity, religion, or anything else not printed in the record. Not with rules,
   not with a model.
7. **Corrections are honored fast.** A visible way to report a bad match, and a
   commitment to fix it in the next build. Log corrections in
   `data/manual/corrections.csv`.

## The itemization trap

Contributions at or below $250 in a calendar year aren't itemized in Nebraska. Any
total the tool shows is a total of itemized contributions only, and the interface
must say so wherever a total appears. A reporter who writes "gave nothing" because
the tool showed nothing has been failed by the tool.

## Staleness is an ethics issue

A dissolved LLC, a resolved audit finding, a corrected filing — showing old data
without a date is how a tool creates a false impression while being technically
accurate. Every record carries its retrieval date. Every dataset carries its last
update. The banner is not optional.

## When a source objects

If a subject contacts us claiming a record is wrong: we do not edit the record —
the state published it and it is theirs to correct. We do add a note to the entity
in `data/manual/corrections.csv`, we do link to their correction if they file one,
and we do fix any matching error that is ours.

## What this tool is not

Not a background-check service. Not a due-diligence product. Not a public "who's
connected to whom" wall. It is a reporter's index over records the state already
publishes, and the design choices above are what keep it that.
