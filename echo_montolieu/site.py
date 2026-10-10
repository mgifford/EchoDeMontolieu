"""Static, trilingual site for GitHub Pages: French, English and Dutch trees with one navigation.

  /                 chooser; a small script sends visitors to their language (saved choice, else the browser's)
  /fr/ /en/ /nl/    the same pages in each language, each with the central navigation and a language switcher
  /<lang>/places/map.html  the map, in each language (/places/map.html is a small page that links to the three)

Pages come from the Markdown in public/. A page is shown in the visitor's language when a file for it
exists (for example minutes.en.md); otherwise the page that does exist is shown with a visible notice
saying so, in a block marked with its own language. Markdown is rendered with raw HTML switched off.
Wording of the interface in French and Dutch was written by the AI assistant and has not been reviewed
by a native speaker (see AI.md); the footer says so.
"""
import html
import json
import re
import shutil
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlsplit

from markdown_it import MarkdownIt

from . import disclosure
from .whats_new import string_key

LANGS = ("fr", "en", "nl")
NAMES = {"fr": "Français", "en": "English", "nl": "Nederlands"}
LANG_IN = {"en": {"fr": "French", "en": "English", "nl": "Dutch"},
           "fr": {"fr": "français", "en": "anglais", "nl": "néerlandais"},
           "nl": {"fr": "Frans", "en": "Engels", "nl": "Nederlands"}}
SITE_NAME = "L’Écho de Montolieu"
REPO_URL = "https://github.com/mgifford/EchoDeMontolieu"
SITE_URL = "https://mgifford.github.io/EchoDeMontolieu/"
PANNEAUPOCKET_URL = "https://app.panneaupocket.com/ville/922810321-montolieu-11170"
CSP = ("default-src 'none'; style-src 'self'; script-src 'self'; img-src 'self' data:; "
       "base-uri 'none'; form-action 'none'")
KEY = "echo-lang"

