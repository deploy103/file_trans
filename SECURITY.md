# Security Notes

File Trans accepts untrusted files and passes them to complex parsers. Treat every upload as hostile.

## Current Controls

- Extension allowlist and content signature checks before conversion.
- External URL and `file:` references in HTML/markup/flat XML document inputs are rejected before conversion.
- DTD and ENTITY declarations in XML-like inputs are rejected before conversion.
- ZIP-based document checks for path traversal, member count, uncompressed size, and external references in metadata.
- Per-job UUID directories outside the public static root.
- Original upload files are stored under an internal temporary name and deleted after conversion.
- Runtime data is stored under `data/` by default and can be isolated with `FILE_TRANS_DATA_DIR`.
- Download URLs require both a job ID and a random token.
- Result metadata stores output integrity data but not the original filename.
- Download responses verify output size and SHA-256 before serving.
- Explicit cross-site browser POSTs to the conversion endpoint are rejected with `Origin`/`Sec-Fetch-Site` checks.
- Split frontend/backend deployments must list trusted frontend origins in `FILE_TRANS_ALLOWED_ORIGINS`.
- Conversion subprocesses run with stdin disabled, timeout, process group termination, reduced environment, and resource limits where supported.
- Local conversion processes use `data/runtime-home` as `HOME`, not the operator's home directory.
- Conversion tool lookup and subprocess `PATH` are restricted to absolute system paths by default.
- Binary HWP to PDF is advertised only when the LibreOffice HWP import filter marker is present.
- Docker worker mode adds `network none`, read-only root filesystem, `cap-drop ALL`, `no-new-privileges`, PID/memory/CPU limits, tmpfs `/tmp`, and a non-root default image user.
- ImageMagick uses `config/imagemagick/policy.xml` with delegates and risky coders disabled.
- Server responses include basic security headers and avoid exposing the Python runtime version.
- The split frontend helper server disables caching, sends basic security headers, avoids exposing the Python runtime version, blocks directory listing/static symlink escapes, and allows only GET/HEAD/OPTIONS.
- Access logs redact download tokens.
- Upload rate limiting, concurrent conversion limits, request read timeout, and result cleanup interval are configurable.
- Optional ClamAV scanning can be enabled with `FILE_TRANS_ENABLE_CLAMSCAN=1`.

## Important Limits

Default limits are intentionally conservative for a local MVP:

- `FILE_TRANS_MAX_UPLOAD`: 100 MiB
- `FILE_TRANS_MAX_MULTIPART_OVERHEAD`: 1 MiB request overhead allowance before multipart parsing
- `FILE_TRANS_MAX_OUTPUT`: 1 GiB
- `FILE_TRANS_PROCESS_MEMORY`: 1 GiB address-space limit for local converter processes where supported
- `FILE_TRANS_PROCESS_FILES`: 128 open files for local converter processes where supported
- `FILE_TRANS_PROCESS_COUNT`: 96 processes for local converter process groups where supported
- `FILE_TRANS_DATA_DIR`: runtime data root for uploads, outputs, and converter home
- `FILE_TRANS_CONVERT_TIMEOUT`: 60 seconds
- `FILE_TRANS_MAX_CONCURRENT`: 2 conversions
- `FILE_TRANS_RATE_MAX`: 30 uploads per IP per window
- `FILE_TRANS_RATE_WINDOW`: 600 seconds
- `FILE_TRANS_REQUEST_TIMEOUT`: 30 seconds
- `FILE_TRANS_ALLOWED_ORIGINS`: comma-separated trusted browser origins for split frontend/backend ports
- `FILE_TRANS_HWP_FILTER_MARKER`: marker path for enabling `hwp -> pdf`, default `/usr/lib/libreoffice/share/extensions/h2orestart/H2Orestart.jar`
- `FILE_TRANS_MAX_DATA_RECORDS`: 100000 records
- `FILE_TRANS_MAX_ARCHIVE_MEMBERS`: 2000 ZIP container members
- `FILE_TRANS_MAX_ARCHIVE_UNCOMPRESSED`: 512 MiB total ZIP container uncompressed size
- `FILE_TRANS_MAX_REFERENCE_SCAN`: 20 MiB of document metadata for external reference checks
- `FILE_TRANS_CONVERT_PATH`: safe absolute search path for conversion tools
- `FILE_TRANS_RESULT_TTL`: 24 hours
- `FILE_TRANS_CLEANUP_INTERVAL`: 600 seconds
- `FILE_TRANS_CLAMSCAN_TIMEOUT`: 30 seconds, only when ClamAV scanning is enabled
- Frontend workspace: 30 selected files per batch, 512 MiB total for browser-generated ZIP downloads

## Deployment Guidance

For public service use, prefer Docker worker mode:

```bash
make build-worker
FILE_TRANS_USE_DOCKER=1 make run-docker-worker
```

Do not expose `data/`, `build/`, `deploy/`, `.env*`, `개발일지.md`, or `요구사항` through a web server or Git.

To add malware scanning, install and update ClamAV on the host, then start the app with `FILE_TRANS_ENABLE_CLAMSCAN=1`. Use `FILE_TRANS_CLAMSCAN=/path/to/clamscan` if the binary is not on `PATH`.

Put a reverse proxy in front of the app for TLS, request body limits, access logs, and IP-based abuse controls. Keep the worker image and conversion tools patched.

## Non-Goals

This project is not a safe online compiler or code execution sandbox. It does not include C++, Java, Rust, or C# build probes, and the web server must not compile or execute user-submitted code.

This project does not remove malicious active content from converted files. It only limits server-side processing risk and serves results as attachments.
