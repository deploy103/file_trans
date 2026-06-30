#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOST="${HOST:-127.0.0.1}"
if [[ -z "${PORT:-}" ]]; then
  PORT="$(
    python3 - <<'PY'
import os
import socket

host = os.environ.get("HOST", "127.0.0.1")
with socket.socket() as sock:
    sock.bind((host, 0))
    print(sock.getsockname()[1])
PY
  )"
fi
BASE_URL="http://${HOST}:${PORT}"
LOG_FILE="$(mktemp /tmp/file-trans-smoke.XXXXXX.log)"
TMP_DIR="$(mktemp -d /tmp/file-trans-smoke.XXXXXX)"
SMOKE_DATA_DIR="${TMP_DIR}/data"
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
FILE_TRANS_DATA_DIR="${SMOKE_DATA_DIR}" HOST="${HOST}" PORT="${PORT}" python3 server.py >"${LOG_FILE}" 2>&1 &
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
assert "helpers" not in data
assert not ({"g++", "java", "rust", "csharp"} & set(data["tools"]))
assert isinstance(data["malwareScanEnabled"], bool)
assert isinstance(data["malwareScanAvailable"], bool)
assert data["inputFormatCount"] >= 40
assert data["maxUploadBytes"] > 0
assert data["maxConversionSeconds"] > 0
assert data["maxReferenceScanBytes"] > 0
'

curl -fsS -D "${TMP_DIR}/headers.txt" "${BASE_URL}/" -o "${TMP_DIR}/index.html"
grep -qi '^Server: FileTrans/' "${TMP_DIR}/headers.txt"
grep -qi '^X-Content-Type-Options: nosniff' "${TMP_DIR}/headers.txt"
grep -qi '^X-Frame-Options: DENY' "${TMP_DIR}/headers.txt"
grep -qi '^Referrer-Policy: no-referrer' "${TMP_DIR}/headers.txt"
grep -qi '^Permissions-Policy:' "${TMP_DIR}/headers.txt"
grep -qi '^Cross-Origin-Resource-Policy: same-origin' "${TMP_DIR}/headers.txt"
grep -qi '^X-Permitted-Cross-Domain-Policies: none' "${TMP_DIR}/headers.txt"
grep -qi '^Content-Security-Policy:' "${TMP_DIR}/headers.txt"
if grep -qi '^Server: .*Python' "${TMP_DIR}/headers.txt"; then
  echo "Server header leaks Python version" >&2
  exit 1
fi
TRACE_STATUS="$(curl -sS -o "${TMP_DIR}/trace.txt" -w '%{http_code}' -X TRACE "${BASE_URL}/")"
[[ "${TRACE_STATUS}" == "405" ]]
PUT_STATUS="$(curl -sS -o "${TMP_DIR}/put.txt" -w '%{http_code}' -X PUT "${BASE_URL}/")"
[[ "${PUT_STATUS}" == "405" ]]
HEAD_STATUS="$(curl -fsS -o /dev/null -w '%{http_code}' -I "${BASE_URL}/api/capabilities")"
[[ "${HEAD_STATUS}" == "200" ]]
TRAVERSAL_STATUS="$(curl -sS -o "${TMP_DIR}/traversal.txt" -w '%{http_code}' "${BASE_URL}/%2e%2e/server.py")"
[[ "${TRAVERSAL_STATUS}" == "403" ]]

PREFLIGHT_STATUS="$(
  curl -sS -D "${TMP_DIR}/preflight-headers.txt" -o "${TMP_DIR}/preflight.txt" -w '%{http_code}' \
    -X OPTIONS \
    -H "Origin: ${BASE_URL}" \
    -H 'Access-Control-Request-Method: POST' \
    -H 'Access-Control-Request-Headers: Content-Type' \
    "${BASE_URL}/convert"
)"
[[ "${PREFLIGHT_STATUS}" == "204" ]]
grep -qi "^Access-Control-Allow-Origin: ${BASE_URL}" "${TMP_DIR}/preflight-headers.txt"
BAD_PREFLIGHT_STATUS="$(
  curl -sS -o "${TMP_DIR}/bad-preflight.txt" -w '%{http_code}' \
    -X OPTIONS \
    -H 'Origin: https://example.test' \
    -H 'Access-Control-Request-Method: POST' \
    "${BASE_URL}/convert"
)"
[[ "${BAD_PREFLIGHT_STATUS}" == "403" ]]

CSRF_FILE="${TMP_DIR}/csrf.txt"
printf 'cross-site request\n' >"${CSRF_FILE}"
CSRF_STATUS="$(
  curl -sS -o "${TMP_DIR}/csrf-response.json" -w '%{http_code}' \
    -H 'Origin: https://example.test' \
    -F "file=@${CSRF_FILE};filename=csrf.txt" \
    -F "target=html" \
    "${BASE_URL}/convert"
)"
[[ "${CSRF_STATUS}" == "403" ]]
grep -q '허용되지 않은 요청 출처입니다' "${TMP_DIR}/csrf-response.json"

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
WRONG_NAME_URL="$(printf '%s' "${DOWNLOAD_URL}" | sed -E 's#/[^/]+$#/wrong-name.json#')"
WRONG_NAME_STATUS="$(curl -sS -o "${TMP_DIR}/wrong-name.txt" -w '%{http_code}' "${BASE_URL}${WRONG_NAME_URL}")"
[[ "${WRONG_NAME_STATUS}" == "404" ]]
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

REMOTE_MD_FILE="${TMP_DIR}/remote.md"
printf '![x](http://169.254.169.254/latest/meta-data/)\n' >"${REMOTE_MD_FILE}"
REMOTE_MD_STATUS="$(
  curl -sS -o "${TMP_DIR}/remote-md-response.json" -w '%{http_code}' \
    -F "file=@${REMOTE_MD_FILE};filename=remote.md" \
    -F "target=html" \
    "${BASE_URL}/convert"
)"
[[ "${REMOTE_MD_STATUS}" == "400" ]]
grep -q '외부 리소스를 참조하는 마크업 파일은 변환할 수 없습니다' "${TMP_DIR}/remote-md-response.json"

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

if find "${SMOKE_DATA_DIR}/uploads" -mindepth 1 -maxdepth 2 -print -quit | grep -q .; then
  echo "smoke upload staging directory is not empty" >&2
  exit 1
fi

echo "smoke test passed"
