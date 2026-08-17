# syntax=docker/dockerfile:1.7

FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    HOST=0.0.0.0 \
    PORT=8000 \
    FILE_TRANS_DATA_DIR=/app/data

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
      ca-certificates \
      calibre \
      ffmpeg \
      fonts-nanum \
      ghostscript \
      imagemagick \
      libreoffice \
      libreoffice-h2orestart \
      pandoc \
      poppler-utils \
      python3 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 filetrans \
    && useradd --system --uid 10001 --gid filetrans --home-dir /app/data/runtime-home --shell /usr/sbin/nologin filetrans

WORKDIR /app
COPY --chown=10001:10001 server.py ./
COPY --chown=10001:10001 public ./public
COPY --chown=10001:10001 config ./config
RUN mkdir -p /app/data && chown -R 10001:10001 /app/data

USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/capabilities', timeout=3)" || exit 1
ENTRYPOINT ["python3", "server.py"]
