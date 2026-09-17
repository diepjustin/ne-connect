import json

import export_fec
import sources

FEC_CONTRIBUTIONS = (
    "sub_id,cmte_id,cmte_name,amndt_ind,rpt_tp,transaction_tp,entity_tp,name,"
    "city,state,zip,transaction_dt,transaction_amt,other_id,tran_id,file_num,"
    "image_num,cycle,source_url,source_snapshot\n"
    "1,C00003988,NEBRASKA DEMOCRATIC PARTY,N,Q1,15,IND,\"DOE, JANE\",OMAHA,NE,"
    "68102,01152024,250.00,,T1,1,IMG1,2024,https://docquery.fec.gov/cgi-bin/"
    "fecimg/?IMG1,2026-09-15T06:01:24Z\n"
    "2,C00003988,NEBRASKA DEMOCRATIC PARTY,N,Q2,15,IND,\"DOE, JANE\",OMAHA,NE,"
    "68102,04202024,300.00,,T2,1,IMG2,2024,https://docquery.fec.gov/cgi-bin/"
    "fecimg/?IMG2,2026-09-15T06:01:24Z\n"
)


def test_fec_rows_json_shape_matches_docs(tmp_path):
    (tmp_path / "fec_contributions_ne.csv").write_text(FEC_CONTRIBUTIONS)
    rows_by_name = sources.load_fec_contribution_rows(tmp_path)

    assert list(rows_by_name.keys()) == ["DOE, JANE"]
    rows = rows_by_name["DOE, JANE"]
    assert len(rows) == 2
    date, amount, cmte_name, city, state, source_url = rows[0]
    assert date == "2024-04-20"
    assert amount == 300.0
    assert cmte_name == "NEBRASKA DEMOCRATIC PARTY"
    assert city == "OMAHA"
    assert state == "NE"
    assert source_url.startswith("https://docquery.fec.gov")


def test_fec_rows_newest_first(tmp_path):
    (tmp_path / "fec_contributions_ne.csv").write_text(FEC_CONTRIBUTIONS)
    rows = sources.load_fec_contribution_rows(tmp_path)["DOE, JANE"]
    assert [r[0] for r in rows] == ["2024-04-20", "2024-01-15"]


def test_write_fec_rows_json_writes_real_file(tmp_path):
    (tmp_path / "fec_contributions_ne.csv").write_text(FEC_CONTRIBUTIONS)
    out_path = tmp_path / "fec_rows.json"

    def fake_loader():
        return sources.load_fec_contribution_rows(tmp_path)

    export_fec.load_fec_contribution_rows = fake_loader
    size = export_fec.write_fec_rows_json(out_path)
    assert size > 0
    assert json.loads(out_path.read_text())["DOE, JANE"]