UI = {
    "en": {
        "data_title": "Open data",
        "data_nav": "Open data",
        "e_data": "Open data: the meetings, decisions, votes and places as JSON and CSV files",
        "data_intro": "The same information as this site, as files you can download, open in a spreadsheet or load into your own tools. They are derived and machine-generated: names are replaced, private property sales are counted and never listed, summaries are written by AI models and no person has reviewed them. Every row links to the page of the original document, which is authoritative.",
        "data_files": "Files",
        "data_updated": "Newest meeting in the files: {date}. {meetings} meetings, {decisions} decisions and votes, {places} confirmed places.",
        "data_f_json": "Everything in one file: meetings with their decisions, summaries in the languages that exist, and places.",
        "data_f_meetings": "One row per meeting: date, pages to check, number of decisions, number of private sale notices, link to the original.",
        "data_f_decisions": "One row per agenda item or recovered vote sentence: title, vote, pages, topics, euro amounts, link to the page of the original. For the 2003 to 2008 minutes the French vote sentence is in the text_fr column, with every name replaced.",
        "data_f_places": "One row per confirmed place: name, kind, coordinates, OpenStreetMap link, number of meetings.",
        "data_notes": "Notes",
        "data_n1": "CSV files are UTF-8 with commas. A cell that could be read as a formula by a spreadsheet starts with an apostrophe.",
        "data_n2": "Titles and sentences are in French, the language of the minutes. Summaries are in French, English and Dutch where they exist.",
        "data_n3": "This derived data is released under the Etalab Open Licence 2.0 (Licence Ouverte 2.0). Reuse is free, including commercially, if you credit the source and the date of the data, for example: Source: L’Écho de Montolieu, data of {date}. The licence is compatible with CC BY 4.0. The code is AGPL-3.0. The original minutes are public documents of the Mairie.",
        "data_n4": "Files are rebuilt with the site. For a question that these files do not answer, see the search and the MCP server described in the project README.",
        "data_dl": "Download",
        "data_size": "{kb} KB",
        "all_minutes_long": "See all minutes, back to 2003",
        "home_recent": "Showing the last 12 months ({n} {sets}). Older minutes, {first} to {last}, are on the Meetings page.", "all_minutes": "All minutes",
        "wn_short": "In short",
        "e_whatsnew": "What’s new and what to watch, from the latest minutes",
        "whatsnew": "What’s new",
        "wn_title": "What’s new and what to watch",
        "wn_intro": "A digest of the latest council meetings, made by software from the minutes. It reports what the minutes say was decided, postponed or planned. It does not predict anything. The minutes are published weeks after each meeting, so check the Mairie and PanneauPocket for current notices.",
        "wn_latest": "Latest meetings",
        "wn_decisions": "{n} agenda items",
        "wn_sales": "Private property sale notices: {n} (counted, not listed)",
        "wn_back": "Issues that came back",
        "wn_back_row": "{n} meetings, from {first} to {last}",
        "wn_pending": "Postponed or planned, in the latest minutes",
        "wn_pending_note": "Sentences that look like a postponement or a plan. Candidates found by wording, not a checked list.",
        "wn_dates": "Dates mentioned in the latest minutes",
        "wn_original": "French original", "wn_tr_note": "The titles and sentences below are machine translations of the French minutes. Software checks numbers and legal references; a person has not read them. The French original follows each one.",
        "wn_dates_note": "Dates written in the text, from the meeting date onwards. Check the sentence and the original before relying on one.",
        "wn_dropped": "Possibly dropped",
        "wn_dropped_note": "Postponed at their last mention and not seen again in the meetings since. A heuristic: they may have continued under another title.",
        "wn_dropped_row": "last mentioned {last}; {n} meetings since",
        "wn_watch": "What to keep an eye on",
        "wn_watch_note": "Subjects that come up in the minutes, by how often in the last twelve months.",
        "wn_watch_row": "{items} items in {meetings} meetings in the last twelve months; last on {last}",
        "wn_none": "Nothing found.",
        "wn_feed": "Subscribe with an Atom feed",
        "wn_vote": {"unanimous": "unanimous", "majority": "by majority", "rejected": "rejected"},
        "wn_novote": "no vote found",
        "wn_postponed": "postponed",
        "wn_planned": "planned",
        "wn_more": "All issues over time",
        "wn_feed_entry": "Council meeting of {date}: {n} agenda items",
        "topics": {"finances": "Budget, taxes and borrowing", "subventions": "Subsidies", "urbanisme": "Planning and the local plan (PLU)", "voirie et travaux": "Roads and works", "patrimoine, culture, tourisme": "Heritage, culture and tourism", "personnel": "Staff", "intercommunalité": "Joint bodies and the Grand Carcassonne area", "environnement et risques": "Environment and risks", "école et enfance": "School and children", "associations et vie locale": "Associations and village life"},
        "why": {"finances": "Taxes, the budget and the credit line decide what the village can afford.", "subventions": "Who receives public money, and how much.", "urbanisme": "The revision of the local plan (PLU) sets what can be built where.", "voirie et travaux": "Roads, paths, the church and other works that affect daily life.", "patrimoine, culture, tourisme": "The museum, the church and the village’s visitors.", "personnel": "Posts, grades and benefits of the village staff.", "intercommunalité": "Decisions taken with the neighbouring communes, such as lighting and shared contracts.", "environnement et risques": "Fire, flood and forest risks.", "école et enfance": "School, after-school care and children’s activities.", "associations et vie locale": "Agreements and support for associations."},
        "places_u_h": "Other place names mentioned, not confirmed", "places_u_note": "These names were picked out of the minutes by pattern and could not be matched to a street or place in Montolieu. The links run a search on OpenStreetMap; the result may be empty or point to the wrong place.", "search_osm": "search OpenStreetMap",
        "places_h": "Places discussed in this meeting", "places_note": "Each place was found in the minutes and confirmed by the national address database; the link opens it on OpenStreetMap. A pin shows where the street or place is, not the exact spot a decision concerned. Not every place is found.", "page_abbr": "page",
        "summary": "Summary", "full": "Full minutes", "facts_l": "Facts", "todo_l": "Follow-ups", "orig": "Original",
        "no_summary": "no summary yet", "data_l": "Data", "meeting_nav": "This meeting", "col_date": "Date",
        "meetings_intro": "One page per meeting: an AI-written summary where one exists, the full minutes tidied for reading, and a link to the original. Dates link to the summary when there is one, otherwise to the full minutes.",
        "months": ("January","February","March","April","May","June","July","August","September","October","November","December"),
        "datefmt": "{d} {m} {y}",
        "skip": "Skip to main content", "nav": "Main navigation", "language": "Language",
        "home": "Home", "minutes": "Council minutes", "meetings": "Meetings", "issues": "Issues over time",
        "finance": "Finance", "budget": "Budget", "places": "Places", "map": "Map", "about_ai": "About AI",
        "table": "Table", "open_source": "Open source (AGPL-3.0)", "ai_page": "About AI in this project",
        "review": "The French and Dutch wording of this interface was written by an AI assistant and has not been reviewed by a native speaker.",
        "fallback": "This page is not available in {want} yet. It is shown in {have}.",
        "alerts_h": "Urgent alerts",
        "alerts_p": "For urgent, real-time notices from the Mairie (water cuts, weather warnings, emergencies), use {link}, an external service. This site is not updated in real time.",
        "intro": "This project helps people find information about the village of Montolieu. It points to the pages of the Mairie and other local sites and does not replace them. Text from council minutes is machine-extracted, may contain errors, and is always shown with a link to the original. Check the original before relying on anything.",
        "explore": "Explore",
        "e_meetings": "Each meeting: the minutes, with summaries and follow-ups",
        "e_issues": "what keeps coming back, and what may have been dropped",
        "e_finance": "as far as the minutes state them",
        "e_resources": "Local risks and public data: flood and ground risk, geology, recorded sales",
        "e_places": "Places discussed (list)", "e_zoning": "Planning and heritage zoning, from the national planning portal",
        "e_map": "Map of places discussed",
        "minutes_h": "Council minutes",
        "minutes_total": "{total} {sets} across {years} {yrs} ({span}). Most recent first.", "sets": ("set of minutes", "sets of minutes"), "yrs": ("year", "years"),
        "none_yet": "No minutes have been published yet.",
        "gaps": "No minutes found for: {gaps}. We found none on the Mairie's site or in the Internet Archive; ask the Mairie if you need them.",
        "year_h": "{year}: {n} {sets}", "undated": "Date not detected",
        "read": "read the minutes", "pdf": "original PDF", "archive": "Internet Archive copy", "json": "extracted text (JSON)",
        "changes": "what changed in version {n}", "of": "of {date}",
        "revised": "Revised by the Mairie: {n} versions are kept.",
        "ocr": "OCR was used on {n} page(s); {r} need review.", "draft": " (draft suspected)",
        "where_h": "Where to find things", "where_note": "on {owner}; check there for current details.",
        "owner_default": "the Mairie site",
        "data": "The data is available as JSON: {a} and {b}.",
        "chooser_p": "Choose your language",
    },
    "fr": {
        "data_title": "Données ouvertes",
        "data_nav": "Données ouvertes",
        "e_data": "Données ouvertes : séances, décisions, votes et lieux en fichiers JSON et CSV",
        "data_intro": "Les mêmes informations que ce site, sous forme de fichiers à télécharger, à ouvrir dans un tableur ou à charger dans vos propres outils. Elles sont dérivées et produites automatiquement : les noms sont remplacés, les ventes de biens privés sont comptées et jamais listées, les résumés sont écrits par des modèles d’IA et aucune personne ne les a relus. Chaque ligne renvoie à la page du document original, qui fait foi.",
        "data_files": "Fichiers",
        "data_updated": "Séance la plus récente dans les fichiers : {date}. {meetings} séances, {decisions} décisions et votes, {places} lieux confirmés.",
        "data_f_json": "Tout dans un seul fichier : les séances avec leurs décisions, les résumés dans les langues disponibles, et les lieux.",
        "data_f_meetings": "Une ligne par séance : date, pages à vérifier, nombre de décisions, nombre d’avis de vente de biens privés, lien vers l’original.",
        "data_f_decisions": "Une ligne par point de l’ordre du jour ou par phrase de vote retrouvée : titre, vote, pages, thèmes, montants en euros, lien vers la page de l’original. Pour les procès-verbaux de 2003 à 2008, la phrase de vote en français figure dans la colonne text_fr, tous les noms étant remplacés.",
        "data_f_places": "Une ligne par lieu confirmé : nom, type, coordonnées, lien OpenStreetMap, nombre de séances.",
        "data_notes": "Remarques",
        "data_n1": "Les fichiers CSV sont en UTF-8, séparés par des virgules. Une cellule qu’un tableur pourrait lire comme une formule commence par une apostrophe.",
        "data_n2": "Les titres et les phrases sont en français, la langue des procès-verbaux. Les résumés sont en français, en anglais et en néerlandais quand ils existent.",
        "data_n3": "Ces données dérivées sont publiées sous Licence Ouverte 2.0 (Etalab). La réutilisation est libre, y compris commerciale, à condition de citer la source et la date des données, par exemple : Source : L’Écho de Montolieu, données du {date}. Cette licence est compatible avec CC BY 4.0. Le code est sous AGPL-3.0. Les procès-verbaux originaux sont des documents publics de la Mairie.",
        "data_n4": "Les fichiers sont reconstruits avec le site. Pour une question que ces fichiers ne couvrent pas, voyez la recherche et le serveur MCP décrits dans le README du projet.",
        "data_dl": "Télécharger",
        "data_size": "{kb} Ko",
        "all_minutes_long": "Voir tous les procès-verbaux, depuis 2003",
        "home_recent": "Les 12 derniers mois ({n} {sets}). Les procès-verbaux plus anciens, de {first} à {last}, sont sur la page Séances.", "all_minutes": "Tous les procès-verbaux",
        "wn_short": "En bref",
        "e_whatsnew": "Nouveautés et points à suivre, d’après les derniers procès-verbaux",
        "whatsnew": "Nouveautés",
        "wn_title": "Nouveautés et points à suivre",
        "wn_intro": "Un résumé des derniers conseils municipaux, fait par un logiciel à partir des procès-verbaux. Il rapporte ce que les procès-verbaux disent avoir été décidé, reporté ou prévu. Il ne prédit rien. Les procès-verbaux paraissent des semaines après chaque séance : consultez la Mairie et PanneauPocket pour les avis en cours.",
        "wn_latest": "Dernières séances",
        "wn_decisions": "{n} points à l’ordre du jour",
        "wn_sales": "Avis de vente de biens privés : {n} (comptés, non listés)",
        "wn_back": "Sujets revenus",
        "wn_back_row": "{n} séances, du {first} au {last}",
        "wn_pending": "Reporté ou prévu, dans les derniers procès-verbaux",
        "wn_pending_note": "Phrases qui ressemblent à un report ou à un projet. Candidates repérées par les mots, pas une liste vérifiée.",
        "wn_dates": "Dates citées dans les derniers procès-verbaux",
        "wn_original": "Original", "wn_tr_note": "",
        "wn_dates_note": "Dates écrites dans le texte, à partir de la date de la séance. Vérifiez la phrase et l’original avant de vous y fier.",
        "wn_dropped": "Peut-être abandonnés",
        "wn_dropped_note": "Reportés lors de leur dernière mention et non revus dans les séances suivantes. Une heuristique : ils ont pu continuer sous un autre titre.",
        "wn_dropped_row": "dernière mention le {last} ; {n} séances depuis",
        "wn_watch": "À surveiller",
        "wn_watch_note": "Sujets qui reviennent dans les procès-verbaux, selon leur fréquence sur les douze derniers mois.",
        "wn_watch_row": "{items} points dans {meetings} séances sur les douze derniers mois ; dernier le {last}",
        "wn_none": "Rien trouvé.",
        "wn_feed": "S’abonner avec un flux Atom",
        "wn_vote": {"unanimous": "à l’unanimité", "majority": "à la majorité", "rejected": "rejeté"},
        "wn_novote": "pas de vote repéré",
        "wn_postponed": "reporté",
        "wn_planned": "prévu",
        "wn_more": "Tous les sujets dans le temps",
        "wn_feed_entry": "Conseil municipal du {date} : {n} points à l’ordre du jour",
        "topics": {"finances": "Budget, impôts et emprunts", "subventions": "Subventions", "urbanisme": "Urbanisme et plan local (PLU)", "voirie et travaux": "Voirie et travaux", "patrimoine, culture, tourisme": "Patrimoine, culture et tourisme", "personnel": "Personnel", "intercommunalité": "Intercommunalité et Grand Carcassonne", "environnement et risques": "Environnement et risques", "école et enfance": "École et enfance", "associations et vie locale": "Associations et vie locale"},
        "why": {"finances": "Les impôts, le budget et la ligne de trésorerie fixent ce que le village peut se permettre.", "subventions": "Qui reçoit de l’argent public, et combien.", "urbanisme": "La révision du plan local (PLU) fixe ce qui peut être construit et où.", "voirie et travaux": "Routes, chemins, église et autres travaux qui touchent la vie quotidienne.", "patrimoine, culture, tourisme": "Le musée, l’église et les visiteurs du village.", "personnel": "Postes, grades et avantages du personnel communal.", "intercommunalité": "Décisions prises avec les communes voisines : éclairage, marchés groupés.", "environnement et risques": "Risques d’incendie, d’inondation et de forêt.", "école et enfance": "École, périscolaire et activités pour les enfants.", "associations et vie locale": "Conventions et soutien aux associations."},
        "places_u_h": "Autres noms de lieux cités, non confirmés", "places_u_note": "Ces noms ont été repérés dans le procès-verbal par un motif et n’ont pas pu être rattachés à une rue ou à un lieu de Montolieu. Les liens lancent une recherche sur OpenStreetMap ; le résultat peut être vide ou désigner un autre lieu.", "search_osm": "rechercher sur OpenStreetMap",
        "places_h": "Lieux évoqués dans cette séance", "places_note": "Chaque lieu a été repéré dans le procès-verbal et confirmé par la Base Adresse Nationale ; le lien l’ouvre sur OpenStreetMap. Le repère montre où se trouve la rue ou le lieu, pas l’endroit exact concerné par une décision. Tous les lieux ne sont pas trouvés.", "page_abbr": "page",
        "summary": "Résumé", "full": "Procès-verbal complet", "facts_l": "Faits", "todo_l": "Suites", "orig": "Original",
        "no_summary": "pas encore de résumé", "data_l": "Données", "meeting_nav": "Cette séance", "col_date": "Date",
        "meetings_intro": "Une page par séance : un résumé écrit par une IA quand il existe, le procès-verbal complet mis en forme pour la lecture, et un lien vers l’original. La date mène au résumé s’il existe, sinon au procès-verbal complet.",
        "months": ("janvier","février","mars","avril","mai","juin","juillet","août","septembre","octobre","novembre","décembre"),
        "datefmt": "{d} {m} {y}",
        "skip": "Aller au contenu principal", "nav": "Navigation principale", "language": "Langue",
        "home": "Accueil", "minutes": "Procès-verbaux", "meetings": "Séances", "issues": "Sujets au fil du temps",
        "finance": "Finances", "budget": "Budget", "places": "Lieux", "map": "Carte", "about_ai": "À propos de l’IA",
        "table": "Tableau", "open_source": "Logiciel libre (AGPL-3.0)", "ai_page": "L’IA dans ce projet",
        "review": "Les termes français et néerlandais de cette interface ont été écrits par un assistant d’IA et n’ont pas été relus par un locuteur natif.",
        "fallback": "Cette page n’existe pas encore en {want}. Elle est affichée en {have}.",
        "alerts_h": "Alertes urgentes",
        "alerts_p": "Pour les avis urgents et en temps réel de la mairie (coupures d’eau, alertes météo, urgences), utilisez {link}, un service externe. Ce site n’est pas mis à jour en temps réel.",
        "intro": "Ce projet aide à trouver des informations sur le village de Montolieu. Il renvoie vers les pages de la mairie et d’autres sites locaux et ne les remplace pas. Le texte des procès-verbaux est extrait automatiquement, peut contenir des erreurs et est toujours accompagné d’un lien vers l’original. Vérifiez l’original avant de vous y fier.",
        "explore": "Explorer",
        "e_meetings": "Chaque séance : le procès-verbal, avec résumés et suites à donner",
        "e_issues": "ce qui revient souvent, et ce qui a peut-être été abandonné",
        "e_finance": "dans la mesure où les procès-verbaux les indiquent",
        "e_resources": "Risques locaux et données publiques : inondation et sol, géologie, ventes enregistrées",
        "e_places": "Lieux évoqués (liste)", "e_zoning": "Urbanisme et zonages patrimoniaux, d’après le Géoportail de l’urbanisme",
        "e_map": "Carte des lieux évoqués",
        "minutes_h": "Procès-verbaux du conseil municipal",
        "minutes_total": "{total} {sets} sur {years} {yrs} ({span}). Le plus récent d’abord.", "sets": ("procès-verbal", "procès-verbaux"), "yrs": ("année", "années"),
        "none_yet": "Aucun procès-verbal n’a encore été publié.",
        "gaps": "Aucun procès-verbal trouvé pour : {gaps}. Nous n’en avons trouvé ni sur le site de la mairie ni dans l’Internet Archive ; demandez-les à la mairie si nécessaire.",
        "year_h": "{year} : {n} {sets}", "undated": "Date non détectée",
        "read": "lire le procès-verbal", "pdf": "PDF original", "archive": "copie de l’Internet Archive", "json": "texte extrait (JSON)",
        "changes": "ce qui a changé dans la version {n}", "of": "du {date}",
        "revised": "Révisé par la mairie : {n} versions conservées.",
        "ocr": "L’OCR a servi pour {n} page(s) ; {r} à vérifier.", "draft": " (projet suspecté)",
        "where_h": "Où trouver quoi", "where_note": "sur {owner} ; vérifiez-y les informations à jour.",
        "owner_default": "le site de la mairie",
        "data": "Les données sont disponibles en JSON : {a} et {b}.",
        "chooser_p": "Choisissez votre langue",
    },
    "nl": {
        "data_title": "Open data",
        "data_nav": "Open data",
        "e_data": "Open data: vergaderingen, besluiten, stemmingen en plaatsen als JSON- en CSV-bestanden",
        "data_intro": "Dezelfde informatie als op deze site, als bestanden die u kunt downloaden, in een spreadsheet kunt openen of in uw eigen hulpmiddelen kunt laden. Ze zijn afgeleid en automatisch gemaakt: namen zijn vervangen, verkopen van particuliere panden worden geteld en nooit vermeld, samenvattingen zijn geschreven door AI-modellen en door niemand nagelezen. Elke rij verwijst naar de pagina van het originele document, dat leidend is.",
        "data_files": "Bestanden",
        "data_updated": "Nieuwste vergadering in de bestanden: {date}. {meetings} vergaderingen, {decisions} besluiten en stemmingen, {places} bevestigde plaatsen.",
        "data_f_json": "Alles in één bestand: vergaderingen met hun besluiten, samenvattingen in de beschikbare talen, en plaatsen.",
        "data_f_meetings": "Eén rij per vergadering: datum, te controleren pagina’s, aantal besluiten, aantal meldingen van verkoop van particuliere panden, link naar het origineel.",
        "data_f_decisions": "Eén rij per agendapunt of teruggevonden stemzin: titel, stemming, pagina’s, thema’s, bedragen in euro, link naar de pagina van het origineel. Voor de notulen van 2003 tot 2008 staat de Franse stemzin in de kolom text_fr, met alle namen vervangen.",
        "data_f_places": "Eén rij per bevestigde plaats: naam, soort, coördinaten, OpenStreetMap-link, aantal vergaderingen.",
        "data_notes": "Opmerkingen",
        "data_n1": "CSV-bestanden zijn UTF-8 met komma’s. Een cel die een spreadsheet als formule zou lezen, begint met een apostrof.",
        "data_n2": "Titels en zinnen zijn in het Frans, de taal van de notulen. Samenvattingen zijn in het Frans, Engels en Nederlands waar ze bestaan.",
        "data_n3": "Deze afgeleide gegevens zijn vrijgegeven onder de Franse Licence Ouverte 2.0 (Etalab). Hergebruik is vrij, ook commercieel, mits u de bron en de datum van de gegevens vermeldt, bijvoorbeeld: Bron: L’Écho de Montolieu, gegevens van {date}. De licentie is compatibel met CC BY 4.0. De code valt onder AGPL-3.0. De originele notulen zijn openbare documenten van de Mairie.",
        "data_n4": "De bestanden worden met de site opnieuw opgebouwd. Voor een vraag die deze bestanden niet beantwoorden, zie de zoekfunctie en de MCP-server in de README van het project.",
        "data_dl": "Downloaden",
        "data_size": "{kb} KB",
        "all_minutes_long": "Alle notulen bekijken, vanaf 2003",
        "home_recent": "De laatste 12 maanden ({n} {sets}). Oudere notulen, van {first} tot {last}, staan op de pagina Vergaderingen.", "all_minutes": "Alle notulen",
        "wn_short": "In het kort",
        "e_whatsnew": "Nieuw en om in de gaten te houden, uit de laatste notulen",
        "whatsnew": "Nieuw",
        "wn_title": "Nieuw en om in de gaten te houden",
        "wn_intro": "Een overzicht van de laatste gemeenteraden, door software gemaakt uit de notulen. Het meldt wat volgens de notulen is besloten, uitgesteld of gepland. Het voorspelt niets. De notulen verschijnen weken na elke vergadering: raadpleeg de Mairie en PanneauPocket voor actuele berichten.",
        "wn_latest": "Laatste vergaderingen",
        "wn_decisions": "{n} agendapunten",
        "wn_sales": "Meldingen van verkoop van particuliere panden: {n} (geteld, niet vermeld)",
        "wn_back": "Onderwerpen die terugkwamen",
        "wn_back_row": "{n} vergaderingen, van {first} tot {last}",
        "wn_pending": "Uitgesteld of gepland, in de laatste notulen",
        "wn_pending_note": "Zinnen die op een uitstel of plan lijken. Kandidaten op grond van woorden, geen gecontroleerde lijst.",
        "wn_dates": "Data genoemd in de laatste notulen",
        "wn_original": "Frans origineel", "wn_tr_note": "De titels en zinnen hieronder zijn machinevertalingen van de Franse notulen. Software controleert getallen en wettelijke verwijzingen; een persoon heeft ze niet gelezen. Het Franse origineel staat na elke vertaling.",
        "wn_dates_note": "Data die in de tekst staan, vanaf de datum van de vergadering. Controleer de zin en het origineel voordat u erop vertrouwt.",
        "wn_dropped": "Mogelijk vergeten",
        "wn_dropped_note": "Bij de laatste vermelding uitgesteld en in de latere vergaderingen niet meer gezien. Een vuistregel: ze kunnen onder een andere titel zijn doorgegaan.",
        "wn_dropped_row": "laatst genoemd op {last}; {n} vergaderingen sindsdien",
        "wn_watch": "Om in de gaten te houden",
        "wn_watch_note": "Onderwerpen die in de notulen terugkomen, naar frequentie in de laatste twaalf maanden.",
        "wn_watch_row": "{items} punten in {meetings} vergaderingen in de laatste twaalf maanden; laatst op {last}",
        "wn_none": "Niets gevonden.",
        "wn_feed": "Abonneren met een Atom-feed",
        "wn_vote": {"unanimous": "unaniem", "majority": "bij meerderheid", "rejected": "verworpen"},
        "wn_novote": "geen stemming gevonden",
        "wn_postponed": "uitgesteld",
        "wn_planned": "gepland",
        "wn_more": "Alle onderwerpen in de tijd",
        "wn_feed_entry": "Gemeenteraad van {date}: {n} agendapunten",
        "topics": {"finances": "Begroting, belastingen en leningen", "subventions": "Subsidies", "urbanisme": "Ruimtelijke ordening en het lokale plan (PLU)", "voirie et travaux": "Wegen en werken", "patrimoine, culture, tourisme": "Erfgoed, cultuur en toerisme", "personnel": "Personeel", "intercommunalité": "Samenwerking en Grand Carcassonne", "environnement et risques": "Milieu en risico’s", "école et enfance": "School en kinderen", "associations et vie locale": "Verenigingen en dorpsleven"},
        "why": {"finances": "Belastingen, begroting en kredietlijn bepalen wat het dorp zich kan veroorloven.", "subventions": "Wie openbaar geld krijgt, en hoeveel.", "urbanisme": "De herziening van het lokale plan (PLU) bepaalt wat waar gebouwd mag worden.", "voirie et travaux": "Wegen, paden, de kerk en andere werken die het dagelijks leven raken.", "patrimoine, culture, tourisme": "Het museum, de kerk en de bezoekers van het dorp.", "personnel": "Functies, rangen en voordelen van het gemeentepersoneel.", "intercommunalité": "Besluiten met de buurgemeenten, zoals verlichting en gezamenlijke contracten.", "environnement et risques": "Brand-, overstromings- en bosrisico’s.", "école et enfance": "School, naschoolse opvang en activiteiten voor kinderen.", "associations et vie locale": "Overeenkomsten met en steun aan verenigingen."},
        "places_u_h": "Andere genoemde plaatsnamen, niet bevestigd", "places_u_note": "Deze namen zijn met een patroon uit de notulen gehaald en konden niet aan een straat of plaats in Montolieu worden gekoppeld. De links starten een zoekopdracht op OpenStreetMap; het resultaat kan leeg zijn of naar een andere plek wijzen.", "search_osm": "zoeken op OpenStreetMap",
        "places_h": "Plaatsen die in deze vergadering aan bod kwamen", "places_note": "Elke plaats is in de notulen gevonden en bevestigd door de nationale adressendatabase; de link opent ze op OpenStreetMap. Een speld toont waar de straat of plaats ligt, niet de exacte plek waarop een besluit betrekking had. Niet elke plaats wordt gevonden.", "page_abbr": "pagina",
        "summary": "Samenvatting", "full": "Volledige notulen", "facts_l": "Feiten", "todo_l": "Vervolg", "orig": "Origineel",
        "no_summary": "nog geen samenvatting", "data_l": "Gegevens", "meeting_nav": "Deze vergadering", "col_date": "Datum",
        "meetings_intro": "Eén pagina per vergadering: een door AI geschreven samenvatting waar die bestaat, de volledige notulen leesbaar opgemaakt, en een link naar het origineel. De datum verwijst naar de samenvatting, anders naar de volledige notulen.",
        "months": ("januari","februari","maart","april","mei","juni","juli","augustus","september","oktober","november","december"),
        "datefmt": "{d} {m} {y}",
        "skip": "Naar de hoofdinhoud", "nav": "Hoofdnavigatie", "language": "Taal",
        "home": "Home", "minutes": "Notulen", "meetings": "Vergaderingen", "issues": "Onderwerpen in de tijd",
        "finance": "Financiën", "budget": "Begroting", "places": "Plaatsen", "map": "Kaart", "about_ai": "Over AI",
        "table": "Tabel", "open_source": "Open source (AGPL-3.0)", "ai_page": "AI in dit project",
        "review": "De Franse en Nederlandse teksten van deze interface zijn door een AI-assistent geschreven en niet door een moedertaalspreker nagelezen.",
        "fallback": "Deze pagina is nog niet beschikbaar in het {want}. Ze wordt getoond in het {have}.",
        "alerts_h": "Dringende meldingen",
        "alerts_p": "Voor dringende meldingen in realtime van de gemeente (waterafsluitingen, weerswaarschuwingen, noodgevallen) gebruikt u {link}, een externe dienst. Deze site wordt niet in realtime bijgewerkt.",
        "intro": "Dit project helpt mensen informatie over het dorp Montolieu te vinden. Het verwijst naar de pagina’s van de gemeente en andere lokale sites en vervangt ze niet. Tekst uit de notulen is automatisch uitgelezen, kan fouten bevatten en wordt altijd met een link naar het origineel getoond. Controleer het origineel voordat u erop vertrouwt.",
        "explore": "Verkennen",
        "e_meetings": "Elke vergadering: de notulen, met samenvattingen en vervolgacties",
        "e_issues": "wat steeds terugkomt, en wat misschien is blijven liggen",
        "e_finance": "voor zover de notulen ze vermelden",
        "e_resources": "Lokale risico’s en openbare gegevens: overstroming en bodem, geologie, geregistreerde verkopen",
        "e_places": "Besproken plaatsen (lijst)", "e_zoning": "Ruimtelijke ordening en erfgoedzones, volgens het nationale planningsportaal",
        "e_map": "Kaart van besproken plaatsen",
        "minutes_h": "Notulen van de gemeenteraad",
        "minutes_total": "{total} {sets} uit {years} {yrs} ({span}). Meest recente eerst.", "sets": ("set notulen", "sets notulen"), "yrs": ("jaar", "jaar"),
        "none_yet": "Er zijn nog geen notulen gepubliceerd.",
        "gaps": "Geen notulen gevonden voor: {gaps}. We vonden er geen op de site van de gemeente of in het Internet Archive; vraag ze aan de gemeente als u ze nodig hebt.",
        "year_h": "{year}: {n} {sets}", "undated": "Datum niet gevonden",
        "read": "lees de notulen", "pdf": "originele pdf", "archive": "kopie uit het Internet Archive", "json": "uitgelezen tekst (JSON)",
        "changes": "wat er in versie {n} veranderde", "of": "van {date}",
        "revised": "Herzien door de gemeente: {n} versies bewaard.",
        "ocr": "OCR is gebruikt op {n} pagina(’s); {r} te controleren.", "draft": " (vermoedelijk concept)",
        "where_h": "Waar vindt u wat", "where_note": "op {owner}; controleer daar de actuele gegevens.",
        "owner_default": "de site van de gemeente",
        "data": "De gegevens zijn beschikbaar als JSON: {a} en {b}.",
        "chooser_p": "Kies uw taal",
    },
}
def _word(lang, key, n):
    one, many = UI[lang][key]
    return one if n == 1 else many


