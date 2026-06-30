#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8765}"
BASE_URL="http://${HOST}:${PORT}"
LOG_FILE="$(mktemp /tmp/file-trans-smoke.XXXXXX.log)"
TMP_DIR="$(mktemp -d /tmp/file-trans-smoke.XXXXXX)"
SERVER_PID=""

cleanup() {
  if [[ -n "${SERVER_PID}" ]] && kill -0 "${SERVER_PID}" 2>/dev/null; then
    kill "${SERVER_PID}" 2>/dev/null || true
    wait "${SERVER_PID}" 2>/dev/null || true
  fi
  rm -rf "${TMP_DIR}" "${LOG_FILE}"
}
trap cleanup EXIT

cd "${ROOT_DIR}"
HOST="${HOST}" PORT="${PORT}" python3 server.py >"${LOG_FILE}" 2>&1 &
SERVER_PID="$!"

for _ in $(seq 1 50); do
  if curl -fsS "${BASE_URL}/api/capabilities" >/dev/null 2>&1; then
    break
  fi
  sleep 0.1
done

curl -fsS "${BASE_URL}/api/capabilities" | python3 -c '
import json
import sys

data = json.load(sys.stdin)
assert data["ok"] is True
assert isinstance(data["tools"]["ffmpeg"], bool)
assert data["inputFormatCount"] >= 40
assert data["maxUploadBytes"] > 0
assert data["maxConversionSeconds"] > 0
'

CSV_FILE="${TMP_DIR}/scores.csv"
printf 'name,score\nkim,10\nlee,20\n' >"${CSV_FILE}"
CONVERT_RESPONSE="$(
  curl -fsS \
    -F "file=@${CSV_FILE};filename=scores.csv" \
    -F "target=json" \
    "${BASE_URL}/convert"
)"
DOWNLOAD_URL="$(printf '%s' "${CONVERT_RESPONSE}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["downloadUrl"])')"
printf '%s' "${DOWNLOAD_URL}" | grep -Eq '^/download/[0-9a-f]{32}/[A-Za-z0-9_-]{32,96}/scores\.json$'
BAD_DOWNLOAD_URL="$(printf '%s' "${DOWNLOAD_URL}" | sed -E 's#/download/([0-9a-f]{32})/[^/]+/#/download/\\1/not-a-valid-token/#')"
BAD_DOWNLOAD_STATUS="$(curl -sS -o "${TMP_DIR}/bad-download.txt" -w '%{http_code}' "${BASE_URL}${BAD_DOWNLOAD_URL}")"
[[ "${BAD_DOWNLOAD_STATUS}" == "404" ]]
curl -fsS "${BASE_URL}${DOWNLOAD_URL}" -o "${TMP_DIR}/scores.json"
grep -q '"name": "kim"' "${TMP_DIR}/scores.json"

TSV_FILE="${TMP_DIR}/scores.tsv"
printf 'name\tscore\nkim\t10\nlee\t20\n' >"${TSV_FILE}"
TSV_RESPONSE="$(
  curl -fsS \
    -F "file=@${TSV_FILE};filename=scores.tsv" \
    -F "target=json" \
    "${BASE_URL}/convert"
)"
TSV_URL="$(printf '%s' "${TSV_RESPONSE}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["downloadUrl"])')"
curl -fsS "${BASE_URL}${TSV_URL}" -o "${TMP_DIR}/scores-tsv.json"
grep -q '"score": "20"' "${TMP_DIR}/scores-tsv.json"

NDJSON_FILE="${TMP_DIR}/events.ndjson"
printf '{"name":"kim","score":10}\n{"name":"lee","score":20}\n' >"${NDJSON_FILE}"
NDJSON_RESPONSE="$(
  curl -fsS \
    -F "file=@${NDJSON_FILE};filename=events.ndjson" \
    -F "target=csv" \
    "${BASE_URL}/convert"
)"
NDJSON_URL="$(printf '%s' "${NDJSON_RESPONSE}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["downloadUrl"])')"
curl -fsS "${BASE_URL}${NDJSON_URL}" -o "${TMP_DIR}/events.csv"
grep -q 'lee,20' "${TMP_DIR}/events.csv"

SRT_FILE="${TMP_DIR}/caption.srt"
printf '1\n00:00:01,000 --> 00:00:02,000\nhello\n' >"${SRT_FILE}"
SRT_RESPONSE="$(
  curl -fsS \
    -F "file=@${SRT_FILE};filename=caption.srt" \
    -F "target=vtt" \
    "${BASE_URL}/convert"
)"
SRT_URL="$(printf '%s' "${SRT_RESPONSE}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["downloadUrl"])')"
curl -fsS "${BASE_URL}${SRT_URL}" -o "${TMP_DIR}/caption.vtt"
grep -q '^WEBVTT' "${TMP_DIR}/caption.vtt"
grep -q '00:00:01.000 --> 00:00:02.000' "${TMP_DIR}/caption.vtt"

BAD_FILE="${TMP_DIR}/bad.png"
printf 'not a png\n' >"${BAD_FILE}"
BAD_STATUS="$(
  curl -sS -o "${TMP_DIR}/bad-response.json" -w '%{http_code}' \
    -F "file=@${BAD_FILE};filename=bad.png" \
    -F "target=jpg" \
    "${BASE_URL}/convert"
)"
[[ "${BAD_STATUS}" == "400" ]]
grep -q '파일 내용이 확장자와 일치하지 않거나 지원하지 않는 형식입니다' "${TMP_DIR}/bad-response.json"

EXE_FILE="${TMP_DIR}/tool.exe"
printf 'MZ fake\n' >"${EXE_FILE}"
EXE_STATUS="$(
  curl -sS -o "${TMP_DIR}/exe-response.json" -w '%{http_code}' \
    -F "file=@${EXE_FILE};filename=tool.exe" \
    -F "target=zip" \
    "${BASE_URL}/convert"
)"
[[ "${EXE_STATUS}" == "400" ]]
grep -q '.exe 파일은 업로드 허용 목록에 없습니다' "${TMP_DIR}/exe-response.json"

if find data/uploads -mindepth 1 -maxdepth 2 -print -quit | grep -q .; then
  echo "data/uploads is not empty" >&2
  exit 1
fi

echo "smoke test passed"
