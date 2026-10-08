"""Build the static site for GitHub Pages from the published data.

Copies only what is meant to be public: public/index.json, public/minutes/ and the
pointer list, and renders a static landing page. It never copies public/redacted
or anything from private/. Usage: python build_site.py OUTPUT_DIR
"""
import shutil
import sys
from pathlib import Path

from app import _landing, _read_json


def build(out_dir, public="public", data="data"):
    out, public, data = Path(out_dir), Path(public), Path(data)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    index = _read_json(public / "index.json", {"count": 0, "documents": []})
    pointers = _read_json(data / "where_to_find_mairie.json", {"entries": []})
    if (public / "index.json").exists():
        shutil.copyfile(public / "index.json", out / "index.json")
    if (public / "minutes").exists():
        shutil.copytree(public / "minutes", out / "minutes")
    for name in ("map.html", "places.json"):  # the map and its data; the Markdown pages are read on GitHub
        if (public / "places" / name).exists():
            (out / "places").mkdir(exist_ok=True)
            shutil.copyfile(public / "places" / name, out / "places" / name)
    if (data / "where_to_find_mairie.json").exists():
        shutil.copyfile(data / "where_to_find_mairie.json", out / "where_to_find_mairie.json")
    (out / "index.html").write_text(_landing(index, pointers, static=True), encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")  # serve files as they are
    return out


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python build_site.py OUTPUT_DIR")
    print(f"built {build(sys.argv[1])}")
