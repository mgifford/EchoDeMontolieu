import json
from types import SimpleNamespace

from echo_montolieu import watch

PAGE = """<html><body>
<a href="/wp-content/uploads/2026/09/PV-CONSEIL-MUNICIPAL-DU-22-juillet-2026-site.pdf">22 juillet</a>
<a href="/wp-content/uploads/2026/10/CRCM-15-09-2026-site.pdf">15 septembre</a>
<a href="/wp-content/uploads/2026/10/Projet-CM-test.pdf">projet</a>
<a href="https://evil.example/fake.pdf">other host</a>
<a href="/mairie/contact/">not a pdf</a>
</body></html>"""


class Fetcher:
    def __init__(self, tmp_path, html=PAGE, error=None):
        self.path, self.error = tmp_path / "page.html", error
        self.path.write_text(html, encoding="utf-8")
        self.urls = []

    def get(self, url, revalidate=True):
        self.urls.append(url)
        if self.error:
            raise self.error
        return SimpleNamespace(path=self.path)


def public(tmp_path, urls):
    p = tmp_path / "public"
    p.mkdir()
    (p / "index.json").write_text(json.dumps({"documents": [{"source_url": u} for u in urls]}))
    return p


KNOWN = "https://www.montolieu.fr/wp-content/uploads/2026/09/PV-CONSEIL-MUNICIPAL-DU-22-juillet-2026-site.pdf"
GONE = "https://www.montolieu.fr/wp-content/uploads/2024/01/old.pdf"
WAYBACK = "https://web.archive.org/web/20051014125508/http://www.montolieu.fr/docs/CRCM250105.pdf"


def test_new_files_are_found_once_and_only_from_the_mairies_own_host(tmp_path):
    fetcher = Fetcher(tmp_path)
    report = watch.check(public(tmp_path, [KNOWN, GONE, WAYBACK]), fetcher)
    assert fetcher.urls == ["https://www.montolieu.fr/mairie/comptes-rendus-cm/"]              # one request
    assert [n["filename"] for n in report["new"]] == ["CRCM-15-09-2026-site.pdf", "Projet-CM-test.pdf"]
    assert all(n["url"].startswith("https://www.montolieu.fr/") for n in report["new"])        # the other host is ignored
    assert report["no_longer_listed"] == [GONE] and report["known"] == 2                       # archive copies are not "known on the site"
    assert any(n["draft_suspected"] for n in report["new"])


def test_nothing_new_gives_no_issue_text(tmp_path):
    p = public(tmp_path, [KNOWN, "https://www.montolieu.fr/wp-content/uploads/2026/10/CRCM-15-09-2026-site.pdf",
                          "https://www.montolieu.fr/wp-content/uploads/2026/10/Projet-CM-test.pdf"])
    report = watch.check(p, Fetcher(tmp_path))
    assert report["new"] == [] and report["no_longer_listed"] == []


def test_issue_text_filters_what_comes_from_the_page_and_says_nothing_was_published(tmp_path):
    report = watch.check(public(tmp_path, [KNOWN]), Fetcher(tmp_path))
    text = watch.issue_markdown(report)
    assert "Nothing was downloaded or published" in text and "python -m echo_montolieu sync" in text
    assert "(looks like a draft)" in text and watch.issue_title(report).startswith("New minutes on the Mairie's site: ")


def test_a_refusal_or_a_robots_block_stops_the_run_with_a_clear_exit_code(tmp_path, monkeypatch):
    from echo_montolieu.fetch import StopFetching
    for n, error in enumerate((StopFetching("503 from the Mairie"), PermissionError("robots.txt disallows"))):
        folder = tmp_path / f"run{n}"
        folder.mkdir()
        monkeypatch.setattr(watch, "PoliteFetcher", lambda *a, _e=error, _f=folder, **k: Fetcher(_f, error=_e))
        assert watch.main(["--public", str(public(folder, [KNOWN]))]) == 2


def test_main_writes_the_report_and_the_issue_only_when_something_is_new(tmp_path, monkeypatch):
    monkeypatch.setattr(watch, "PoliteFetcher", lambda *a, **k: Fetcher(tmp_path))
    report, issue = tmp_path / "r.json", tmp_path / "issue.md"
    assert watch.main(["--public", str(public(tmp_path, [KNOWN])), "--report", str(report), "--issue", str(issue)]) == 0
    assert json.loads(report.read_text())["new"] and "not published here yet" in issue.read_text() and issue.with_name("issue.md.title").exists()


def test_hostile_characters_in_a_link_from_the_page_cannot_break_out_of_the_issue_text(tmp_path):
    page = ('<a href="/uploads/a b)[x](http://evil.example)<script>alert(1)</script>.pdf?utm=1#frag">x</a>'
            '<a href="/uploads/ok.pdf">ok</a>')
    report = watch.check(public(tmp_path, []), Fetcher(tmp_path, html=page))
    text = watch.issue_markdown(report)
    assert all(ch not in n["url"] for n in report["new"] for ch in "<>()[] \"'?#") and "evil.example)" not in text
    assert "<script>" not in text and "<" not in "".join(l for l in text.splitlines() if l.startswith("- ["))