_MD = MarkdownIt("commonmark", {"html": False, "linkify": False}).enable("table").enable("strikethrough")
_FRONT = re.compile(r"\A---\n(.*?)\n---\n", re.S)
_TRANSLATION_LINK = re.compile(r" · \[[^\]]*\]\([^)]*\.(?:en|nl)\.md\)")


def anchor(text):
    """Heading id; the same rule the Markdown writer used for its table of contents."""
    return re.sub(r"[^a-z0-9]+", "-", re.sub(r"[àâä]", "a", re.sub(r"[éèêë]", "e", text.lower()))).strip("-")


def split_front(text):
    m = _FRONT.match(text)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).splitlines():
        k, _, v = line.partition(":")
        meta[k.strip()] = v.strip().strip('"')
    return meta, text[m.end():]


def _fix_href(href, root=""):
    parts = urlsplit(href)
    if parts.scheme or parts.netloc or not parts.path:
        return href
    path = re.sub(r"(?:\.(?:en|nl))?\.md$", ".html", parts.path)
    return path + (f"#{parts.fragment}" if parts.fragment else "")


def render_markdown(text, table_label, root=""):
    """HTML for a Markdown page: heading ids, .md links turned into .html, tables in a labelled scroll region."""
    tokens = _MD.parse(text)
    seen = {}
    for i, tok in enumerate(tokens):
        if tok.type == "heading_open":
            base = anchor(tokens[i + 1].content.split(" [p.")[0])      # the contents list links to the title, not the page mark
            if base:
                n = seen.get(base, 0)
                seen[base] = n + 1
                tok.attrSet("id", base if n == 0 else f"{base}-{n}")
        if tok.type == "inline":
            for child in tok.children or []:
                if child.type == "link_open":
                    child.attrSet("href", _fix_href(child.attrGet("href") or "", root))
    out = _MD.renderer.render(tokens, _MD.options, {})
    out = re.sub(r"<th(?=[ >])", '<th scope="col"', out)
    count = iter(range(1, 10_000))       # region names must be unique on a page
    out = re.sub(r"<table>", lambda _: f'<div class="tablewrap" role="region" aria-label="{html.escape(table_label)} {next(count)}" tabindex="0"><table>', out)
    return out.replace("</table>", "</table></div>")


