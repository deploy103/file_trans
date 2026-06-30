#!/usr/bin/env bash
set -euo pipefail

sudo apt-get update
sudo apt-get install -y \
  python3 \
  ffmpeg \
  libreoffice \
  imagemagick \
  ghostscript \
  poppler-utils \
  pandoc \
  calibre \
  fonts-nanum
