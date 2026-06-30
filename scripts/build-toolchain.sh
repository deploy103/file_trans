#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="$ROOT_DIR/build/tools"

mkdir -p "$OUT_DIR/java"

g++ -std=c++17 -O2 -Wall -Wextra "$ROOT_DIR/tools/cpp/file_probe.cpp" -o "$OUT_DIR/fileprobe-cpp"
rustc -O "$ROOT_DIR/tools/rust/file_probe.rs" -o "$OUT_DIR/fileprobe-rust"
javac -encoding UTF-8 -d "$OUT_DIR/java" "$ROOT_DIR/tools/java/FileProbe.java"
mcs -optimize+ -out:"$OUT_DIR/fileprobe-cs.exe" "$ROOT_DIR/tools/csharp/FileProbe.cs"
