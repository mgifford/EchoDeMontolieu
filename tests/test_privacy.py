import json
import stat

import pytest

from echo_montolieu.privacy import (KEY_ENV, Pseudonymiser, find_private_names,
                                    normalize_name, redact_extraction)

KEY = "k" * 40
# All names below are fictional.
SALE = (
    "Désignation du bien vendu :\n"
    "Réf. Cadastrale : PECH ROSIE\n"
    "Prix de vente : 90 000,00 EUR\n"
    "Vendeur(s) : DURANT Jean Marc, DURANT Éliane, DURANT Jean-Luc,\n\n"
    "DURANT Paul, DURANT Léa\n"
    "Acquéreur : SAFER\n"
    "> Le conseil se prononce à l'unanimité\n"
)


def make(tmp_path, key=KEY):
    return Pseudonymiser(key, tmp_path / "private")


def test_normalize_is_order_and_accent_insensitive():
    assert normalize_name("DURANT Éliane") == normalize_name("eliane durant")
    assert normalize_name("Marie-José MARTIN") == normalize_name("martin jose marie")


def test_master_id_is_stable_and_depends_on_key(tmp_path):
    a, b = make(tmp_path), Pseudonymiser("z" * 40, tmp_path / "other")
    assert a.master_id("DURANT Paul") == a.master_id("paul durant")
    assert a.master_id("DURANT Paul") != b.master_id("DURANT Paul")
    assert a.master_id("DURANT Paul").startswith("M-")


def test_public_id_is_per_document_by_default_global_on_request(tmp_path):
    p = make(tmp_path)
    assert p.public_id("DURANT Paul", "doc1") == p.public_id("Paul Durant", "doc1")
    assert p.public_id("DURANT Paul", "doc1") != p.public_id("DURANT Paul", "doc2")
    assert (p.public_id("DURANT Paul", "doc1", "global")
            == p.public_id("DURANT Paul", "doc2", "global"))
    assert p.public_id("DURANT Paul", "doc1") != p.master_id("DURANT Paul")[2:]


def test_short_key_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        Pseudonymiser("short", tmp_path)


def test_find_private_names_follows_wrapped_lists_and_skips_organisations():
    names = [n["name"] for n in find_private_names(SALE)]
    assert names == ["DURANT Jean Marc", "DURANT Éliane", "DURANT Jean-Luc",
                     "DURANT Paul", "DURANT Léa"]
    assert not any("SAFER" in n for n in names)       # organisation, not redacted
    assert find_private_names("Vendeur(s) : SAFER") == []
    assert find_private_names("Vendeur : Durant") == []  # single token is ignored


def test_redaction_handles_either_order_and_leaves_place_names(tmp_path):
    p = make(tmp_path)
    text = "Vendeur(s) : DURANT Paul\nCourrier de Paul Durant reçu.\nLieu : PECH ROSIE, Durant"
    out, n = p.redact(text, "d", 1, ["DURANT Paul"])
    pid = p.public_id("DURANT Paul", "d")
    assert out.count(pid) == 2 and n == 2
    assert "PECH ROSIE" in out and out.endswith("Durant")  # surname alone is not redacted


def test_same_surname_different_person_is_not_redacted(tmp_path):
    p = make(tmp_path)
    out, n = p.redact("DURANT Marie et DURANT Paul", "d", 1, ["DURANT Paul"])
    assert "DURANT Marie" in out and n == 1


def test_redact_extraction_removes_names_registers_and_stays_withheld(tmp_path):
    p = make(tmp_path)
    extraction = {"sha256": "ab" * 32, "pages": [
        {"page": 16, "method": "tesseract", "status": "needs_review",
         "text": SALE, "text_sparse": "DURANT Paul 90 000,00 EUR Léa DURANT"}]}
    red = redact_extraction(extraction, p)
    blob = json.dumps(red, ensure_ascii=False)
    for n in ("DURANT Jean Marc", "Éliane", "DURANT Paul", "Léa DURANT", "Jean-Luc"):
        assert n not in blob
    assert "SAFER" in blob and "PECH ROSIE" in blob
    assert red["privacy"]["public_release"] == "withheld"
    # per page: the larger of the two text variants, i.e. the five names in SALE
    assert red["privacy"]["redactions"] == 5
    assert "DURANT Paul" in json.dumps(extraction, ensure_ascii=False)  # input untouched


def test_registry_lets_maintainer_resolve_ids_and_is_private(tmp_path):
    p = make(tmp_path)
    extraction = {"sha256": "cd" * 32,
                  "pages": [{"page": 3, "text": "Vendeur(s) : DURANT Paul", "method": "x"}]}
    redact_extraction(extraction, p)
    reopened = make(tmp_path)  # registry persisted
    mid = reopened.master_id("DURANT Paul")
    pid = reopened.public_id("DURANT Paul", "cd" * 6)
    by_public = reopened.whois(pid)[0]
    assert by_public["master_id"] == mid and by_public["names_seen"] == ["DURANT Paul"]
    assert by_public["appearances"][0]["page"] == 3
    assert reopened.whois(mid)[0]["names_seen"] == ["DURANT Paul"]
    assert reopened.whois("P-doesnotexist") == []
    assert stat.S_IMODE((tmp_path / "private" / "people.json").stat().st_mode) == 0o600


