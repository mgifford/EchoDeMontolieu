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
COPY --chown=user public ./public
COPY --chown=user data/where_to_find_mairie.json ./data/where_to_find_mairie.json

EXPOSE 7860
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT}"]