def first_heading(text, default):
    m = re.search(r"^# (.+)$", text, re.M)
    return re.sub(r"[`*_\\]", "", m.group(1)).strip() if m else default


def _read_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def pick(base, lang):
    """(path, language of the text) for the page `base` (a path without .md) as seen in `lang`, or None."""
    translated = base.with_name(f"{base.name}.{lang}.md")
    if translated.exists():
        return translated, lang
    original = base.with_name(f"{base.name}.md")
    if original.exists():
        meta, _ = split_front(original.read_text(encoding="utf-8"))
        return original, meta.get("language", "en")
    return None


def page_bases(public):
    """Every page in public/ as (relative path without extension), counting a page once however many languages it has."""
    bases = set()
    for p in Path(public).rglob("*.md"):
        rel = p.relative_to(public)
        if rel.parts[0] == "redacted":
            continue
        stem = re.sub(r"\.(?:en|nl)$", "", rel.with_suffix("").as_posix())
        bases.add(stem)
    return sorted(bases)


class Page:
    def __init__(self, lang, rel, title, body, content_lang=None, description=None):
        self.lang, self.rel, self.title, self.body = lang, rel, title, body
        self.content_lang, self.description = content_lang or lang, description

    @property
    def depth(self):
        return self.rel.count("/")


def _up(depth):
    return "../" * depth


# Language of parts (WCAG 3.1.2). Pages made from the minutes quote French titles and sentences inside English or Dutch text.
# The generators know which words those are but write plain Markdown, so the builder marks them here: a stretch of text that
# is clearly French gets <span lang="fr">. Only text that carries no `lang` of its own is touched.
_STRONG_FR = frozenset("le la les des du un une pour dans au aux avec cette ces ses leur sont été est il qui et elle elles nous vous sur par ou".split())
_OTHER = frozenset("the of and to in is are for with on that this by an as it be was were from at or not which their its has have"
                   " het een van op te dat die voor met zijn niet aan er door als ook bij naar of dit deze worden werd".split())
_SKIP_TAGS = frozenset(("script", "style", "title", "head", "code", "pre", "svg", "textarea"))
_VOID_TAGS = frozenset(("br", "img", "meta", "link", "input", "hr", "source", "area", "base", "col", "wbr"))
_TOKEN = re.compile(r"(<!--.*?-->|<[^>]+>)", re.S)
_WORDS = re.compile(r"[^\W\d_]+", re.U)                   # d’une counts as d + une


def is_french(text):
    """True when `text` is French prose or a French title: two French function words and more of them than English or Dutch ones,
    or one French function word and none from either other language. Under three words, or doubtful, it is left alone."""
    words = [w.lower() for w in _WORDS.findall(text)]
    if len(words) < 3:
        return False
    fr = sum(1 for w in words if w in _STRONG_FR)
    other = sum(1 for w in words if w in _OTHER)
    return (fr >= 2 and fr > 2 * other) or (fr >= 1 and other == 0)


def mark_french(fragment):
    """`fragment` (HTML) with each clearly French text node outside any element that already has a `lang` wrapped in <span lang="fr">."""
    out, stack, skip = [], [], 0
    for piece in _TOKEN.split(fragment):
        if not piece:
            continue
        if piece.startswith("<!--"):
            out.append(piece)
        elif piece.startswith("<"):
            out.append(piece)
            m = re.match(r"<(/?)([a-zA-Z0-9]+)([^>]*)>", piece)
            if not m:
                continue
            closing, tag, rest = m.group(1) == "/", m.group(2).lower(), m.group(3)
            if tag in _VOID_TAGS or rest.rstrip().endswith("/"):
                continue
            if closing:
                while stack:                                       # pop up to the matching open tag
                    top = stack.pop()
                    if top[0] == tag:
                        skip -= top[2]
                        break
            else:
                has_lang = bool(re.search(r"\slang\s*=", rest))
                is_skip = tag in _SKIP_TAGS
                stack.append((tag, has_lang, 1 if (has_lang or is_skip) else 0))
                skip += 1 if (has_lang or is_skip) else 0
        else:
            if skip == 0 and piece.strip():
                # Punctuation, and a trailing "(street):"-style note in the page's own language, stay outside the French span.
                core = re.match(r"^(\s*[)\]\[(;,.:]*\s*)(.*?)((?:\s*\([^()]*\))?[\s:;,.()\]]*)$", piece, re.S)
                if core and core.group(2) and is_french(html.unescape(core.group(2))):
                    piece = f'{core.group(1)}<span lang="fr">{core.group(2)}</span>{core.group(3)}'
            out.append(piece)
    return "".join(out)


