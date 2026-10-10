from echo_montolieu import culture


def test_links_are_https_and_trilingual():
    for e in culture.load_links():
        assert e["url"].startswith("https://")
        assert set(e["title"]) == set(e["about"]) == {"fr", "en", "nl"}


def test_page_groups_decisions_and_links_the_original_page(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "decisions.csv").write_text(
        "date,source,n,title,text_fr,vote,votes_for,votes_against,abstentions,first_page,last_page,original_page_url,topics,euro_amounts\n"
        "2025-03-06,current,5,GIP musée,,unanimous,,,,5,5,https://example.test/a.pdf#page=5,musée Cérès Franco; finances,\n"
        "2025-09-25,current,3,Chemin,,majority,10,3,0,4,5,https://example.test/b.pdf#page=4,musée Cérès Franco,\n",
        encoding="utf-8")
    info = culture.write(tmp_path)
    assert info["decisions"] == 2
    en = (tmp_path / "culture" / "index.en.md").read_text(encoding="utf-8")
    assert "[Chemin](https://example.test/b.pdf#page=4) (Vote: majority (10/3/0))" in en
    assert en.index("2025-09-25") < en.index("2025-03-06")      # newest first
    assert "visitors per year is not in the minutes" in en
    assert (tmp_path / "culture" / "index.nl.md").exists() and (tmp_path / "culture" / "index.md").exists()
