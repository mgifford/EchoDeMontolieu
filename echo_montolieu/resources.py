"""A short page of official public resources about the commune: risks, geology, recorded sales, planning.

The list lives in data/resources.json (an id, a link, and a title and a sentence in each language), so a link is added by
editing that file. Only official public sources belong here; it is not a list of homes for sale or of sale notices.
The page is written in French, English and Dutch by `render`; nothing is fetched.
"""
import json
from pathlib import Path

from . import disclosure

T = {
    "fr": dict(title="Risques locaux et données publiques", basis="Cette page est une liste de liens officiels choisie à la main ; elle n’utilise pas les procès-verbaux.",
               intro="Des cartes et des documents officiels, gratuits, qui aident à connaître un terrain ou une maison avant de s’y intéresser de près.",
               check="Avant un achat", check_text=("Le vendeur doit joindre au contrat de vente un « état des risques et pollutions » à jour, établi pour l’adresse du bien. "
                                                   "Demandez-le tôt et comparez-le avec Géorisques et le DICRIM."),
               note="Ces liens sont donnés à titre d’information ; ils ne remplacent ni un notaire, ni un diagnostic, ni un conseil juridique. Les sites sont ceux de leurs auteurs et peuvent changer.",
               ok="Lien vérifié le"),
    "en": dict(title="Local risks and public data", basis="This page is a hand-chosen list of official links; it does not use the minutes.",
               intro="Free official maps and documents that help you understand a plot or a house before you look at it closely.",
               check="Before buying", check_text=("The seller must attach an up-to-date statement of risks and pollution for the property’s address to the sale contract. "
                                                  "Ask for it early and compare it with Géorisques and the DICRIM."),
               note="These links are for information. They do not replace a notary, a survey or legal advice. The sites belong to their owners and can change.",
               ok="Link checked on"),
    "nl": dict(title="Lokale risico’s en openbare gegevens", basis="Deze pagina is een met de hand gekozen lijst van officiële links; ze gebruikt de notulen niet.",
               intro="Gratis officiële kaarten en documenten waarmee u een perceel of huis leert kennen voordat u het van dichtbij bekijkt.",
               check="Voor een aankoop", check_text=("De verkoper moet bij de verkoopakte een actuele verklaring van risico’s en vervuiling voor het adres van het pand voegen. "
                                                      "Vraag er vroeg om en vergelijk ze met Géorisques en de DICRIM."),
               note="Deze links zijn ter informatie. Ze vervangen geen notaris, expertise of juridisch advies. De sites zijn van hun eigenaars en kunnen veranderen.",
               ok="Link gecontroleerd op"),
}


def load(data_file="data/resources.json"):
    entries = json.loads(Path(data_file).read_text(encoding="utf-8")).get("entries", [])
    return [e for e in entries if str(e.get("url", "")).startswith("https://")]


def render(lang, entries, checked):
    t = T[lang]
    lines = [f"# {t['title']}", "", disclosure.markdown("site", lang), "", f"> {t['basis']}", "", t["intro"], ""]
    for e in entries:
        lines += [f"- [{e['title'][lang]}]({e['url']}): {e['about'][lang]}"]
    lines += ["", f"## {t['check']}", "", t["check_text"], "", f"*{t['note']}* {t['ok']} {checked}.", ""]
    return "\n".join(lines)


def write(public_dir, data_file="data/resources.json", checked="2026-10-10"):
    entries = load(data_file)
    target = Path(public_dir) / "resources"
    target.mkdir(parents=True, exist_ok=True)
    for lang, name in (("fr", "index.md"), ("en", "index.en.md"), ("nl", "index.nl.md")):
        page = disclosure.with_front_matter(render(lang, entries, checked), T[lang]["title"], kind="site")
        if lang == "fr":
            page = page.replace("---\n", "---\nlanguage: fr\n", 1)
        (target / name).write_text(page, encoding="utf-8")
    return {"links": len(entries)}