def layout(page, available_langs, budget=False):
    """Full HTML document: skip link, header with central navigation and language switcher, main, footer."""
    lang, ui, d = page.lang, UI[page.lang], page.depth
    root = _up(d + 1)                 # the site root, from this page
    home = _up(d) or "./"             # this language's home
    e = html.escape
    nav_items = [("home", home + "index.html", "index.html"), ("minutes", home + "meetings/index.html", "meetings/index.html"),
                 ("whatsnew", home + "whats-new/index.html", "whats-new/index.html"),
                 ("meetings", home + "meetings/index.html", None),
                 ("issues", home + "topics/index.html", "topics/index.html"),
                 ("finance", home + "finance/index.html", "finance/index.html"),
                 *([("budget", home + "finance/budget.html", "finance/budget.html")] if budget else []),
                 ("places", home + "places/index.html", "places/index.html"),
                 ("map", home + "places/map.html", "places/map.html"), ("about_ai", disclosure.AI_PAGE_URL, None)]
    links = []
    for key, href, own in nav_items:
        current = ' aria-current="page"' if own and own == page.rel else ""
        links.append(f'<li><a href="{e(href)}"{current}>{e(ui[key])}</a></li>')
    switch = []
    for code in LANGS:
        href = f"{root}{code}/{page.rel}"
        cur = ' aria-current="true"' if code == lang else ""
        switch.append(f'<li><a href="{e(href)}" lang="{code}" hreflang="{code}" data-setlang="{code}"{cur}>{NAMES[code]}</a></li>')
    alternates = "".join(f'<link rel="alternate" hreflang="{c}" href="{root}{c}/{page.rel}">' for c in LANGS)
    notice = ""
    if page.content_lang != lang:
        notice = (f'<p class="notice" role="note">{e(ui["fallback"].format(want=LANG_IN[lang][lang], have=LANG_IN[lang][page.content_lang]))}</p>')
    content = mark_french(page.body) if page.content_lang != "fr" else page.body
    body = f'<div lang="{page.content_lang}">{content}</div>' if page.content_lang != lang else content
    title = f"{page.title} – {SITE_NAME}" if page.rel != "index.html" else SITE_NAME
    return f"""<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="{CSP}">
<title>{e(title)}</title>
{f'<meta name="description" content="{e(page.description)}">' if page.description else ''}
{alternates}<link rel="alternate" hreflang="x-default" href="{root}">
<link rel="stylesheet" href="{root}assets/site.css">
<script src="{root}assets/site.js" defer></script>
</head>
<body>
<a class="skip" href="#main">{e(ui['skip'])}</a>
<header>
<p class="brand"><a href="{home}index.html" lang="fr">{SITE_NAME}</a></p>
<nav aria-label="{e(ui['nav'])}"><ul>{''.join(links)}</ul></nav>
<nav aria-label="{e(ui['language'])}" class="langs"><ul>{''.join(switch)}</ul></nav>
</header>
<main id="main" tabindex="-1">
{notice}
{body}
</main>
<footer>
{disclosure.html('site', lang)}
<p class="note">{e(ui['review'])}</p>
<p class="note">{e(ui['open_source'])}: <a href="{REPO_URL}">{REPO_URL}</a>. <a href="{disclosure.AI_PAGE_URL}">{e(ui['ai_page'])}</a>.</p>
</footer>
</body>
</html>
"""


def human_date(lang, iso):
    """'2025-06-24' as '24 June 2025' (localised); anything else is returned unchanged."""
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", iso or "")
    if not m:
        return iso or ""
    y, mo, d = m.groups()
    day = "1er" if lang == "fr" and d == "01" else str(int(d))
    return UI[lang]["datefmt"].format(d=day, m=UI[lang]["months"][int(mo) - 1], y=y)


def meeting_files(public):
    """folder -> set of page names that exist for it (minutes, summary, facts, todo), in any language."""
    out = {}
    for f in (Path(public) / "meetings").glob("*/*.md"):
        name = re.sub(r"\.(?:en|nl)$", "", f.stem)
        out.setdefault(f.parent.name, set()).add(name)
    return out


def meeting_links(lang, folder, have, prefix=""):
    """Human-readable links to one meeting's pages: [(label, href)], summary first."""
    ui = UI[lang]
    pairs = [("summary", "summary"), ("full", "minutes"), ("facts_l", "facts"), ("todo_l", "todo")]
    return [(ui[label], f"{prefix}{folder}/{name}.html") for label, name in pairs if name in have]


def meetings_list(lang, index, folders, files, prefix="meetings/", up="../", every=False, since=None):
    """The minutes as a list: a dated heading, then Summary, Full minutes and Original as plain links."""
    ui, e = UI[lang], html.escape
    by_year = {}
    docs = sorted(index.get("documents", []), key=lambda d: ((d.get("meeting_date") or {}).get("value") or "", d.get("filename") or ""), reverse=True)
    for d in docs:
        when = (d.get("meeting_date") or {}).get("value")
        if since and (not when or when < since):
            continue
        folder = folders.get(d["document_id"])
        shown = e(human_date(lang, when)) if when else e(ui["undated"])
        about = f'<span class="sr"> {e(ui["of"].format(date=human_date(lang, when)))}</span>' if when else ""
        have = files.get(folder, set()) if folder else set()
        links = [f'<a href="{prefix}{e(href)}">{e(label)}{about}</a>' for label, href in meeting_links(lang, folder, have)
                 if every or label in (ui["summary"], ui["full"])] if folder else []
        if folder and "summary" not in have:
            links.insert(0, f'<span class="note">{e(ui["no_summary"])}</span>')
        src = d.get("source_url")
        if src and src.startswith("https://"):
            label = ui["archive"] if src.startswith("https://web.archive.org/") else ui["pdf"]
            links.append(f'<a href="{e(src)}" lang="fr">{e(label)}{about}</a>')
        data = [f'<a href="{up}minutes/{e(d["document_id"])}.json">{e(ui["json"])}{about}</a>']
        n = d.get("versions", 1)
        flags = ""
        if n > 1:
            data.append(f'<a href="{up}minutes/{e(d["document_id"])}/diff-v{n - 1}-v{n}.json">{e(ui["changes"].format(n=n))}{about}</a>')
            flags += " " + ui["revised"].format(n=n)
        if d.get("ocr_pages"):
            flags += " " + ui["ocr"].format(n=len(d["ocr_pages"]), r=len(d.get("needs_review_pages", [])))
        lead = f'<strong>{shown}</strong>{e(ui["draft"]) if d.get("draft_suspected") else ""}'
        by_year.setdefault(when[:4] if when else "undated", []).append(
            f'<li>{lead}: {" · ".join(links)}.{e(flags)} <span class="note">{e(ui["data_l"])}: {", ".join(data)}.</span></li>')
    return by_year


def minutes_summary(lang, by_year):
    """'N sets of minutes across Y years (span)' and the list of years with none. ("", "") when there are no minutes."""
    ui, e = UI[lang], html.escape
    years = sorted((y for y in by_year if y != "undated"), reverse=True)
    total = sum(len(v) for v in by_year.values())
    if not total:
        return "", ""
    span = f"{years[-1]}–{years[0]}" if len(years) > 1 else (years[0] if years else "")
    missing = [y for y in range(int(years[-1]), int(years[0])) if str(y) not in by_year] if years else []
    gaps, run = [], []
    for y in missing + [None]:
        if run and (y is None or y != run[-1] + 1):
            gaps.append(str(run[0]) if len(run) == 1 else f"{run[0]}–{run[-1]}")
            run = []
        if y is not None:
            run.append(y)
    line = f'<p>{e(ui["minutes_total"].format(total=total, sets=_word(lang, "sets", total), years=len(years), yrs=_word(lang, "yrs", len(years)), span=span))}</p>'
    gap_note = f'<p class="note">{e(ui["gaps"].format(gaps="; ".join(gaps)))}</p>' if gaps else ""
    return line, gap_note


def recent_since(index, days=365):
    """The date `days` before the latest dated meeting (so a build never changes by itself), or None."""
    dates = [(d.get("meeting_date") or {}).get("value") for d in index.get("documents", [])]
    dates = [d for d in dates if d]
    if not dates:
        return None
    return (date.fromisoformat(max(dates)) - timedelta(days=days)).isoformat()


def meetings_index_body(lang, index, folders, files):
    """The meetings page: every meeting by year with all its pages as plain links."""
    ui, e = UI[lang], html.escape
    by_year = meetings_list(lang, index, folders, files, prefix="", up="../../", every=True)
    parts = [f'<h1>{e(ui["meetings"])}</h1>', disclosure.html("rules", lang), f'<p>{e(ui["meetings_intro"])}</p>', *minutes_summary(lang, by_year)]
    for y in sorted((y for y in by_year if y != "undated"), reverse=True) + (["undated"] if "undated" in by_year else []):
        heading = ui["undated"] if y == "undated" else y
        parts.append(f'<h2 id="y{y}">{e(heading)}</h2><ul>{"".join(by_year[y])}</ul>')
    return "\n".join(parts)


def _insert_after_h1(body, section):
    """Put `section` right after the page's first heading (after the navigation strip, before the long text)."""
    if not section:
        return body
    m = re.search(r"</h1>", body)
    return body[:m.end()] + section + body[m.end():] if m else section + body


