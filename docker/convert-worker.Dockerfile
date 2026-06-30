FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    HOME=/tmp \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

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
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system --gid 10001 filetrans \
    && useradd --system --uid 10001 --gid filetrans --home-dir /tmp --shell /usr/sbin/nologin filetrans \
    && mkdir -p /input /work /tmp /var/tmp \
    && chmod 1777 /tmp /var/tmp \
    && chmod 755 /input \
    && chmod 1777 /work

WORKDIR /work
USER 10001:10001
