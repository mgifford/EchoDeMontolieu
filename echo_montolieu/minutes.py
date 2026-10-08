"""Find council-minutes PDFs on the Mairie's index page."""
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

INDEX_URL = "https://www.montolieu.fr/mairie/comptes-rendus-cm/"


def parse_minutes_index(html, base_url=INDEX_URL):
    """Unique PDF links in page order.

    The meeting date is deliberately not taken from the filename: names are
    inconsistent (CRCM-24062025, CM-18-SEPTEMBRE with no year, ...) and the
    /uploads/YYYY/MM/ folder is the upload month, not the meeting date.
    """
    soup = BeautifulSoup(html, "lxml")
    seen, items = set(), []
    for a in soup.find_all("a", href=True):
        url = urljoin(base_url, a["href"])
        if urlparse(url).path.lower().endswith(".pdf") and url not in seen:
            seen.add(url)
            name = urlparse(url).path.rsplit("/", 1)[-1]
            items.append({
                "url": url,
                "filename": name,
                "link_text": a.get_text(" ", strip=True) or None,
                # Guess only; confirm against the document text.
                "draft_suspected": name.lower().startswith("projet"),
            })
    return items