def _osm_pin(p):
    """OpenStreetMap link to a pin. Written here, not imported from places.py, so the site builder keeps its one dependency."""
    return f"https://www.openstreetmap.org/?mlat={p['lat']:.6f}&mlon={p['lon']:.6f}#map=18/{p['lat']:.6f}/{p['lon']:.6f}"


def map_with_site_navigation(text, lang, budget=False):
    """The map page is its own document (Leaflet needs its own content security policy), so it gets the site's
    top navigation here, at build time: the shared stylesheet, the same menu, and a language switcher that stays on the map.
    `text` is the page for `lang`, published at /<lang>/places/map.html."""
    ui, e = UI[lang], html.escape
    items = [("home", "../index.html"), ("minutes", "../meetings/index.html"), ("whatsnew", "../whats-new/index.html"),
             ("meetings", "../meetings/index.html"),
             ("issues", "../topics/index.html"), ("finance", "../finance/index.html"),
             *([("budget", "../finance/budget.html")] if budget else []), ("places", "../places/index.html"),
             ("map", None), ("about_ai", disclosure.AI_PAGE_URL)]
    links = "".join(f'<li><a href="{e(href)}">{e(ui[key])}</a></li>' if href else
                    f'<li><a href="map.html" aria-current="page">{e(ui[key])}</a></li>' for key, href in items)
    langs = "".join(f'<li><a href="../../{code}/places/map.html" lang="{code}" hreflang="{code}" data-setlang="{code}"'
                    f'{" aria-current=\"true\"" if code == lang else ""}>{NAMES[code]}</a></li>' for code in LANGS)
    header = (f'<header>\n<p class="brand"><a href="../index.html" lang="fr">{SITE_NAME}</a></p>\n'
              f'<nav aria-label="{e(ui["nav"])}"><ul>{links}</ul></nav>\n'
              f'<nav aria-label="{e(ui["language"])}" class="langs"><ul>{langs}</ul></nav>\n</header>\n')
    # The page's own title bar was a <header>; with the site header above it, the page would have two banners, and a title
    # outside <main> would sit outside every landmark. So the title becomes the first thing inside <main>.
    title = re.search(r"<header>(<h1>.*?</h1>)</header>\n?", text)
    if title:
        text = text.replace(title.group(0), "", 1).replace('<main id="main">', '<main id="main">\n' + title.group(1), 1)
    text = text.replace("<style>", '<link rel="stylesheet" href="../../assets/site.css">\n<style>', 1)
    text = text.replace("</head>", '<script src="../../assets/site.js" defer></script>\n</head>', 1)
    text = re.sub(r"(style-src )", r"\1'self' ", text, count=1)
    text = re.sub(r"(script-src )", r"\1'self' ", text, count=1)
    skip = re.search(r'<a class="skip"[^>]*>.*?</a>\n', text)          # the page's own skip link stays first in the tab order
    at = skip.end() if skip else text.index("<body>\n") + len("<body>\n")
    text = text[:at] + header + text[at:]
    if lang != "fr":
        head, sep, rest = text.partition("<body>")
        text = head + sep + mark_french(rest) if sep else text
    return text


def map_redirect_page():
    """/places/map.html: older links land here, one click from the map in each language."""
    links = "".join(f'<li><a href="../{c}/places/map.html" lang="{c}" hreflang="{c}">{NAMES[c]}</a></li>' for c in LANGS)
    return ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'self'; base-uri 'none'\">\n"
            '<meta http-equiv="refresh" content="0; url=../en/places/map.html">\n<title>Map / Carte / Kaart</title>\n'
            '<link rel="stylesheet" href="../assets/site.css">\n</head>\n<body>\n<main id="main">\n'
            f"<h1>Map / Carte / Kaart</h1>\n<ul class=\"choose\">{links}</ul>\n</main>\n</body>\n</html>\n")


def place_links(public):
    """folder -> {"confirmed": [{label, kind, osm, pages}], "unconfirmed": [{label, kind, search, pages}]}."""
    try:
        data = _read_json(Path(public) / "places" / "places.json", {})
        data = data if isinstance(data, dict) else {}
    except ValueError:                  # an unreadable places file just means no place links
        data = {}
    out = {}

    def add(kind, entry, items):
        by_folder = {}
        for it in items:
            by_folder.setdefault(it["folder"], []).append((it["page"], it.get("url")))
        for folder, pages in by_folder.items():
            out.setdefault(folder, {"confirmed": [], "unconfirmed": []})[kind].append({**entry, "pages": sorted(set(pages))})

    for p in data.get("places", []):
        add("confirmed", {"label": p["label"], "kind": p.get("kind"), "osm": _osm_pin(p)}, p.get("items", []))
    for m in data.get("unconfirmed_mentions", []):
        add("unconfirmed", {"label": m["label"], "kind": m.get("kind"), "search": m["search"]}, m.get("items", []))
    return out


def _page_links(ui, pages):
    e = html.escape
    return ", ".join((f'<a href="{e(u)}#page={n}">{e(ui["page_abbr"])} {n}</a>' if u else f'{e(ui["page_abbr"])} {n}') for n, u in pages)


def places_section(lang, found):
    """OpenStreetMap links for the places in one meeting: confirmed ones as map pins, the rest as search links."""
    if not found or not (found["confirmed"] or found["unconfirmed"]):
        return ""
    ui, e = UI[lang], html.escape
    parts = []
    if found["confirmed"]:
        items = [f'<li><a href="{e(p["osm"])}" lang="fr">{e(p["label"])}</a> ({e(p["kind"] or "")}; {_page_links(ui, p["pages"])})</li>'
                 for p in sorted(found["confirmed"], key=lambda p: p["label"].lower())]
        parts.append(f'<section aria-labelledby="places-h"><h2 id="places-h">{e(ui["places_h"])}</h2><ul>{"".join(items)}</ul>'
                     f'<p class="note">{e(ui["places_note"])}</p></section>')
    if found["unconfirmed"]:
        items = [f'<li><span lang="fr">{e(p["label"])}</span> ({e(p["kind"] or "")}; {_page_links(ui, p["pages"])}): '
                 f'<a href="{e(p["search"])}">{e(ui["search_osm"])}<span class="sr"> : {e(p["label"])}</span></a></li>'
                 for p in sorted(found["unconfirmed"], key=lambda p: p["label"].lower())]
        parts.append(f'<section aria-labelledby="places-u-h"><h2 id="places-u-h">{e(ui["places_u_h"])}</h2><ul>{"".join(items)}</ul>'
                     f'<p class="note">{e(ui["places_u_note"])}</p></section>')
    return f'<div lang="{lang}">{"".join(parts)}</div>'      # the section is in the visitor's language even inside French minutes


def data_page_body(lang, info, sizes):
    """The Open data page: what the files are, how to read them, where they are and what they do not promise."""
    ui, e = UI[lang], html.escape
    names = [("council.json", "data_f_json"), ("meetings.csv", "data_f_meetings"), ("decisions.csv", "data_f_decisions"), ("places.csv", "data_f_places")]
    rows = "".join(f'<li><a href="../../data/{n}" download>{e(n)}</a> <span class="note">({e(ui["data_size"].format(kb=max(1, round(sizes.get(n, 0) / 1024))))})</span>: {e(ui[k])}</li>'
                   for n, k in names)
    notes = "".join(f"<li>{e(ui[k].format(date=human_date(lang, info.get('newest_meeting'))))}</li>" for k in ("data_n1", "data_n2", "data_n3", "data_n4"))
    licence = {"fr": "Licence Ouverte 2.0 (Etalab)", "en": "Etalab Open Licence 2.0 (Licence Ouverte 2.0)", "nl": "Franse Licence Ouverte 2.0 (Etalab)"}[lang]
    notes = notes.replace(licence, f'<a href="https://www.etalab.gouv.fr/licence-ouverte-open-licence/">{e(licence)}</a>', 1)
    return (f'<h1>{e(ui["data_title"])}</h1>{disclosure.html("rules", lang)}<p>{e(ui["data_intro"])}</p>'
            f'<p>{e(ui["data_updated"].format(date=human_date(lang, info.get("newest_meeting")), meetings=info.get("counts", {}).get("meetings", 0), decisions=info.get("counts", {}).get("decisions", 0), places=info.get("counts", {}).get("places", 0)))}</p>'
            f'<h2>{e(ui["data_files"])}</h2><ul>{rows}</ul><h2>{e(ui["data_notes"])}</h2><ul>{notes}</ul>')


def meeting_nav(lang, folder, name, files):
    """Strip at the top of a meeting page linking its sibling pages (summary, full minutes, facts, follow-ups)."""
    ui, e = UI[lang], html.escape
    items = []
    for label, href in meeting_links(lang, folder, files.get(folder, set())):
        here = href.endswith(f"/{name}.html")
        items.append(f'<li><a href="{e(href.split("/", 1)[1])}"{" aria-current=\"page\"" if here else ""}>{e(label)}</a></li>')
    return f'<nav class="mnav" aria-label="{e(ui["meeting_nav"])}"><ul>{"".join(items)}</ul></nav>' if len(items) > 1 else ""


