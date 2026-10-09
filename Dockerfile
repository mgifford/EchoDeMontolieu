FROM python:3.12-slim

# Hugging Face Spaces run containers as user 1000; match that so file ownership works.
RUN useradd -m -u 1000 user
USER user
ENV PATH="/home/user/.local/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PORT=7860
WORKDIR /home/user/app

COPY --chown=user requirements-space.txt .
RUN pip install --no-cache-dir -r requirements-space.txt

# Only published data goes into the image. private/ and .cache/ never do.
COPY --chown=user app.py .
# The modules that build and query the database use only the standard library; the OCR and fetch
# modules in the same folder are shipped but never imported here.
COPY --chown=user echo_montolieu ./echo_montolieu
COPY --chown=user schema.sql .
COPY --chown=user public ./public
COPY --chown=user data/where_to_find_mairie.json ./data/where_to_find_mairie.json
# The searchable database is derived from public/ at build time and not stored in git.
RUN python -c "from echo_montolieu import db; print(db.build_public('public', 'data/echo.db'))"

EXPOSE 7860
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT}"]
