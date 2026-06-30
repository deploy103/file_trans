#!/usr/bin/env python3
import os
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server  # noqa: E402

FORBIDDEN_TRACKED_PREFIXES = ("data/", "build/", "deploy/", "secrets/", "private/", "tools/")
FORBIDDEN_TRACKED_NAMES = {"개발일지.md", "요구사항", ".env", ".env.local", "scripts/build-toolchain.sh"}


def fail(message: str) -> None:
    print(f"security-audit: {message}", file=sys.stderr)
    raise SystemExit(1)


def tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def check_tracked_files() -> None:
    for filename in tracked_files():
        if not (ROOT / filename).exists():
            continue
        if filename in FORBIDDEN_TRACKED_NAMES:
            fail(f"forbidden tracked file: {filename}")
        if filename.startswith(FORBIDDEN_TRACKED_PREFIXES):
            fail(f"forbidden tracked path: {filename}")


def check_command_execution() -> None:
    source = (ROOT / "server.py").read_text(encoding="utf-8")
    forbidden = ["os.system", "shell=True", "subprocess.call(", "subprocess.check_output("]
    for needle in forbidden:
        if needle in source:
            fail(f"forbidden command execution pattern found: {needle}")

    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    if "build-tools:" in makefile:
        fail("Makefile must not expose a code build-tools target")


def check_conversion_path() -> None:
    path_entries = server.conversion_env()["PATH"].split(os.pathsep)
    if not path_entries:
        fail("conversion PATH must not be empty")
    for entry in path_entries:
        path = Path(entry)
        if not path.is_absolute():
            fail(f"conversion PATH entry must be absolute: {entry}")
        if entry == ".":
            fail("conversion PATH must not include current directory")


def check_imagemagick_policy() -> None:
    policy = ROOT / "config" / "imagemagick" / "policy.xml"
    if not policy.exists():
        fail("missing ImageMagick policy.xml")
    text = policy.read_text(encoding="utf-8")
    required = [
        'domain="delegate" rights="none" pattern="*"',
        'domain="coder" rights="none" pattern="HTTP"',
        'domain="coder" rights="none" pattern="HTTPS"',
        'domain="path" rights="none" pattern="@*"',
    ]
    for needle in required:
        if needle not in text:
            fail(f"ImageMagick policy missing: {needle}")


def check_docker_worker() -> None:
    dockerfile = ROOT / "docker" / "convert-worker.Dockerfile"
    if not dockerfile.exists():
        fail("missing Docker worker Dockerfile")
    text = dockerfile.read_text(encoding="utf-8")
    if "\nUSER 10001:10001" not in f"\n{text}":
        fail("Docker worker must default to a non-root USER")

    server_source = (ROOT / "server.py").read_text(encoding="utf-8")
    required_run_options = [
        '"--network"',
        '"none"',
        '"--read-only"',
        '"--cap-drop"',
        '"ALL"',
        '"--security-opt"',
        '"no-new-privileges:true"',
        '"--pids-limit"',
        '"--memory"',
        '"--cpus"',
        '"--tmpfs"',
    ]
    for needle in required_run_options:
        if needle not in server_source:
            fail(f"Docker worker wrapper missing run option: {needle}")


def check_ci_workflow() -> None:
    workflow = ROOT / ".github" / "workflows" / "ci.yml"
    if not workflow.exists():
        fail("missing GitHub Actions CI workflow")
    text = workflow.read_text(encoding="utf-8")
    for needle in ("make check", "make smoke-test"):
        if needle not in text:
            fail(f"CI workflow must run {needle}")


def check_capabilities() -> None:
    capabilities = server.capabilities()
    if capabilities["inputFormatCount"] < 40:
        fail("input format count is below requirement")
    if capabilities["maxUploadBytes"] <= 0:
        fail("max upload size must be positive")
    exposed_tools = set(capabilities.get("tools", {}))
    forbidden_tools = {"g++", "java", "rust", "csharp"}
    leaked_tools = exposed_tools & forbidden_tools
    if leaked_tools:
        fail(f"compiler tools must not be exposed in capabilities: {sorted(leaked_tools)}")
    if capabilities.get("helpers"):
        fail("build helpers must not be exposed in capabilities")


def check_frontend() -> None:
    for relative in ("public/index.html", "public/app.js", "public/styles.css"):
        text = (ROOT / relative).read_text(encoding="utf-8")
        for url in re.findall(r"https?://[^\"')\s<>]+", text):
            if not (url.startswith("http://127.0.0.1") or url.startswith("http://localhost")):
                fail(f"frontend asset must not depend on external URL: {relative}: {url}")
        for needle in ("innerHTML", "document.write", "eval("):
            if needle in text:
                fail(f"frontend asset must not use unsafe DOM/code pattern: {relative}: {needle}")

    frontend_server = (ROOT / "scripts" / "frontend-server.py").read_text(encoding="utf-8")
    required = [
        'server_version = "FileTransFrontend"',
        '"Cache-Control", "no-store"',
        '"X-Content-Type-Options", "nosniff"',
        '"X-Frame-Options", "DENY"',
        '"Referrer-Policy", "no-referrer"',
        '"Cross-Origin-Resource-Policy", "same-origin"',
        "PUBLIC_ROOT",
        ".relative_to(PUBLIC_ROOT)",
        "self.send_error(403)",
        "def list_directory",
        "def do_OPTIONS",
        "def do_TRACE",
        "def do_POST",
        "self.send_response(405)",
        "allow_reuse_address = True",
        "daemon_threads = True",
    ]
    for needle in required:
        if needle not in frontend_server:
            fail(f"frontend server missing security setting: {needle}")


def main() -> None:
    check_tracked_files()
    check_command_execution()
    check_conversion_path()
    check_imagemagick_policy()
    check_docker_worker()
    check_ci_workflow()
    check_capabilities()
    check_frontend()
    print("security audit passed")


if __name__ == "__main__":
    main()