def test_known_person_is_redacted_even_without_a_label_in_later_documents(tmp_path):
    p = make(tmp_path)
    redact_extraction({"sha256": "01" * 32, "pages": [
        {"page": 1, "text": "Vendeur(s) : DURANT Paul", "method": "x"}]}, p)
    later = redact_extraction({"sha256": "02" * 32, "pages": [
        {"page": 4, "text": "M. Paul DURANT demande une réponse.", "method": "x"}]}, p)
    assert "DURANT" not in later["pages"][0]["text"]
    mid = p.master_id("DURANT Paul")
    assert len(p.registry[mid]["appearances"]) == 1  # unlabelled hit is redacted, not re-registered
    ids = {p.public_id("DURANT Paul", "01" * 6), p.public_id("DURANT Paul", "02" * 6)}
    assert len(ids) == 2  # different public id per document


def test_generate_key_file_is_private_and_never_overwrites(tmp_path):
    path = Pseudonymiser.generate_key_file(tmp_path / "private")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        Pseudonymiser.generate_key_file(tmp_path / "private")
    assert Pseudonymiser.from_environment(tmp_path / "private").master_id("A B")


def test_environment_key_takes_precedence(tmp_path, monkeypatch):
    monkeypatch.setenv(KEY_ENV, "e" * 40)
    assert (Pseudonymiser.from_environment(tmp_path / "p").master_id("A B")
            == Pseudonymiser("e" * 40, tmp_path / "q").master_id("A B"))
    monkeypatch.delenv(KEY_ENV)
    with pytest.raises(RuntimeError):
        Pseudonymiser.from_environment(tmp_path / "nokey")


# ---- public figures allow-list -------------------------------------------------
from echo_montolieu.privacy import PublicFigures  # noqa: E402

OFFICIAL = {"name": "MARTEL Hélène", "category": "elected_official",
            "basis": "https://example.test/minutes-attendance-list"}


def test_public_figures_require_basis_category_and_full_name():
    with pytest.raises(ValueError):
        PublicFigures([{**OFFICIAL, "basis": ""}])
    with pytest.raises(ValueError):
        PublicFigures([{**OFFICIAL, "category": "friend"}])
    with pytest.raises(ValueError):
        PublicFigures([{**OFFICIAL, "name": "Martel"}])


def test_business_owner_needs_diffusion_check():
    biz = {"name": "BLANC Pierre", "category": "business_owner", "basis": "https://example.test/x"}
    with pytest.raises(ValueError):
        PublicFigures([biz])
    assert PublicFigures([{**biz, "diffusion_checked": True}]).allows("Pierre Blanc")


def test_allows_respects_validity_window_and_fails_closed_without_a_date():
    f = PublicFigures([{**OFFICIAL, "valid_from": "2020-05-23", "valid_to": "2026-03-31"}])
    assert f.allows("Hélène MARTEL", "2024-09-18")
    assert not f.allows("Hélène MARTEL", "2026-07-22")
    assert not f.allows("Hélène MARTEL", "2019-01-01")
    assert not f.allows("Hélène MARTEL", None)  # unknown date: not exempt
    assert PublicFigures([OFFICIAL]).allows("martel helene", None)  # no window: always
    assert not PublicFigures([]).allows("Hélène MARTEL", "2024-01-01")


def test_missing_figures_file_means_nobody_is_exempt(tmp_path):
    assert PublicFigures.load(tmp_path / "nope.json").entries == []


def test_official_stays_visible_in_public_role_but_not_in_a_private_sale(tmp_path):
    p = make(tmp_path)
    figures = PublicFigures([OFFICIAL])
    ext = {"sha256": "ee" * 32, "meeting_date": {"value": "2024-09-18"}, "pages": [
        {"page": 1, "method": "x", "text": "Présents : Hélène MARTEL, maire."},
        {"page": 2, "method": "x", "text": "Vendeur(s) : MARTEL Hélène\nLe conseil renonce."},
        {"page": 3, "method": "x", "text": "Mme Hélène MARTEL remercie l'assemblée."}]}
    # Seed the registry as if she had sold land earlier, so she is "known".
    p.register("MARTEL Hélène", "earlier", 9, "Vendeur(s)")
    red = redact_extraction(ext, p, figures=figures)
    t = [pg["text"] for pg in red["pages"]]
    assert "MARTEL" in t[0] and "MARTEL" in t[2]        # public role: visible
    assert "MARTEL" not in t[1]                          # private sale: pseudonymised
    # Same document, same registry, but no allow-list: she is redacted on every page.
    p2 = make(tmp_path / "x")
    p2.register("MARTEL Hélène", "earlier", 9, "Vendeur(s)")
    red2 = redact_extraction(ext, p2, figures=None)
    assert all("MARTEL" not in pg["text"] for pg in red2["pages"])


def test_expired_window_redacts_the_official(tmp_path):
    p = make(tmp_path)
    figures = PublicFigures([{**OFFICIAL, "valid_to": "2026-03-31"}])
    p.register("MARTEL Hélène", "earlier", 9, "Vendeur(s)")
    ext = {"sha256": "ff" * 32, "meeting_date": {"value": "2026-07-22"}, "pages": [
        {"page": 1, "method": "x", "text": "Hélène MARTEL, conseillère."}]}
    assert "MARTEL" not in redact_extraction(ext, p, figures=figures)["pages"][0]["text"]


def test_redacting_twice_does_not_register_pseudonyms_as_people(tmp_path):
    p = make(tmp_path)
    ext = {"sha256": "aa" * 32, "pages": [{"page": 1, "method": "x",
                                           "text": "Vendeur(s) : DURANT Paul, DURANT Léa"}]}
    once = redact_extraction(ext, p)
    before = len(p.registry)
    redact_extraction(once, p)
    assert len(p.registry) == before
