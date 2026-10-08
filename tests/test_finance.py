from echo_montolieu import finance as fin
from echo_montolieu import threads as th
from tests.test_threads import item, meeting


def money(n, date, title, amounts, refs=(), wording=(), exceptions=(), vote="unanimous"):
    it = item(n, date, title, "Texte de l’élément sur les finances de la commune pour l’année.", amounts=amounts)
    it["legal_refs"] = [{"kind": "article", "code": "CGCT", "ref": r, "key": f"CGCT {r}", "sentence": "x"} for r in refs]
    it["rule_mentions"] = [{"sentence": s} for s in wording]
    it["exceptions"] = [{"marker": "exception", "sentence": s} for s in exceptions]
    it["vote_result"] = vote
    return it


def sample():
    return [
        meeting("2024-01-10", [money(1, "2024-01-10", "Ligne de trésorerie", (300000,), refs=("L1612-1",)),
                               money(2, "2024-01-10", "Travaux de voirie", (45000,)),
                               item(3, "2024-01-10", "Droits de préemption", "x", sensitive=True, amounts=(90000,))]),
        meeting("2025-02-10", [money(1, "2025-02-10", "Subventions", (1500, 300), wording=("Conformément à la réglementation en vigueur.",),
                                    exceptions=("Votées à l’unanimité, à l’exception de la demande de l’association.",)),
                               item(2, "2025-02-10", "Sans montant", "Un point sans argent à l’ordre du jour de la séance.")]),
    ]


def test_money_rows_only_include_non_sensitive_items_with_euro_amounts():
    rows = fin.money_rows(sample())
    assert [r["item"]["title"] for r in rows] == ["Ligne de trésorerie", "Travaux de voirie", "Subventions"]


def test_basis_distinguishes_a_citation_wording_only_and_nothing():
    a, b, c = fin.money_rows(sample())
    assert fin.basis(a) == "cites: CGCT L1612-1" and fin.basis(c) == "rule wording only" and fin.basis(b) == "none stated"


def test_the_page_leads_with_how_little_is_explicit_and_counts_correctly():
    md = fin.render_finance(sample())
    assert "Agenda items with euro amounts: **3**" in md
    assert "cite a law, article, decree or budget instruction**: **1**" in md
    assert "wording that points to a rule or limit** but no citation: **1**" in md
    assert "say nothing about a rule**: **1**" in md
    assert "seldom state their legal basis" in md and "not a legal analysis" in md
    assert md.index("How much the minutes say explicitly") < md.index("Decisions with money, by year")


def test_table_rows_show_amounts_basis_exception_vote_and_page_link():
    md = fin.render_finance(sample())
    assert "### 2024" in md and "### 2025" in md
    assert "| 2024-01-10 | Ligne de trésorerie | 300 000 € |" in md and "cites: CGCT L1612-1" in md
    assert "| 2025-02-10 | Subventions | 1 500 €, 300 € |" in md and "rule wording only | yes |" in md
    assert "https://example.test/2025-02-10.pdf#page=1" in md


def test_rules_cited_by_name_and_exceptions_sections():
    md = fin.render_finance(sample())
    assert "## Rules cited by name" in md and "| CGCT L1612-1 | 1 |" in md
    assert "## Exceptions and exemptions mentioned" in md and "à l’exception de la demande" in md and "amounts 1 500 €, 300 €" in md


def test_unknown_code_references_are_flagged_not_guessed():
    m = sample()
    m[0]["meeting"]["items"][0]["legal_refs"] = [{"kind": "article", "code": None, "ref": "L141-5-3", "key": "? L141-5-3", "sentence": "x"}]
    assert "has no code named near it" in fin.render_finance(m) and "| ? L141-5-3 |" in fin.render_finance(m)


def test_empty_sections_say_none_found():
    md = fin.render_finance([meeting("2024-01-10", [item(1, "2024-01-10", "Rien", "Aucun montant ici dans ce point de la séance.")])])
    assert "Agenda items with euro amounts: **0**" in md and md.count("None found.") == 2


def test_recurring_money_issues_show_amounts_over_time():
    m = [meeting(f"2024-0{i}-10", [money(1, f"2024-0{i}-10", "Ligne de trésorerie",
                                         (300000 + i,), wording=())]) for i in (1, 3, 5)]
    for x in m:
        x["meeting"]["items"][0]["text"] = "Renouvellement de la ligne de trésorerie auprès de la banque pour les besoins courants de la commune"
    result = th.build_threads(m)
    md = fin.render_finance(m, result)
    assert "## Recurring money issues: amounts over time" in md and "| 2024-03-10 | 300 003 € |" in md


def test_write_finance_creates_the_page(tmp_path):
    info = fin.write_finance(tmp_path, sample())
    assert (tmp_path / "finance" / "index.md").exists() and info == {"money_items": 3, "exception_items": 1}
