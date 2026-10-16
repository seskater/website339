# Free hosting on Hugging Face Spaces (Docker SDK) or any container host.
FROM python:3.12-slim

RUN useradd -m -u 1000 app
WORKDIR /app
COPY requirements.txt requirements-photo.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-photo.txt

COPY --chown=app . .
RUN chown app /app
ENV VINTED_FINDER_MODELS=/app/.models USAGE_FILE=/tmp/usage.json PORT=7860
USER app
# Bake the CLIP model into the image so the first search isn't slow.
RUN python -c "from vinted_finder import visual; visual.warm_up()"

EXPOSE 7860
CMD uvicorn vinted_finder.app:app --host 0.0.0.0 --port ${PORT}
