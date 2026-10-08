#!/usr/bin/env bash
# One-off check that a Hugging Face Job can run this project's pipeline.
# This runs INSIDE the job container. It makes two requests to montolieu.fr
# (robots.txt and the minutes index page) and downloads no PDFs.
set -euo pipefail

echo "== who am I"
id

echo "== install system packages (needs root)"
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends \
    tesseract-ocr tesseract-ocr-fra git ca-certificates
tesseract --version | head -1
tesseract --list-langs

echo "== get the code (branch: ${REPO_REF:-main})"
mkdir -p /work
git clone --depth 1 --branch "${REPO_REF:-main}" https://github.com/mgifford/EchoDeMontolieu.git /work/repo
cd /work/repo
git log --oneline -1

echo "== install python dependencies"
pip install -q -r requirements.txt

echo "== run the test suite"
python -m pytest -q -p no:cacheprovider

echo "== dry-run sync (two requests to montolieu.fr, no PDFs)"
python -m echo_montolieu sync --dry-run --cache /work/cache --private /work/private

echo "== write test: can the job write to a mounted Storage Bucket?"
if [ -d /mnt/spike ]; then
    date -u > /mnt/spike/last_run.txt
    cat /mnt/spike/last_run.txt
else
    echo "no bucket mounted at /mnt/spike (skipped)"
fi

echo "== done"