def whats_new_body(lang, data, files, intro=None, strings=None):
    """The What's new page: latest meetings, what came back, what was postponed or dated, what to watch."""
    ui, e = UI[lang], html.escape
    shown_tr = (strings or {}).get("texts", {}).get(lang, {}) if lang != "fr" else {}

    def fr(text):                      # a French title: translated when a checked translation exists, with the original kept
        t = shown_tr.get(string_key(text))
        return (f'<span lang="{lang}">{e(t)}</span> <span class="note">({e(ui["wn_original"])}: <span lang="fr">{e(text)}</span>)</span>'
                if t else f'<span lang="fr">{e(text)}</span>')

    def quote(text):                   # a French sentence, quoted exactly, with its translation first when there is one
        t = shown_tr.get(string_key(text))
        return (f'<span lang="{lang}">{e(t)}</span> <span class="note">{e(ui["wn_original"])}: <q lang="fr">{e(text)}</q></span>'
                if t else f'<q lang="fr">{e(text)}</q>')
    plink = lambda row: f'<a href="{e(row["page_url"])}">{e(ui["page_abbr"])} {row["page"]}</a>'
    parts = [f'<h1>{e(ui["wn_title"])}</h1>', disclosure.html("rules", lang), f'<p>{e(ui["wn_intro"])}</p>',
             f'<p><a href="feed.xml">{e(ui["wn_feed"])}</a></p>']
    texts = (intro or {}).get("texts") or {}
    shown = texts.get(lang) or texts.get("fr")
    if shown:
        shown_lang = lang if texts.get(lang) else "fr"
        kind = "summary_translation" if shown_lang != "fr" else "summary"
        note = f'<p class="note">{e(ui["fallback"].format(want=LANG_IN[lang][lang], have=LANG_IN[lang]["fr"]))}</p>' if shown_lang != lang else ""
        parts.append(f'<section aria-labelledby="wn-short-h"><h2 id="wn-short-h">{e(ui["wn_short"])}</h2>'
                     f'{disclosure.html(kind, lang, shown["model"])}{note}<p lang="{shown_lang}">{e(shown["text"])}</p></section>')
    if shown_tr and ui["wn_tr_note"]:
        parts.append(disclosure.html("translation", lang, strings.get("model")) + f'<p class="note">{e(ui["wn_tr_note"])}</p>')
    parts.append(f'<h2>{e(ui["wn_latest"])}</h2>')
    for m in data["recent_meetings"]:
        links = " · ".join(f'<a href="../meetings/{e(href)}">{e(label)}</a>' for label, href in meeting_links(lang, m["folder"], files.get(m["folder"], set())))
        rows = "".join(
            f'<li>{fr(d["title"])} ({e(ui["wn_vote"].get(d["vote"], ui["wn_novote"]))}; {plink(d)})</li>' for d in m["decisions"])
        sales = f'<p class="note">{e(ui["wn_sales"].format(n=m["sale_notices"]))}</p>' if m["sale_notices"] else ""
        parts.append(f'<h3>{e(human_date(lang, m["date"]))}</h3><p>{e(ui["wn_decisions"].format(n=len(m["decisions"])))}. {links}</p>'
                     f'<ul>{rows}</ul>{sales}')
    parts.append(f'<h2>{e(ui["wn_back"])}</h2>')
    if data["coming_back"]:
        parts.append("<ul>" + "".join(
            f'<li>{fr(t["title"])}: {e(ui["wn_back_row"].format(n=t["n_meetings"], first=human_date(lang, t["meetings"][0]), last=human_date(lang, t["last"])))}</li>'
            for t in data["coming_back"]) + f'</ul><p><a href="../topics/index.html">{e(ui["wn_more"])}</a></p>')
    else:
        parts.append(f'<p>{e(ui["wn_none"])}</p>')
    parts.append(f'<h2>{e(ui["wn_pending"])}</h2><p class="note">{e(ui["wn_pending_note"])}</p>')
    parts.append(("<ul>" + "".join(
        f'<li><strong>{e(human_date(lang, x["date"]))}</strong>, {e(ui["wn_" + ("postponed" if x["type"] == "deferred" else "planned")])}: '
        f'{fr(x["title"])}. {quote(x["sentence"])} ({plink(x)})</li>' for x in data["pending"]) + "</ul>")
        if data["pending"] else f'<p>{e(ui["wn_none"])}</p>')
    parts.append(f'<h2>{e(ui["wn_dates"])}</h2><p class="note">{e(ui["wn_dates_note"])}</p>')
    parts.append(("<ul>" + "".join(
        f'<li><strong>{e(human_date(lang, x["mentioned"]))}</strong>: {quote(x["sentence"])} '
        f'({e(human_date(lang, x["meeting"]))}, {plink(x)})</li>' for x in data["dates_mentioned"]) + "</ul>")
        if data["dates_mentioned"] else f'<p>{e(ui["wn_none"])}</p>')
    parts.append(f'<h2>{e(ui["wn_dropped"])}</h2><p class="note">{e(ui["wn_dropped_note"])}</p>')
    parts.append(("<ul>" + "".join(
        f'<li>{fr(x["title"])}: {e(ui["wn_dropped_row"].format(last=human_date(lang, x["last"]), n=x["later_meetings"]))}</li>'
        for x in data["possibly_dropped"]) + "</ul>") if data["possibly_dropped"] else f'<p>{e(ui["wn_none"])}</p>')
    parts.append(f'<h2>{e(ui["wn_watch"])}</h2><p class="note">{e(ui["wn_watch_note"])}</p><ul>' + "".join(
        f'<li><strong>{e(ui["topics"][w["topic"]])}</strong>: {e(ui["why"][w["topic"]])} '
        f'<span class="note">{e(ui["wn_watch_row"].format(items=w["items_last_year"], meetings=w["meetings_last_year"], last=human_date(lang, w["last"])))}</span></li>'
        for w in data["watch"] if w["topic"] in ui["topics"]) + "</ul>")
    return "\n".join(parts)


def whats_new_feed(lang, data, files):
    """Atom feed, one entry per recent meeting. Dates come from the minutes, so a rebuild changes nothing."""
    e = html.escape
    ui, base = UI[lang], SITE_URL
    entries = []
    for m in data.get("feed_meetings", []):
        page = "summary" if "summary" in files.get(m["folder"], set()) else "minutes"
        link = f"{base}{lang}/meetings/{m['folder']}/{page}.html" if m["folder"] else f"{base}{lang}/meetings/index.html"
        title = ui["wn_feed_entry"].format(date=human_date(lang, m["date"]), n=m["decisions"])
        entries.append(f"<entry><id>tag:mgifford.github.io,2026:echo-montolieu:{lang}:{m['date']}</id><title>{e(title)}</title>"
                       f'<link href="{e(link)}"/><updated>{m["date"]}T00:00:00Z</updated></entry>')
    updated = (data.get("latest") or "1970-01-01") + "T00:00:00Z"
    return ('<?xml version="1.0" encoding="utf-8"?>\n<feed xmlns="http://www.w3.org/2005/Atom" xml:lang="' + lang + '">'
            f"<id>tag:mgifford.github.io,2026:echo-montolieu:{lang}:whats-new</id><title>{e(SITE_NAME)}: {e(ui['wn_title'])}</title>"
            f'<link rel="self" href="{base}{lang}/whats-new/feed.xml"/><link href="{base}{lang}/whats-new/index.html"/>'
            f"<updated>{updated}</updated>" + "".join(entries) + "</feed>\n")


def landing_body(lang, index, pointers, folders, files, has_zoning=False, has_whats_new=False, has_data=False, has_resources=False):
    """Home page: alerts, introduction, explore links, the minutes grouped by year, where to find things."""
    ui, e = UI[lang], html.escape
    since = recent_since(index)
    by_year = meetings_list(lang, index, folders, files, since=since)
    all_by_year = meetings_list(lang, index, folders, files)
    if by_year:
        years = sorted((y for y in by_year if y != "undated"), reverse=True)
        n = sum(len(v) for v in by_year.values())
        old = sorted((d.get("meeting_date") or {}).get("value", "")[:4] for d in index.get("documents", [])
                     if (d.get("meeting_date") or {}).get("value") and (d["meeting_date"]["value"] < since))
        minutes = (f'<p>{e(ui["home_recent"].format(n=n, sets=_word(lang, "sets", n), first=old[0], last=old[-1])) if old else ""} '
                   f'<a href="meetings/index.html">{e(ui["all_minutes"])}</a></p>')
        for y in years:
            k = len(by_year[y])
            minutes += f'<h3 id="minutes-{y}">{e(ui["year_h"].format(year=y, n=k, sets=_word(lang, "sets", k)))}</h3><ul>{"".join(by_year[y])}</ul>'
        minutes += f'<p><a href="meetings/index.html">{e(ui["all_minutes_long"])}</a></p>'
    elif all_by_year:
        minutes = f'<p><a href="meetings/index.html">{e(ui["all_minutes"])}</a></p>'
    else:
        minutes = f'<p>{e(ui["none_yet"])}</p>'
    where = []
    for p in pointers.get("entries", []):
        url = p.get("url")
        if isinstance(url, str) and url.startswith("https://"):
            label, label_lang = (p["label_fr"], "fr") if lang == "fr" else (p["label_en"], "en")
            where.append(f'<li><a href="{e(url)}" lang="{label_lang}">{e(label)}</a> '
                         f'<span class="note">{e(ui["where_note"].format(owner=p.get("owner") or ui["owner_default"]))}</span></li>')
    pocket = f'<a href="{PANNEAUPOCKET_URL}">PanneauPocket Montolieu</a>'
    data = ui["data"].format(a='<a href="../index.json">index.json</a>', b='<a href="../where_to_find_mairie.json">where_to_find_mairie.json</a>')
    return f"""<h1>{SITE_NAME}</h1>
<section class="alerts" aria-labelledby="alerts-heading"><h2 id="alerts-heading">{e(ui['alerts_h'])}</h2>
<p>{e(ui['alerts_p']).replace('{link}', pocket)}</p></section>
{disclosure.html('site', lang)}
<p>{e(ui['intro'])}</p>
<h2>{e(ui['explore'])}</h2>
<ul>
{f'<li><a href="whats-new/index.html">{e(ui["whatsnew"])}</a>: {e(ui["e_whatsnew"])}</li>' if has_whats_new else ''}
<li><a href="meetings/index.html">{e(ui['meetings'])}</a>: {e(ui['e_meetings'])}</li>
<li><a href="topics/index.html">{e(ui['issues'])}</a>: {e(ui['e_issues'])}</li>
<li><a href="finance/index.html">{e(ui['finance'])}</a>, {e(ui['e_finance'])}</li>
<li><a href="places/index.html">{e(ui['e_places'])}</a></li>
{f'<li><a href="resources/index.html">{e(ui["e_resources"])}</a></li>' if has_resources else ''}
{f'<li><a href="data/index.html">{e(ui["data_title"])}</a>: {e(ui["e_data"].split(": ", 1)[-1])}</li>' if has_data else ''}
{f'<li><a href="zoning/index.html">{e(ui["e_zoning"])}</a></li>' if has_zoning else ''}
<li><a href="places/map.html">{e(ui['e_map'])}</a></li>
</ul>
<h2 id="minutes">{e(ui['minutes_h'])}</h2>
{minutes}
<h2>{e(ui['where_h'])}</h2>
<ul>{''.join(where)}</ul>
<p class="note">{data}</p>"""


