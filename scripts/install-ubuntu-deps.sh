#!/usr/bin/env bash
set -euo pipefail

sudo apt-get update
sudo apt-get install -y \
  python3 \
  ffmpeg \
  libreoffice \
  libreoffice-h2orestart \
  imagemagick \
  ghostscript \
  poppler-utils \
  pandoc \
  calibre \
  fonts-nanum
