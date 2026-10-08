"""Build the static, trilingual site for GitHub Pages from the published data.

Copies only what is meant to be public: public/index.json, public/minutes/, the map and the pointer
list, and renders the Markdown pages in public/ as HTML in French, English and Dutch (see
echo_montolieu/site.py). It never copies public/redacted or anything from private/.
Usage: python build_site.py OUTPUT_DIR
"""
import sys

from echo_montolieu.site import build

if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python build_site.py OUTPUT_DIR")
    print(f"built {build(sys.argv[1])}")
