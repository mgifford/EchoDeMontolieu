import json

from echo_montolieu import history


def test_surname_picks_the_capitalised_family_name_in_either_order():
    assert history.surname("Bernard LAURET") == "Lauret"
    assert history.surname("RICARD Edouard") == "Ricard"
    assert history.surname("Edouard Ricard") == "Ricard"


def test_chair_is_read_from_the_opening_sentence_in_each_layout():
    assert history.chair_of("sous la Présidence de Monsieur Max DELPERIER, Maire, dans la salle") == "Delperier"
    assert history.chair_of("sous la présidence de Monsieur Bernard LAURET, à la salle d’honneur") == "Lauret"
    assert history.chair_of("sous la présidence du Maire, M. Edouard Ricard. Étaient présents") == "Ricard"
    assert history.chair_of("CONSEIL MUNICIPAL DU 18/07/2008 Etaient présents : A, B") is None


def test_spelling_variants_merge_to_the_commonest_but_different_names_do_not():
    canon = history.canonical_names(["Delperier"] * 5 + ["Delpérier", "Demperier", "Ricard", "Lauret"])
    assert canon["Delpérier"] == canon["Demperier"] == "Delperier"
    assert canon["Ricard"] == "Ricard" and canon["Lauret"] == "Lauret"


def _public(tmp_path, docs):
    pub = tmp_path / "public"
    (pub / "minutes").mkdir(parents=True)
    entries = []
    for i, (when, text, origin) in enumerate(docs):
        rec = {"document_id": f"{i:012x}", "source_url": f"https://x/{i}", "source_sha256": "a" * 64, "page_count": 1,
               "meeting_date": {"value": when, "status": "tentative"}, "origin": origin,
               "pages": [{"page": 1, "method": "text_layer", "status": "machine_extracted", "text": text}]}
        (pub / "minutes" / f"{rec['document_id']}.json").write_text(json.dumps(rec))
        entries.append({"file": f"minutes/{rec['document_id']}.json"})
    (pub / "index.json").write_text(json.dumps({"documents": entries}))
    return pub


def test_history_reports_chairs_gaps_and_missing_years_without_naming_anyone_else(tmp_path):
    pub = _public(tmp_path, [
        ("2004-03-02", "sous la Présidence de Monsieur Max DELPERIER, Maire. Budget 135 000 € voté. Présents : DUPONT Jeanne.", {"kind": "wayback"}),
        ("2008-05-09", "sous la Présidence de Monsieur RICARD Edouard, Maire. Voirie et travaux.", {"kind": "wayback"}),
        ("2024-01-31", "sous la présidence de Monsieur Bernard LAURET, à la salle. Subvention.", None)])
    h = history.write(pub, tmp_path / "out")
    assert [c["chair"] for c in h["chairs"]] == ["Delperier", "Ricard", "Lauret"]
    assert h["coverage"]["years_with_no_minutes"][0] == 2005 and 2023 in h["coverage"]["years_with_no_minutes"]
    assert h["coverage"]["gaps_over_180_days"][-1]["before"] == "2024-01-31"
    md = (tmp_path / "out" / "HISTORY.md").read_text(encoding="utf-8")
    assert "Dupont" not in md and "DUPONT" not in md and "Jeanne" not in json.dumps(h)
    assert "AI disclosure." in md and "human_reviewed: false" in md
    assert h["meetings"][0]["recovered_from_internet_archive"] is True and h["meetings"][0]["amounts"]["largest"][0]["eur"] == 135000
