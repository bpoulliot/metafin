FROM python:3.12-slim

RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY VERSION .
COPY app/ ./app/

RUN useradd --uid 1000 --no-create-home --shell /sbin/nologin xenotag \
    && chown -R xenotag /app
USER xenotag

EXPOSE 7755

ENV PYTHONUNBUFFERED=1
ENV CONFIG_PATH=/config/config.yml

ARG BUILD_VERSION=dev
LABEL org.opencontainers.image.title="Xenotag" \
      org.opencontainers.image.description="Jellyfin media tagger and poster badge overlay service" \
      org.opencontainers.image.source="https://github.com/bpoulliot/xenotag" \
      org.opencontainers.image.version="${BUILD_VERSION}" \
      org.opencontainers.image.licenses="MIT"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7755"]
