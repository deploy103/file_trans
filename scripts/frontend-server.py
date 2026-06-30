#!/usr/bin/env python3
import os
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DIR = ROOT / "public"
PUBLIC_ROOT = PUBLIC_DIR.resolve()
HOST = os.environ.get("FRONTEND_HOST", "127.0.0.1")
PORT = int(os.environ.get("FRONTEND_PORT", "4762"))


class FrontendHandler(SimpleHTTPRequestHandler):
    server_version = "FileTransFrontend"
    sys_version = ""

    def version_string(self) -> str:
        return self.server_version

    def list_directory(self, path):  # noqa: ANN001, N802 - stdlib API
        self.send_error(403)
        return None

    def method_not_allowed(self) -> None:
        self.send_response(405)
        self.send_header("Allow", "GET, HEAD, OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_OPTIONS(self) -> None:  # noqa: N802 - stdlib API
        self.send_response(204)
        self.send_header("Allow", "GET, HEAD, OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802 - stdlib API
        self.method_not_allowed()

    def do_PUT(self) -> None:  # noqa: N802 - stdlib API
        self.method_not_allowed()

    def do_DELETE(self) -> None:  # noqa: N802 - stdlib API
        self.method_not_allowed()

    def do_TRACE(self) -> None:  # noqa: N802 - stdlib API
        self.method_not_allowed()

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        super().end_headers()

    def send_head(self):  # noqa: N802 - stdlib API
        request_path = urlparse(self.path).path
        filesystem_path = Path(self.translate_path(request_path))
        try:
            filesystem_path.resolve().relative_to(PUBLIC_ROOT)
        except ValueError:
            self.send_error(403)
            return None
        if not filesystem_path.exists() and not Path(request_path).suffix:
            self.path = "/index.html"
        return super().send_head()


class FrontendServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def main() -> None:
    handler = partial(FrontendHandler, directory=str(PUBLIC_DIR))
    server = FrontendServer((HOST, PORT), handler)
    print(f"FileTrans frontend running at http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