def chooser():
    e = html.escape
    links = "".join(f'<li><a href="{c}/" lang="{c}" hreflang="{c}" data-setlang="{c}">{NAMES[c]}</a></li>' for c in LANGS)
    hint = " / ".join(f'<span lang="{c}">{e(UI[c]["chooser_p"])}</span>' for c in LANGS)
    return f"""<!doctype html>
<html lang="en" data-chooser>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="{CSP}">
<title>{SITE_NAME}</title>
<link rel="stylesheet" href="assets/site.css">
<script src="assets/site.js" defer></script>
</head>
<body class="chooser">
<main id="main">
<h1>{SITE_NAME}</h1>
<p>{hint}</p>
<ul class="choose">{links}</ul>
{disclosure.html('site', 'en')}
</main>
</body>
</html>
"""


def folders_by_document(public):
    out = {}
    for p in (Path(public) / "meetings").glob("*/minutes.md"):
        meta, _ = split_front(p.read_text(encoding="utf-8"))
        if meta.get("document_id"):
            out[meta["document_id"]] = p.parent.name
    return out


CSS = """\
:root{--bg:#FBF9F5;--fg:#1A1A1A;--brand:#004B87;--tint:#EBF3FA;--grey:#F1EFEA;--rule:#6b6b6b;color-scheme:light}
*{box-sizing:border-box}
body{margin:0;font:1rem/1.6 system-ui,-apple-system,sans-serif;background:var(--bg);color:var(--fg)}
a{color:var(--brand)}
a:focus-visible,[tabindex]:focus-visible{outline:3px solid #005A9C;outline-offset:2px}
.skip{position:absolute;left:-999px;top:0;background:#fff;color:#000;padding:.75rem 1rem;z-index:10}
.skip:focus{left:0}
header{background:var(--brand);color:#fff;padding:.75rem 1rem}
header a{color:#fff}
header a:focus-visible{outline-color:#fff}
.brand{margin:0 0 .25rem;font-size:1.4rem;font-weight:700}
.brand a{text-decoration:none}
header ul{list-style:none;margin:0;padding:0;display:flex;flex-wrap:wrap;gap:.25rem .5rem}
header li{margin:0}
header nav a{display:inline-flex;align-items:center;min-height:44px;min-width:44px;padding:0 .6rem;text-decoration:underline}
header a[aria-current]{font-weight:700;text-decoration-thickness:3px}
.langs{margin-top:.25rem;border-top:1px solid rgba(255,255,255,.5)}
main{max-width:56rem;margin:0 auto;padding:1rem;overflow-wrap:anywhere}
main:focus{outline:none}
footer{max-width:56rem;margin:0 auto;padding:1rem;overflow-wrap:anywhere}
li{margin:.5rem 0}
.note{font-size:.95rem}
.sr{position:absolute;width:1px;height:1px;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap}
.alerts{background:var(--tint);border-left:6px solid var(--brand);padding:.5rem 1rem;margin:1rem 0}
.alerts h2{margin:.25rem 0;font-size:1.1rem}
.ai,blockquote{border-left:6px solid var(--rule);background:var(--grey);padding:.25rem 1rem;margin:1rem 0}
blockquote p{margin:.5rem 0}
.notice{border:2px solid var(--brand);background:var(--tint);padding:.5rem 1rem;margin:1rem 0}
.tablewrap{overflow-x:auto;margin:1rem 0}
table{border-collapse:collapse;min-width:100%}
th,td{border:1px solid var(--rule);padding:.4rem .6rem;text-align:left;vertical-align:top}
th{background:var(--grey)}
code{background:var(--grey);padding:0 .2rem;overflow-wrap:anywhere}
pre{white-space:pre-wrap;overflow-wrap:anywhere;background:var(--grey);padding:.5rem}
h1{font-size:1.7rem;line-height:1.25}
.mnav ul{list-style:none;margin:0;padding:0;display:flex;flex-wrap:wrap;gap:.25rem .5rem}
.mnav a{display:inline-flex;align-items:center;min-height:44px;padding:0 .75rem;border:2px solid var(--brand);border-radius:4px;background:var(--tint)}
.mnav a[aria-current]{background:var(--brand);color:#fff;font-weight:700}
.choose{list-style:none;padding:0}
.choose a{display:inline-block;min-height:44px;padding:.5rem 1rem;font-size:1.2rem}
@media (prefers-reduced-motion:reduce){*{scroll-behavior:auto!important}}
"""
JS = f"""(function () {{
  var L = ['fr', 'en', 'nl'], KEY = '{KEY}';
  function stored() {{ try {{ var v = localStorage.getItem(KEY); return L.indexOf(v) >= 0 ? v : null; }} catch (e) {{ return null; }} }}
  function browser() {{
    var l = navigator.languages && navigator.languages.length ? navigator.languages : [navigator.language || ''];
    for (var i = 0; i < l.length; i++) {{ var p = String(l[i]).toLowerCase().split('-')[0]; if (L.indexOf(p) >= 0) return p; }}
    return 'en';
  }}
  if (document.documentElement.hasAttribute('data-chooser')) {{ location.replace((stored() || browser()) + '/'); return; }}
  document.addEventListener('click', function (ev) {{
    var a = ev.target.closest && ev.target.closest('a[data-setlang]');
    if (a) {{ try {{ localStorage.setItem(KEY, a.getAttribute('data-setlang')); }} catch (e) {{}} }}
  }});
}})();
"""


def build(out_dir, public="public", data="data"):
    out, public, data = Path(out_dir), Path(public), Path(data)
    if out.exists():
        shutil.rmtree(out)
    (out / "assets").mkdir(parents=True)
    (out / "assets" / "site.css").write_text(CSS, encoding="utf-8")
    (out / "assets" / "site.js").write_text(JS, encoding="utf-8")
    index = _read_json(public / "index.json", {"count": 0, "documents": []})
    has_budget = (public / "finance" / "budget.md").exists()       # the menu item appears only when the page does
    pointers = _read_json(data / "where_to_find_mairie.json", {"entries": []})
    # data files and the map, as before
    if (public / "index.json").exists():
        shutil.copyfile(public / "index.json", out / "index.json")
    if (public / "minutes").exists():
        shutil.copytree(public / "minutes", out / "minutes")
    if (public / "places" / "places.json").exists():
        (out / "places").mkdir(exist_ok=True)
        shutil.copyfile(public / "places" / "places.json", out / "places" / "places.json")
    for lang, name in (("en", "map.html"), ("fr", "map.fr.html"), ("nl", "map.nl.html")):
        source = public / "places" / name
        if not source.exists() and lang != "en":
            source = public / "places" / "map.html"                     # not generated yet: the English map
        if source.exists():
            text = source.read_text(encoding="utf-8")
            (out / lang / "places").mkdir(parents=True, exist_ok=True)
            (out / lang / "places" / "map.html").write_text(map_with_site_navigation(text, lang, has_budget) if "<body>" in text else text, encoding="utf-8")
    if (public / "places" / "map.html").exists():
        (out / "places").mkdir(exist_ok=True)
        (out / "places" / "map.html").write_text(map_redirect_page(), encoding="utf-8")
    opendata = {}
    if (public / "data" / "council.json").exists():
        shutil.copytree(public / "data", out / "data")
        opendata = _read_json(out / "data" / "council.json", {})
    if (data / "where_to_find_mairie.json").exists():
        shutil.copyfile(data / "where_to_find_mairie.json", out / "where_to_find_mairie.json")
    (out / "index.html").write_text(chooser(), encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")

    folders = folders_by_document(public)
    place_map = place_links(public)
    whats = _read_json(public / "whats-new" / "whats-new.json", None)
    for lang in LANGS:
        pages = [Page(lang, "index.html", SITE_NAME, landing_body(lang, index, pointers, folders, meeting_files(public), (public / 'zoning' / 'index.md').exists(), (public / 'whats-new' / 'whats-new.json').exists(), (public / 'data' / 'council.json').exists(), (public / 'resources' / 'index.md').exists()))]
        if opendata:
            sizes = {f.name: f.stat().st_size for f in (out / "data").iterdir()}
            pages.append(Page(lang, "data/index.html", UI[lang]["data_title"], data_page_body(lang, opendata, sizes)))
        if whats and whats.get("latest"):
            pages.append(Page(lang, "whats-new/index.html", UI[lang]["wn_title"], whats_new_body(lang, whats, meeting_files(public), _read_json(public / "whats-new" / "intro.json", None), _read_json(public / "whats-new" / "translations.json", None))))
            feed = out / lang / "whats-new" / "feed.xml"
            feed.parent.mkdir(parents=True, exist_ok=True)
            feed.write_text(whats_new_feed(lang, whats, meeting_files(public)), encoding="utf-8")
        for base in page_bases(public):
            found = pick(public / base, lang)
            if not found:
                continue
            path, content_lang = found
            meta, text = split_front(path.read_text(encoding="utf-8"))
            text = _TRANSLATION_LINK.sub("", text)
            body = render_markdown(text, UI[lang]["table"], _up(base.count("/") + 1))
            parts = base.split("/")
            if base == "meetings/index":
                body, content_lang = meetings_index_body(lang, index, folders, meeting_files(public)), lang
            elif len(parts) == 3 and parts[0] == "meetings":
                body = meeting_nav(lang, parts[1], parts[2], meeting_files(public)) + body
                if parts[2] == "minutes":
                    body = _insert_after_h1(body, places_section(lang, place_map.get(parts[1])))
            pages.append(Page(lang, base + ".html", first_heading(text, base), body, content_lang))
        if index.get("documents") and not any(pg.rel == "meetings/index.html" for pg in pages):
            pages.append(Page(lang, "meetings/index.html", UI[lang]["meetings"], meetings_index_body(lang, index, folders, meeting_files(public)), lang))
        for page in pages:
            target = out / lang / page.rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(layout(page, LANGS, has_budget), encoding="utf-8")
    return out
