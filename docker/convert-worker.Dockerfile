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
      pandoc \
      poppler-utils \
      python3 \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /input /work /tmp /var/tmp \
    && chmod 1777 /tmp /var/tmp \
    && chmod 755 /input /work

WORKDIR /work
