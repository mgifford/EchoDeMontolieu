import json

from echo_montolieu import budget as b


def row(compte, sd=0, sc=0, obnetdeb=0, obnetcre=0, **kw):
    return {"compte": compte, "sd": sd, "sc": sc, "obnetdeb": obnetdeb, "obnetcre": obnetcre, "bal": "DEF", "nomen": "M14", **kw}


def year_rows(main=("budget", "BP"), annex=("budget", "BA")):
    k, v = main
    ak, av = annex
    return [
        row("70311", sc=1000, **{k: v}), row("7311", sc=5000, **{k: v}), row("7391", sd=500, **{k: v}),   # taxes net of a levy
        row("74121", sc=2000, **{k: v}), row("775", sc=9999, **{k: v}),                                    # 775 is left out
        row("6411", sd=3000, **{k: v}), row("6419", sc=200, **{k: v}), row("66111", sd=100, **{k: v}),     # staff net of refunds
        row("6811", sd=7777, **{k: v}), row("676", sd=1234, **{k: v}),                                     # 68x and 676 are left out
        row("2315", obnetdeb=800, **{k: v}), row("2128", obnetdeb=200, obnetcre=50, **{k: v}),
        row("1641", sc=4000, **{k: v}), row("165", sc=100, **{k: v}), row("1641", sc=99999, **{ak: av}),   # a deposit and an annex budget
    ]


def test_figures_follow_the_stated_rules():
    f = b.summarise(year_rows())
    assert f["revenue"] == 1000 + 5000 - 500 + 2000          # 70, 73 (net), 74; not 775
    assert f["spending"] == 3000 - 200 + 100                 # 64 net, 66; not 68x, not 676
    assert f["result"] == f["revenue"] - f["spending"]
    assert (f["staff"], f["interest"], f["taxes"], f["state"]) == (2800, 100, 4500, 2000)
    assert f["investment"] == 800 + 150 and f["debt"] == 4000


def test_the_newer_file_layout_marks_the_main_budget_with_cbudg():
    assert b.summarise(year_rows(main=("cbudg", "1"), annex=("cbudg", "2")))["debt"] == 4000


def test_a_year_with_only_annex_budgets_is_left_out():
    assert b.summarise([row("1641", sc=5, budget="BA")]) is None


def test_euros_are_written_the_way_each_language_writes_them():
    assert b.euros("en", 1234567) == "€1,234,567" and b.euros("en", -5) == "−€5"
    assert b.euros("fr", 1234567) == "1 234 567 €"
    assert b.euros("nl", 1234567) == "€ 1.234.567"


def test_pages_in_three_languages_are_written_with_disclosure_caveats_and_every_year(tmp_path):
    folder = tmp_path / "in"
    folder.mkdir()
    for y in (2010, 2011):
        (folder / f"balances-{y}.json").write_text(json.dumps(year_rows()), encoding="utf-8")
    (folder / "ignored.json").write_text("[]", encoding="utf-8")
    info = b.run(folder, tmp_path / "public", tmp_path / "budget_years.json")
    assert info["years"] == [2010, 2011]
    fr = (tmp_path / "public/finance/budget.md").read_text(encoding="utf-8")
    assert "language: fr" in fr and "# Les finances au fil des années" in fr and "| 2010 |" in fr and "| 2011 |" in fr
    en = (tmp_path / "public/finance/budget.en.md").read_text(encoding="utf-8")
    assert "executed accounts, not the voted budget" in en and "AI disclosure" in en and b.VOTED_2026 in en
    assert "# De financiën" in (tmp_path / "public/finance/budget.nl.md").read_text(encoding="utf-8")
    assert json.loads((tmp_path / "budget_years.json").read_text())["years"]["2010"]["revenue"] == 7500


def test_an_empty_folder_stops_with_a_message_that_says_how_to_get_the_files(tmp_path):
    try:
        b.run(tmp_path, tmp_path / "p", tmp_path / "d.json")
    except SystemExit as exc:
        assert "balances-YYYY.json" in str(exc)
    else:
        raise AssertionError("expected a stop")


def test_the_finance_page_links_to_the_budget_page_only_when_it_exists(tmp_path):
    from echo_montolieu import finance
    finance.write_finance(tmp_path, [])
    assert "budget.md" not in (tmp_path / "finance/index.md").read_text(encoding="utf-8")
    (tmp_path / "finance/budget.md").write_text("x", encoding="utf-8")
    finance.write_finance(tmp_path, [])
    assert "(budget.md)" in (tmp_path / "finance/index.md").read_text(encoding="utf-8")
