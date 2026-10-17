# Dockerfile
FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PIP_NO_CACHE_DIR=1

# No torch here: every model runs in models-serve. libglib: OpenCV (headless).
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-dev.txt requirements-ml.txt ./
RUN pip install -r requirements.txt -r requirements-ml.txt

COPY . .

# Uploaded models, uploads and run outputs live on the /data volume.
ENV WEIGHTS_DIR=/data/weights \
    MEDIA_DIR=/data/media
RUN mkdir -p /app/logs /data
VOLUME /data

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-keep-alive", "300"]
