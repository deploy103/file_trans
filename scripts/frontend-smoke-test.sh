#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"
if [[ -z "${FRONTEND_PORT:-}" ]]; then
  FRONTEND_PORT="$(
    python3 - <<'PY'
import os
import socket

host = os.environ.get("FRONTEND_HOST", "127.0.0.1")
with socket.socket() as sock:
    sock.bind((host, 0))
    print(sock.getsockname()[1])
PY
  )"
fi
BASE_URL="http://${FRONTEND_HOST}:${FRONTEND_PORT}"
LOG_FILE="$(mktemp /tmp/file-trans-frontend-smoke.XXXXXX.log)"
TMP_DIR="$(mktemp -d /tmp/file-trans-frontend-smoke.XXXXXX)"
SERVER_PID=""
ESCAPE_LINK=""
LISTING_DIR=""

cleanup() {
  if [[ -n "${SERVER_PID}" ]] && kill -0 "${SERVER_PID}" 2>/dev/null; then
    kill "${SERVER_PID}" 2>/dev/null || true
    wait "${SERVER_PID}" 2>/dev/null || true
  fi
  if [[ -n "${ESCAPE_LINK}" ]]; then
    rm -f "${ESCAPE_LINK}"
  fi
  if [[ -n "${LISTING_DIR}" ]]; then
    rm -rf "${LISTING_DIR}"
  fi
  rm -rf "${TMP_DIR}" "${LOG_FILE}"
}
trap cleanup EXIT

cd "${ROOT_DIR}"
FRONTEND_HOST="${FRONTEND_HOST}" FRONTEND_PORT="${FRONTEND_PORT}" python3 scripts/frontend-server.py >"${LOG_FILE}" 2>&1 &
SERVER_PID="$!"

for _ in $(seq 1 50); do
  if curl -fsS "${BASE_URL}/favicon.svg" >/dev/null 2>&1; then
    break
  fi
  sleep 0.1
done

curl -fsS -D "${TMP_DIR}/route-headers.txt" "${BASE_URL}/csvtojson/tran" -o "${TMP_DIR}/route.html"
grep -q '<title>File Trans</title>' "${TMP_DIR}/route.html"
grep -q '<script src="/app.js" defer></script>' "${TMP_DIR}/route.html"
grep -qi '^Server: FileTransFrontend' "${TMP_DIR}/route-headers.txt"
grep -qi '^Cache-Control: no-store' "${TMP_DIR}/route-headers.txt"
grep -qi '^X-Content-Type-Options: nosniff' "${TMP_DIR}/route-headers.txt"
grep -qi '^X-Frame-Options: DENY' "${TMP_DIR}/route-headers.txt"
grep -qi '^Referrer-Policy: no-referrer' "${TMP_DIR}/route-headers.txt"
grep -qi '^Permissions-Policy:' "${TMP_DIR}/route-headers.txt"
grep -qi '^Cross-Origin-Resource-Policy: same-origin' "${TMP_DIR}/route-headers.txt"
if grep -qi '^Server: .*Python' "${TMP_DIR}/route-headers.txt"; then
  echo "frontend Server header leaks Python version" >&2
  exit 1
fi

curl -fsS -D "${TMP_DIR}/favicon-headers.txt" "${BASE_URL}/favicon.svg" -o "${TMP_DIR}/favicon.svg"
grep -qi '^Content-type: image/svg+xml' "${TMP_DIR}/favicon-headers.txt"
grep -q '<svg' "${TMP_DIR}/favicon.svg"

STATIC_MISS_STATUS="$(curl -sS -o "${TMP_DIR}/miss.txt" -w '%{http_code}' "${BASE_URL}/missing.js")"
[[ "${STATIC_MISS_STATUS}" == "404" ]]
OPTIONS_STATUS="$(curl -sS -o "${TMP_DIR}/options.txt" -w '%{http_code}' -X OPTIONS "${BASE_URL}/")"
[[ "${OPTIONS_STATUS}" == "204" ]]
TRACE_STATUS="$(curl -sS -o "${TMP_DIR}/trace.txt" -w '%{http_code}' -X TRACE "${BASE_URL}/")"
[[ "${TRACE_STATUS}" == "405" ]]
POST_STATUS="$(curl -sS -o "${TMP_DIR}/post.txt" -w '%{http_code}' -X POST "${BASE_URL}/")"
[[ "${POST_STATUS}" == "405" ]]

ESCAPE_LINK="${ROOT_DIR}/public/.frontend-smoke-escape"
if ln -s "${ROOT_DIR}/server.py" "${ESCAPE_LINK}" 2>/dev/null; then
  ESCAPE_STATUS="$(curl -sS -o "${TMP_DIR}/escape.txt" -w '%{http_code}' "${BASE_URL}/.frontend-smoke-escape")"
  [[ "${ESCAPE_STATUS}" == "403" ]]
fi

LISTING_DIR="${ROOT_DIR}/public/.frontend-smoke-dir"
mkdir -p "${LISTING_DIR}"
LISTING_STATUS="$(curl -sS -o "${TMP_DIR}/listing.txt" -w '%{http_code}' "${BASE_URL}/.frontend-smoke-dir/")"
[[ "${LISTING_STATUS}" == "403" ]]

echo "frontend smoke test passed"
