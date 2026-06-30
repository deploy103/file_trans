#!/usr/bin/env python3
import csv
import hashlib
import html
import json
import mimetypes
import os
import re
import secrets
import signal
import shutil
import struct
import subprocess
import threading
import time
import unicodedata
import uuid
import warnings
import zipfile
from dataclasses import dataclass
from http import HTTPStatus
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import quote, unquote
from xml.etree import ElementTree

try:
    import resource
except ImportError:  # pragma: no cover - Windows fallback
    resource = None

warnings.filterwarnings("ignore", category=DeprecationWarning, message="'cgi' is deprecated.*")
import cgi


ROOT = Path(__file__).resolve().parent
PUBLIC_DIR = ROOT / "public"
DATA_DIR = ROOT / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
OUTPUT_DIR = DATA_DIR / "outputs"
BUILD_DIR = ROOT / "build"
IMAGEMAGICK_POLICY_DIR = ROOT / "config" / "imagemagick"
USE_DOCKER_WORKER = os.environ.get("FILE_TRANS_USE_DOCKER", "").lower() in {"1", "true", "yes", "on"}
CONVERT_WORKER_IMAGE = os.environ.get("FILE_TRANS_WORKER_IMAGE", "file-trans-convert-worker:latest")
MAX_UPLOAD_BYTES = int(os.environ.get("FILE_TRANS_MAX_UPLOAD", str(100 * 1024 * 1024)))
MAX_CONVERSION_SECONDS = int(os.environ.get("FILE_TRANS_CONVERT_TIMEOUT", "60"))
RESULT_TTL_SECONDS = int(os.environ.get("FILE_TRANS_RESULT_TTL", str(24 * 60 * 60)))
MAX_OUTPUT_BYTES = int(os.environ.get("FILE_TRANS_MAX_OUTPUT", str(1024 * 1024 * 1024)))
MAX_PROCESS_MEMORY_BYTES = int(os.environ.get("FILE_TRANS_PROCESS_MEMORY", str(1024 * 1024 * 1024)))
MAX_PROCESS_FILES = int(os.environ.get("FILE_TRANS_PROCESS_FILES", "128"))
MAX_PROCESS_COUNT = int(os.environ.get("FILE_TRANS_PROCESS_COUNT", "96"))
MAX_ARCHIVE_MEMBERS = int(os.environ.get("FILE_TRANS_MAX_ARCHIVE_MEMBERS", "2000"))
MAX_ARCHIVE_UNCOMPRESSED_BYTES = int(
    os.environ.get("FILE_TRANS_MAX_ARCHIVE_UNCOMPRESSED", str(512 * 1024 * 1024))
)
RATE_LIMIT_WINDOW_SECONDS = int(os.environ.get("FILE_TRANS_RATE_WINDOW", "600"))
RATE_LIMIT_MAX_UPLOADS = int(os.environ.get("FILE_TRANS_RATE_MAX", "30"))
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8000"))

DOCUMENT_EXTS = {
    "doc",
    "docx",
    "fodp",
    "fods",
    "fodt",
    "ppt",
    "pptx",
    "xls",
    "xlsx",
    "odt",
    "ods",
    "odp",
    "rtf",
    "html",
    "htm",
    "hwp",
    "hwpx",
}
DATA_EXTS = {"csv", "json", "ndjson", "tsv"}
SUBTITLE_EXTS = {"srt", "vtt"}
MARKUP_EXTS = {"md", "rst", "org", "tex", "latex", "typ", "ipynb"}
TEXT_EXTS = {"txt", "xml", "log", "yaml", "yml", "hwpx"} | DATA_EXTS | SUBTITLE_EXTS | MARKUP_EXTS
VIDEO_EXTS = {
    "3g2",
    "3gp",
    "avi",
    "flv",
    "m2ts",
    "m4v",
    "mkv",
    "mov",
    "mp4",
    "mpeg",
    "mpg",
    "mts",
    "ogv",
    "ts",
    "webm",
    "wmv",
}
AUDIO_EXTS = {
    "aac",
    "aif",
    "aiff",
    "amr",
    "caf",
    "flac",
    "m4a",
    "mid",
    "midi",
    "mp3",
    "ogg",
    "opus",
    "wav",
    "wma",
}
IMAGE_EXTS = {
    "avif",
    "bmp",
    "gif",
    "heic",
    "ico",
    "jpeg",
    "jpg",
    "pbm",
    "pgm",
    "png",
    "pnm",
    "ppm",
    "psd",
    "tga",
    "tif",
    "tiff",
    "webp",
}
EBOOK_EXTS = {"azw3", "cbz", "chm", "djvu", "epub", "fb2", "mobi"}

AUDIO_TARGETS = {"aac", "aiff", "flac", "m4a", "mp3", "ogg", "opus", "wav"}
VIDEO_TARGETS = {"gif", "mkv", "mov", "mp4", "webm"}
IMAGE_TARGETS = {"avif", "bmp", "gif", "ico", "jpg", "jpeg", "pdf", "png", "tiff", "webp"}
PDF_IMAGE_TARGETS = {"jpg", "jpeg", "png"}
DATA_TARGETS = {"csv", "json", "tsv"}
SUBTITLE_TARGETS = {"srt", "vtt"}
MARKUP_TARGETS = {"docx", "epub", "html", "pdf"}
EBOOK_TARGETS = {"azw3", "epub", "mobi", "pdf", "txt"}
PDF_EXTS = {"pdf"}
ALLOWED_INPUT_EXTS = DOCUMENT_EXTS | TEXT_EXTS | VIDEO_EXTS | AUDIO_EXTS | IMAGE_EXTS | EBOOK_EXTS | PDF_EXTS
ALLOWED_TARGET_EXTS = (
    AUDIO_TARGETS
    | VIDEO_TARGETS
    | IMAGE_TARGETS
    | PDF_IMAGE_TARGETS
    | DATA_TARGETS
    | SUBTITLE_TARGETS
    | MARKUP_TARGETS
    | EBOOK_TARGETS
    | {"zip"}
)
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{32,96}$")
EXT_RE = re.compile(r"^[a-z0-9]{1,12}$")
CHUNK_SIZE = 1024 * 1024
CONTAINER_TOOL_NAMES = {
    "ebook-convert",
    "ffmpeg",
    "libreoffice",
    "soffice",
    "magick",
    "convert",
    "pandoc",
    "pdftoppm",
    "pdftotext",
}


class ConversionError(Exception):
    pass


@dataclass(frozen=True)
class FileValidation:
    ext: str
    detected: str
    size: int
    sha256: str


class UploadRateLimiter:
    def __init__(self, window_seconds: int, max_uploads: int):
        self.window_seconds = window_seconds
        self.max_uploads = max_uploads
        self._lock = threading.Lock()
        self._events: dict[str, list[float]] = {}

    def allow(self, key: str) -> bool:
        if self.max_uploads <= 0:
            return True
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            events = [item for item in self._events.get(key, []) if item >= cutoff]
            if len(events) >= self.max_uploads:
                self._events[key] = events
                return False
            events.append(now)
            self._events[key] = events
            return True


rate_limiter = UploadRateLimiter(RATE_LIMIT_WINDOW_SECONDS, RATE_LIMIT_MAX_UPLOADS)


def ensure_dirs() -> None:
    mkdir_private(UPLOAD_DIR)
    mkdir_private(OUTPUT_DIR)
    purge_upload_staging()
    cleanup_expired_jobs()


def sanitize_filename(name: str) -> str:
    name = Path(name or "upload.bin").name
    name = re.sub(r"[^\w.\-가-힣()\[\] ]+", "_", name, flags=re.UNICODE).strip()
    return name or "upload.bin"


def stem_for_output(original_name: str) -> str:
    stem = Path(original_name).stem
    stem = re.sub(r"[^\w.\-가-힣()\[\] ]+", "_", stem, flags=re.UNICODE).strip()
    return stem or "converted"


def local_tool_path(*names: str) -> str | None:
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return None


def tool_path(*names: str) -> str | None:
    if USE_DOCKER_WORKER and any(name in CONTAINER_TOOL_NAMES for name in names):
        if not local_tool_path("docker"):
            return None
        if "convert" in names:
            return "convert"
        if "libreoffice" in names:
            return "libreoffice"
        if "pdftoppm" in names:
            return "pdftoppm"
        return names[0]
    return local_tool_path(*names)


def installed_tools() -> dict:
    return {
        "ffmpeg": tool_path("ffmpeg"),
        "libreoffice": tool_path("libreoffice", "soffice"),
        "imagemagick": tool_path("magick", "convert"),
        "poppler": tool_path("pdftoppm", "pdftotext"),
        "pandoc": tool_path("pandoc"),
        "calibre": tool_path("ebook-convert"),
        "g++": local_tool_path("g++"),
        "java": local_tool_path("javac"),
        "rust": local_tool_path("rustc"),
        "csharp": local_tool_path("dotnet", "mcs", "csc"),
    }


def built_helpers() -> dict:
    helpers = {
        "cpp_probe": BUILD_DIR / "tools" / "fileprobe-cpp",
        "rust_probe": BUILD_DIR / "tools" / "fileprobe-rust",
        "java_probe": BUILD_DIR / "tools" / "java" / "FileProbe.class",
        "csharp_probe": BUILD_DIR / "tools" / "fileprobe-cs.exe",
    }
    return {name: str(path) if path.exists() else None for name, path in helpers.items()}


def public_tool_status(values: dict) -> dict:
    return {name: bool(value) for name, value in values.items()}


def operations() -> list[dict]:
    tools = installed_tools()
    has_ffmpeg = bool(tools["ffmpeg"])
    has_office = bool(tools["libreoffice"])
    has_image = bool(tools["imagemagick"])
    has_pdftoppm = bool(tool_path("pdftoppm"))
    has_pdftotext = bool(tool_path("pdftotext"))
    has_pandoc = bool(tools["pandoc"])
    has_calibre = bool(tools["calibre"])

    ops = [
        {
            "id": "media-audio",
            "label": "영상/오디오 -> 오디오",
            "from": sorted(VIDEO_EXTS | AUDIO_EXTS),
            "to": sorted(AUDIO_TARGETS),
            "engine": "ffmpeg",
            "available": has_ffmpeg,
        },
        {
            "id": "media-video",
            "label": "영상 -> 영상",
            "from": sorted(VIDEO_EXTS),
            "to": sorted(VIDEO_TARGETS),
            "engine": "ffmpeg",
            "available": has_ffmpeg,
        },
        {
            "id": "document-pdf",
            "label": "Office/HWP -> PDF",
            "from": sorted(DOCUMENT_EXTS - {"hwpx"}),
            "to": ["pdf"],
            "engine": "libreoffice",
            "available": has_office,
        },
        {
            "id": "image",
            "label": "이미지 변환",
            "from": sorted(IMAGE_EXTS),
            "to": sorted(IMAGE_TARGETS),
            "engine": "imagemagick",
            "available": has_image,
        },
        {
            "id": "pdf-image",
            "label": "PDF -> 이미지",
            "from": ["pdf"],
            "to": sorted(PDF_IMAGE_TARGETS),
            "engine": "poppler",
            "available": has_pdftoppm,
        },
        {
            "id": "pdf-text",
            "label": "PDF -> 텍스트",
            "from": ["pdf"],
            "to": ["txt"],
            "engine": "poppler",
            "available": has_pdftotext,
        },
        {
            "id": "csv-json",
            "label": "CSV/TSV -> JSON",
            "from": ["csv", "tsv"],
            "to": ["json"],
            "engine": "python",
            "available": True,
        },
        {
            "id": "json-csv",
            "label": "JSON/NDJSON -> CSV/TSV",
            "from": ["json", "ndjson"],
            "to": ["csv", "tsv"],
            "engine": "python",
            "available": True,
        },
        {
            "id": "ndjson-json",
            "label": "NDJSON -> JSON",
            "from": ["ndjson"],
            "to": ["json"],
            "engine": "python",
            "available": True,
        },
        {
            "id": "subtitle",
            "label": "자막 변환",
            "from": sorted(SUBTITLE_EXTS),
            "to": sorted(SUBTITLE_TARGETS),
            "engine": "python",
            "available": True,
        },
        {
            "id": "text-html",
            "label": "텍스트/마크업/HWPX -> HTML",
            "from": sorted(TEXT_EXTS),
            "to": ["html"],
            "engine": "python",
            "available": True,
        },
        {
            "id": "text-pdf",
            "label": "텍스트/마크업/HWPX -> PDF",
            "from": sorted(TEXT_EXTS),
            "to": ["pdf"],
            "engine": "python",
            "available": True,
        },
        {
            "id": "markup-pandoc",
            "label": "마크업 문서 변환",
            "from": sorted(MARKUP_EXTS | {"html", "htm"}),
            "to": sorted(MARKUP_TARGETS),
            "engine": "pandoc",
            "available": has_pandoc,
        },
        {
            "id": "ebook",
            "label": "전자책 변환",
            "from": sorted(EBOOK_EXTS | {"html", "htm", "md", "pdf", "rtf", "txt"}),
            "to": sorted(EBOOK_TARGETS),
            "engine": "calibre",
            "available": has_calibre,
        },
        {
            "id": "zip",
            "label": "파일 -> ZIP",
            "from": sorted(ALLOWED_INPUT_EXTS),
            "to": ["zip"],
            "engine": "python",
            "available": True,
        },
    ]
    return ops


def targets_for_extension(ext: str) -> list[str]:
    ext = ext.lower().lstrip(".")
    if ext not in ALLOWED_INPUT_EXTS:
        return []
    targets = set()
    for op in operations():
        if "*" in op["from"] or ext in op["from"]:
            targets.update(op["to"])
    targets.discard(ext)
    return sorted(targets)


def capabilities() -> dict:
    return {
        "tools": public_tool_status(installed_tools()),
        "helpers": public_tool_status(built_helpers()),
        "operations": operations(),
        "inputFormats": sorted(ALLOWED_INPUT_EXTS),
        "targetFormats": sorted(ALLOWED_TARGET_EXTS),
        "inputFormatCount": len(ALLOWED_INPUT_EXTS),
        "targetFormatCount": len(ALLOWED_TARGET_EXTS),
        "maxUploadBytes": MAX_UPLOAD_BYTES,
        "maxConversionSeconds": MAX_CONVERSION_SECONDS,
        "resultTtlSeconds": RESULT_TTL_SECONDS,
    }


def read_text_file(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def chmod_private(path: Path) -> None:
    try:
        path.chmod(0o700)
    except OSError:
        pass


def mkdir_private(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    chmod_private(path)


def safe_unlink(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def remove_tree(path: Path) -> None:
    try:
        shutil.rmtree(path)
    except FileNotFoundError:
        pass


def cleanup_expired_jobs() -> None:
    now = time.time()
    if not OUTPUT_DIR.exists():
        return
    for child in OUTPUT_DIR.iterdir():
        if not child.is_dir():
            continue
        metadata_path = child / ".job.json"
        expires_at = None
        if metadata_path.exists():
            try:
                expires_at = float(read_json(metadata_path).get("expiresAt", 0))
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                expires_at = 0
        else:
            try:
                expires_at = child.stat().st_mtime + RESULT_TTL_SECONDS
            except OSError:
                expires_at = 0
        if expires_at and expires_at > now:
            continue
        remove_tree(child)


def purge_upload_staging() -> None:
    if not UPLOAD_DIR.exists():
        return
    for child in UPLOAD_DIR.iterdir():
        if child.is_dir():
            remove_tree(child)
        else:
            safe_unlink(child)


def copy_stream_limited(source, output_path: Path, max_bytes: int) -> tuple[int, str]:
    digest = hashlib.sha256()
    total = 0
    with output_path.open("wb") as handle:
        while True:
            chunk = source.read(CHUNK_SIZE)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise ConversionError("업로드 용량 제한을 초과했습니다.")
            digest.update(chunk)
            handle.write(chunk)
    if total <= 0:
        raise ConversionError("빈 파일은 변환할 수 없습니다.")
    return total, digest.hexdigest()


def archive_names(path: Path) -> list[str]:
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
    except zipfile.BadZipFile as exc:
        raise ConversionError("ZIP 기반 문서 구조가 올바르지 않습니다.") from exc

    if len(infos) > MAX_ARCHIVE_MEMBERS:
        raise ConversionError("압축 컨테이너의 파일 수가 너무 많습니다.")

    total_uncompressed = 0
    names = []
    for info in infos:
        normalized = info.filename.replace("\\", "/")
        parts = [part for part in normalized.split("/") if part]
        if normalized.startswith("/") or any(part == ".." for part in parts):
            raise ConversionError("압축 컨테이너에 안전하지 않은 경로가 포함되어 있습니다.")
        total_uncompressed += info.file_size
        if total_uncompressed > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
            raise ConversionError("압축 해제 예상 크기가 제한을 초과했습니다.")
        names.append(normalized)
    return names


def zip_has_prefix(names: list[str], prefix: str) -> bool:
    prefix = prefix.lower()
    return any(name.lower().startswith(prefix) for name in names)


def zip_has_name(names: list[str], expected: str) -> bool:
    expected = expected.lower()
    return any(name.lower() == expected for name in names)


def text_decodes(sample: bytes) -> bool:
    if b"\x00" in sample[:4096]:
        return False
    for encoding in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
        try:
            sample.decode(encoding)
            return True
        except UnicodeDecodeError:
            continue
    return False


def is_text_like(path: Path) -> bool:
    return text_decodes(path.read_bytes()[:8192])


def is_json_like(path: Path) -> bool:
    if not is_text_like(path):
        return False
    try:
        json.loads(read_text_file(path))
        return True
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return False


def is_ndjson_like(path: Path) -> bool:
    if not is_text_like(path):
        return False
    lines = [line for line in read_text_file(path).splitlines() if line.strip()]
    if not lines:
        return False
    try:
        for line in lines[:1000]:
            json.loads(line)
        return True
    except json.JSONDecodeError:
        return False


def is_xml_like(path: Path) -> bool:
    sample = path.read_bytes()[:8192]
    if not text_decodes(sample):
        return False
    stripped = sample.lstrip()
    return stripped.startswith(b"<?xml") or stripped.startswith(b"<")


def is_rtf_like(sample: bytes) -> bool:
    return sample.startswith(b"{\\rtf")


def is_mp4_like(sample: bytes, allowed_brands: set[str] | None = None) -> bool:
    if len(sample) < 12 or sample[4:8] != b"ftyp":
        return False
    brands = {
        sample[8:12].decode("latin-1", errors="ignore").strip(),
        *[
            sample[index : index + 4].decode("latin-1", errors="ignore").strip()
            for index in range(16, min(len(sample), 96), 4)
        ],
    }
    brands.discard("")
    if allowed_brands is None:
        return True
    return bool(brands & allowed_brands)


def is_mpeg_video(sample: bytes) -> bool:
    return sample.startswith((b"\x00\x00\x01\xba", b"\x00\x00\x01\xb3"))


def is_transport_stream(path: Path) -> bool:
    data = path.read_bytes()[:192 * 5]
    if len(data) < 188 * 3:
        return False
    if all(data[index] == 0x47 for index in range(0, min(len(data), 188 * 5), 188)):
        return True
    return len(data) >= 192 * 3 and all(data[index] == 0x47 for index in range(4, min(len(data), 192 * 5), 192))


def is_tga_like(path: Path) -> bool:
    try:
        trailer = path.read_bytes()[-26:]
    except OSError:
        return False
    return trailer.endswith(b"TRUEVISION-XFILE.\x00")


def detect_magic(path: Path, ext: str) -> str:
    sample = path.read_bytes()[:8192]
    lower_ext = ext.lower()
    ole = sample.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
    signatures = {
        "pdf": sample.startswith(b"%PDF-"),
        "png": sample.startswith(b"\x89PNG\r\n\x1a\n"),
        "jpg": sample.startswith(b"\xff\xd8\xff"),
        "jpeg": sample.startswith(b"\xff\xd8\xff"),
        "gif": sample.startswith((b"GIF87a", b"GIF89a")),
        "bmp": sample.startswith(b"BM"),
        "ico": sample.startswith((b"\x00\x00\x01\x00", b"\x00\x00\x02\x00")),
        "psd": sample.startswith(b"8BPS"),
        "pnm": sample[:2] in {b"P1", b"P2", b"P3", b"P4", b"P5", b"P6", b"P7"},
        "pbm": sample[:2] in {b"P1", b"P4"},
        "pgm": sample[:2] in {b"P2", b"P5"},
        "ppm": sample[:2] in {b"P3", b"P6"},
        "tga": is_tga_like(path),
        "tif": sample.startswith((b"II*\x00", b"MM\x00*")),
        "tiff": sample.startswith((b"II*\x00", b"MM\x00*")),
        "webp": sample.startswith(b"RIFF") and sample[8:12] == b"WEBP",
        "avi": sample.startswith(b"RIFF") and sample[8:12] == b"AVI ",
        "wav": sample.startswith(b"RIFF") and sample[8:12] == b"WAVE",
        "aif": sample.startswith(b"FORM") and sample[8:12] in {b"AIFF", b"AIFC"},
        "aiff": sample.startswith(b"FORM") and sample[8:12] in {b"AIFF", b"AIFC"},
        "amr": sample.startswith((b"#!AMR\n", b"#!AMR-WB\n")),
        "mid": sample.startswith(b"MThd"),
        "midi": sample.startswith(b"MThd"),
        "caf": sample.startswith(b"caff"),
        "flac": sample.startswith(b"fLaC"),
        "ogg": sample.startswith(b"OggS"),
        "ogv": sample.startswith(b"OggS"),
        "opus": sample.startswith(b"OggS"),
        "mp3": sample.startswith(b"ID3") or (len(sample) >= 2 and sample[0] == 0xFF and sample[1] & 0xE0 == 0xE0),
        "aac": len(sample) >= 2 and sample[0] == 0xFF and sample[1] & 0xF0 == 0xF0,
        "flv": sample.startswith(b"FLV"),
        "mkv": sample.startswith(b"\x1a\x45\xdf\xa3"),
        "webm": sample.startswith(b"\x1a\x45\xdf\xa3"),
        "mpg": is_mpeg_video(sample),
        "mpeg": is_mpeg_video(sample),
        "ts": is_transport_stream(path),
        "mts": is_transport_stream(path),
        "m2ts": is_transport_stream(path),
        "wma": sample.startswith(b"\x30\x26\xb2\x75\x8e\x66\xcf\x11\xa6\xd9\x00\xaa\x00\x62\xce\x6c"),
        "wmv": sample.startswith(b"\x30\x26\xb2\x75\x8e\x66\xcf\x11\xa6\xd9\x00\xaa\x00\x62\xce\x6c"),
        "djvu": sample.startswith(b"AT&TFORM") and b"DJV" in sample[:32],
        "chm": sample.startswith(b"ITSF"),
        "hwp": ole,
        "doc": ole,
        "xls": ole,
        "ppt": ole,
        "rtf": is_rtf_like(sample),
        "mp4": is_mp4_like(sample),
        "mov": is_mp4_like(sample),
        "m4v": is_mp4_like(sample),
        "m4a": is_mp4_like(sample),
        "3gp": is_mp4_like(sample, {"3gp4", "3gp5", "3gp6", "3gp7", "3ge6", "3ge7"}),
        "3g2": is_mp4_like(sample, {"3g2a", "3g2b", "3g2c"}),
        "heic": is_mp4_like(sample, {"heic", "heix", "hevc", "hevx", "mif1", "msf1"}),
        "avif": is_mp4_like(sample, {"avif", "avis"}),
    }
    if lower_ext in signatures and signatures[lower_ext]:
        return lower_ext

    if lower_ext in {"docx", "pptx", "xlsx", "odt", "ods", "odp", "hwpx", "epub", "cbz"} and sample.startswith(b"PK\x03\x04"):
        names = archive_names(path)
        if lower_ext == "docx" and zip_has_prefix(names, "word/"):
            return "docx"
        if lower_ext == "pptx" and zip_has_prefix(names, "ppt/"):
            return "pptx"
        if lower_ext == "xlsx" and zip_has_prefix(names, "xl/"):
            return "xlsx"
        if lower_ext == "hwpx" and (zip_has_prefix(names, "contents/") or zip_has_name(names, "mimetype")):
            return "hwpx"
        if lower_ext == "epub" and zip_has_name(names, "mimetype"):
            return "epub"
        if lower_ext == "cbz":
            return "cbz"
        if lower_ext in {"odt", "ods", "odp"} and zip_has_name(names, "mimetype"):
            return lower_ext

    if lower_ext in {"azw3", "mobi"} and b"BOOKMOBI" in sample[:256]:
        return lower_ext
    if lower_ext == "fb2" and is_xml_like(path):
        return "fb2"
    if lower_ext in {"fodt", "fods", "fodp"} and is_xml_like(path):
        return lower_ext
    if lower_ext == "ndjson" and is_ndjson_like(path):
        return "ndjson"
    if lower_ext in {"json"} and is_json_like(path):
        return "json"
    if lower_ext in {"xml"} and is_xml_like(path):
        return "xml"
    if lower_ext in {
        "csv",
        "html",
        "htm",
        "ipynb",
        "latex",
        "log",
        "md",
        "org",
        "rst",
        "srt",
        "tex",
        "tsv",
        "txt",
        "typ",
        "vtt",
        "yaml",
        "yml",
    } and is_text_like(path):
        return "text"
    return "unknown"


def validate_upload_file(path: Path, original_name: str, size: int, digest: str) -> FileValidation:
    ext = Path(original_name).suffix.lower().lstrip(".")
    if not ext or not EXT_RE.match(ext):
        raise ConversionError("확장자가 있는 파일만 업로드할 수 있습니다.")
    if ext not in ALLOWED_INPUT_EXTS:
        raise ConversionError(f".{ext} 파일은 업로드 허용 목록에 없습니다.")
    if size > MAX_UPLOAD_BYTES:
        raise ConversionError("업로드 용량 제한을 초과했습니다.")

    detected = detect_magic(path, ext)
    if detected == "unknown":
        raise ConversionError("파일 내용이 확장자와 일치하지 않거나 지원하지 않는 형식입니다.")
    return FileValidation(ext=ext, detected=detected, size=size, sha256=digest)


def metadata_path(job_output_dir: Path) -> Path:
    return job_output_dir / ".job.json"


def create_download_metadata(
    job_id: str,
    output_path: Path,
    original_name: str,
    source: FileValidation,
) -> dict:
    token = secrets.token_urlsafe(32)
    size = output_path.stat().st_size
    with output_path.open("rb") as handle:
        output_sha256 = hashlib.file_digest(handle, "sha256").hexdigest()
    now = time.time()
    metadata = {
        "jobId": job_id,
        "token": token,
        "outputName": output_path.name,
        "originalName": original_name,
        "sourceExt": source.ext,
        "sourceDetected": source.detected,
        "sourceSize": source.size,
        "sourceSha256": source.sha256,
        "outputSize": size,
        "outputSha256": output_sha256,
        "createdAt": now,
        "expiresAt": now + RESULT_TTL_SECONDS,
    }
    write_json(metadata_path(output_path.parent), metadata)
    return metadata


def load_download_metadata(job_id: str) -> dict | None:
    if not re.fullmatch(r"[0-9a-f]{32}", job_id):
        return None
    path = OUTPUT_DIR / job_id / ".job.json"
    try:
        metadata = read_json(path)
    except (OSError, json.JSONDecodeError):
        return None
    if metadata.get("expiresAt", 0) < time.time():
        remove_tree(path.parent)
        return None
    return metadata


def convert_delimited_to_json(input_path: Path, output_path: Path, delimiter: str | None = None) -> None:
    text = read_text_file(input_path)
    sample = text[:4096]
    if delimiter is None:
        try:
            dialect = csv.Sniffer().sniff(sample)
        except csv.Error:
            dialect = csv.excel
        rows = list(csv.DictReader(text.splitlines(), dialect=dialect))
    else:
        rows = list(csv.DictReader(text.splitlines(), delimiter=delimiter))
    write_json(output_path, rows)


def convert_csv_to_json(input_path: Path, output_path: Path) -> None:
    convert_delimited_to_json(input_path, output_path)


def convert_tsv_to_json(input_path: Path, output_path: Path) -> None:
    convert_delimited_to_json(input_path, output_path, "\t")


def read_ndjson(input_path: Path) -> list:
    records = []
    for line_no, line in enumerate(read_text_file(input_path).splitlines(), start=1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ConversionError(f"NDJSON {line_no}번째 줄을 파싱하지 못했습니다: {exc.msg}") from exc
    if not records:
        raise ConversionError("NDJSON에 변환할 레코드가 없습니다.")
    return records


def convert_ndjson_to_json(input_path: Path, output_path: Path) -> None:
    write_json(output_path, read_ndjson(input_path))


def normalize_json_records(data):
    if isinstance(data, list):
        records = data
    elif isinstance(data, dict):
        list_value = next((v for v in data.values() if isinstance(v, list)), None)
        records = list_value if list_value is not None else [data]
    else:
        raise ConversionError("JSON 최상위 값은 객체 또는 객체 배열이어야 CSV로 변환할 수 있습니다.")

    normalized = []
    fieldnames: list[str] = []
    for item in records:
        if not isinstance(item, dict):
            item = {"value": item}
        flat = {}
        for key, value in item.items():
            flat[str(key)] = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value
        normalized.append(flat)
        for key in flat:
            if key not in fieldnames:
                fieldnames.append(key)
    return normalized, fieldnames


def convert_json_to_delimited(input_path: Path, output_path: Path, delimiter: str = ",") -> None:
    data = json.loads(read_text_file(input_path))
    rows, fieldnames = normalize_json_records(data)
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter=delimiter)
        writer.writeheader()
        writer.writerows(rows)


def convert_json_to_csv(input_path: Path, output_path: Path) -> None:
    convert_json_to_delimited(input_path, output_path)


def convert_json_to_tsv(input_path: Path, output_path: Path) -> None:
    convert_json_to_delimited(input_path, output_path, "\t")


def convert_ndjson_to_delimited(input_path: Path, output_path: Path, delimiter: str = ",") -> None:
    rows, fieldnames = normalize_json_records(read_ndjson(input_path))
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter=delimiter)
        writer.writeheader()
        writer.writerows(rows)


def convert_ndjson_to_csv(input_path: Path, output_path: Path) -> None:
    convert_ndjson_to_delimited(input_path, output_path)


def convert_ndjson_to_tsv(input_path: Path, output_path: Path) -> None:
    convert_ndjson_to_delimited(input_path, output_path, "\t")


def convert_srt_to_vtt(input_path: Path, output_path: Path) -> None:
    text = read_text_file(input_path).replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"(\d{2}:\d{2}:\d{2}),(\d{3})", r"\1.\2", text)
    output_path.write_text("WEBVTT\n\n" + text.strip() + "\n", encoding="utf-8")


def convert_vtt_to_srt(input_path: Path, output_path: Path) -> None:
    text = read_text_file(input_path).replace("\r\n", "\n").replace("\r", "\n")
    lines = text.splitlines()
    if lines and lines[0].lstrip("\ufeff").strip().upper().startswith("WEBVTT"):
        lines = lines[1:]
    blocks = []
    current = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if current:
                blocks.append(current)
                current = []
            continue
        if stripped.startswith(("NOTE", "STYLE", "REGION")):
            continue
        current.append(line)
    if current:
        blocks.append(current)

    output_blocks = []
    cue_index = 1
    for block in blocks:
        if not any("-->" in line for line in block):
            continue
        converted = [re.sub(r"(\d{2}:\d{2}:\d{2})\.(\d{3})", r"\1,\2", line) for line in block]
        if not converted[0].strip().isdigit():
            converted.insert(0, str(cue_index))
        output_blocks.append("\n".join(converted))
        cue_index += 1
    output_path.write_text("\n\n".join(output_blocks).strip() + "\n", encoding="utf-8")


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def parse_safe_xml(data: bytes):
    upper = data[:4096].upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise ConversionError("DTD 또는 ENTITY가 포함된 XML은 처리하지 않습니다.")
    return ElementTree.fromstring(data)


def extract_hwpx_text(path: Path) -> str:
    paragraphs: list[str] = []
    try:
        archive_names(path)
        with zipfile.ZipFile(path) as archive:
            xml_names = [
                name
                for name in archive.namelist()
                if name.lower().startswith("contents/section") and name.lower().endswith(".xml")
            ]
            if not xml_names:
                xml_names = [name for name in archive.namelist() if name.lower().endswith(".xml")]
            for name in sorted(xml_names):
                root = parse_safe_xml(archive.read(name))
                section_paragraphs = []
                for element in root.iter():
                    if local_name(element.tag) in {"p", "para", "paragraph"}:
                        parts = [
                            child.text
                            for child in element.iter()
                            if local_name(child.tag) in {"t", "text"} and child.text
                        ]
                        if parts:
                            section_paragraphs.append("".join(parts))
                if section_paragraphs:
                    paragraphs.extend(section_paragraphs)
            if not paragraphs:
                for name in sorted(xml_names):
                    root = parse_safe_xml(archive.read(name))
                    paragraphs.extend(
                        element.text
                        for element in root.iter()
                        if local_name(element.tag) in {"t", "text"} and element.text
                    )
    except (zipfile.BadZipFile, ElementTree.ParseError, ConversionError) as exc:
        raise ConversionError(f"HWPX 텍스트를 읽지 못했습니다: {exc}") from exc
    return "\n".join(paragraphs).strip()


def markdownish_to_html(text: str, title: str) -> str:
    lines = text.splitlines()
    body: list[str] = []
    in_list = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if in_list:
                body.append("</ul>")
                in_list = False
            body.append("")
            continue
        if stripped.startswith("#"):
            if in_list:
                body.append("</ul>")
                in_list = False
            level = min(len(stripped) - len(stripped.lstrip("#")), 6)
            content = stripped[level:].strip()
            body.append(f"<h{level}>{html.escape(content)}</h{level}>")
            continue
        if stripped.startswith(("- ", "* ")):
            if not in_list:
                body.append("<ul>")
                in_list = True
            body.append(f"<li>{html.escape(stripped[2:])}</li>")
            continue
        if in_list:
            body.append("</ul>")
            in_list = False
        body.append(f"<p>{html.escape(stripped)}</p>")
    if in_list:
        body.append("</ul>")

    return """<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <title>{title}</title>
  <style>
    body {{
      color: #1d2433;
      font-family: "Malgun Gothic", "Apple SD Gothic Neo", "Noto Sans CJK KR", Arial, sans-serif;
      line-height: 1.65;
      margin: 48px auto;
      max-width: 820px;
      padding: 0 24px;
    }}
    h1, h2, h3 {{ line-height: 1.25; }}
    pre, code {{ font-family: Consolas, "Ubuntu Mono", monospace; }}
  </style>
</head>
<body>
{body}
</body>
</html>
""".format(title=html.escape(title), body="\n".join(body))


def convert_text_to_html(input_path: Path, output_path: Path, original_name: str) -> None:
    if input_path.suffix.lower() == ".hwpx":
        text = extract_hwpx_text(input_path)
    else:
        text = read_text_file(input_path)
    output_path.write_text(markdownish_to_html(text, Path(original_name).stem), encoding="utf-8")


def _u16(data: bytes, offset: int) -> int:
    return struct.unpack_from(">H", data, offset)[0]


def _i16(data: bytes, offset: int) -> int:
    return struct.unpack_from(">h", data, offset)[0]


def _u32(data: bytes, offset: int) -> int:
    return struct.unpack_from(">I", data, offset)[0]


class TrueTypeFont:
    def __init__(self, path: Path):
        self.path = path
        self.data = path.read_bytes()
        self.tables = self._read_tables()
        self.units_per_em = 1000
        self.bbox = (-50, -200, 1000, 900)
        self.ascent = 800
        self.descent = -200
        self.num_h_metrics = 0
        self.num_glyphs = 0
        self._advance_widths: list[int] = []
        self._cmap_format = 0
        self._cmap_offset = 0
        self._load_metrics()
        self._load_cmap()

    def _read_tables(self) -> dict[str, tuple[int, int]]:
        num_tables = _u16(self.data, 4)
        tables: dict[str, tuple[int, int]] = {}
        for index in range(num_tables):
            offset = 12 + index * 16
            tag = self.data[offset : offset + 4].decode("latin-1")
            table_offset = _u32(self.data, offset + 8)
            length = _u32(self.data, offset + 12)
            tables[tag] = (table_offset, length)
        return tables

    def table(self, tag: str) -> bytes:
        if tag not in self.tables:
            raise ConversionError(f"폰트 테이블이 없습니다: {tag}")
        offset, length = self.tables[tag]
        return self.data[offset : offset + length]

    def _load_metrics(self) -> None:
        head = self.table("head")
        self.units_per_em = _u16(head, 18)
        self.bbox = (_i16(head, 36), _i16(head, 38), _i16(head, 40), _i16(head, 42))

        hhea = self.table("hhea")
        self.ascent = _i16(hhea, 4)
        self.descent = _i16(hhea, 6)
        self.num_h_metrics = _u16(hhea, 34)

        maxp = self.table("maxp")
        self.num_glyphs = _u16(maxp, 4)

        hmtx = self.table("hmtx")
        widths = []
        for gid in range(self.num_h_metrics):
            widths.append(_u16(hmtx, gid * 4))
        self._advance_widths = widths

    def _load_cmap(self) -> None:
        cmap = self.table("cmap")
        num_tables = _u16(cmap, 2)
        candidates: list[tuple[int, int, int, int]] = []
        for index in range(num_tables):
            record = 4 + index * 8
            platform = _u16(cmap, record)
            encoding = _u16(cmap, record + 2)
            offset = _u32(cmap, record + 4)
            fmt = _u16(cmap, offset)
            priority = 0
            if fmt == 12:
                priority = 4 if (platform, encoding) in {(3, 10), (0, 4)} else 3
            elif fmt == 4:
                priority = 2 if platform in {0, 3} else 1
            if priority:
                candidates.append((priority, fmt, platform, offset))
        if not candidates:
            raise ConversionError("PDF 폰트에서 Unicode cmap을 찾지 못했습니다.")
        _, self._cmap_format, _, self._cmap_offset = sorted(candidates, reverse=True)[0]

    def glyph_id(self, codepoint: int) -> int:
        cmap = self.table("cmap")
        offset = self._cmap_offset
        if self._cmap_format == 12:
            n_groups = _u32(cmap, offset + 12)
            group_offset = offset + 16
            for index in range(n_groups):
                base = group_offset + index * 12
                start_char = _u32(cmap, base)
                end_char = _u32(cmap, base + 4)
                start_gid = _u32(cmap, base + 8)
                if start_char <= codepoint <= end_char:
                    return int(start_gid + codepoint - start_char)
            return 0

        seg_count = _u16(cmap, offset + 6) // 2
        end_codes = offset + 14
        start_codes = end_codes + 2 * seg_count + 2
        id_deltas = start_codes + 2 * seg_count
        id_range_offsets = id_deltas + 2 * seg_count
        for index in range(seg_count):
            end_code = _u16(cmap, end_codes + 2 * index)
            start_code = _u16(cmap, start_codes + 2 * index)
            if not (start_code <= codepoint <= end_code):
                continue
            delta = _i16(cmap, id_deltas + 2 * index)
            range_offset = _u16(cmap, id_range_offsets + 2 * index)
            if range_offset == 0:
                return (codepoint + delta) & 0xFFFF
            glyph_offset = id_range_offsets + 2 * index + range_offset + 2 * (codepoint - start_code)
            if glyph_offset + 2 > len(cmap):
                return 0
            glyph = _u16(cmap, glyph_offset)
            return ((glyph + delta) & 0xFFFF) if glyph else 0
        return 0

    def width(self, glyph_id: int) -> int:
        if not self._advance_widths:
            return 1000
        if glyph_id < len(self._advance_widths):
            advance = self._advance_widths[glyph_id]
        else:
            advance = self._advance_widths[-1]
        return max(1, round(advance * 1000 / self.units_per_em))

    def scale(self, value: int) -> int:
        return round(value * 1000 / self.units_per_em)


def find_pdf_font(text: str) -> Path:
    has_korean = any("\uac00" <= char <= "\ud7a3" or "\u3130" <= char <= "\u318f" for char in text)
    candidates = []
    if has_korean:
        candidates.extend(
            [
                Path("/usr/share/fonts/truetype/nanum/NanumGothic.ttf"),
                Path("/usr/share/fonts/truetype/nanum/NanumBarunGothic.ttf"),
                Path("/mnt/c/Windows/Fonts/malgun.ttf"),
                Path("/mnt/c/Windows/Fonts/HANBatang.ttf"),
                Path("/mnt/c/Windows/Fonts/NGULIM.TTF"),
            ]
        )
    candidates.extend(
        [
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            Path("/usr/share/fonts/truetype/ubuntu/UbuntuSans[wdth,wght].ttf"),
            Path("/mnt/c/Windows/Fonts/arial.ttf"),
        ]
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise ConversionError("PDF 생성을 위한 TrueType 폰트를 찾지 못했습니다.")


def visual_width(text: str) -> int:
    width = 0
    for char in text:
        width += 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
    return width


def wrap_text_for_pdf(text: str, max_width: int = 86) -> list[str]:
    output: list[str] = []
    for paragraph in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if not paragraph:
            output.append("")
            continue
        current = ""
        for word in re.split(r"(\s+)", paragraph):
            if word == "":
                continue
            candidate = current + word
            if current and visual_width(candidate) > max_width:
                output.append(current.rstrip())
                current = word.lstrip()
            elif visual_width(word) > max_width:
                for char in word:
                    if current and visual_width(current + char) > max_width:
                        output.append(current.rstrip())
                        current = char
                    else:
                        current += char
            else:
                current = candidate
        output.append(current.rstrip())
    return output or [""]


def pdf_hex_text(line: str, font: TrueTypeFont) -> str:
    data = bytearray()
    for char in line:
        codepoint = ord(char)
        if codepoint > 0xFFFF:
            codepoint = ord("?")
        if font.glyph_id(codepoint) == 0 and codepoint not in {10, 13, 32}:
            codepoint = ord("?")
        data.extend(struct.pack(">H", codepoint))
    return data.hex().upper()


def pdf_name(name: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9]+", "", name)
    return safe or "EmbeddedFont"


class PDFBuilder:
    def __init__(self):
        self.objects: list[bytes] = []

    def add(self, body: bytes | str) -> int:
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.objects.append(body)
        return len(self.objects)

    def stream(self, dictionary: str, data: bytes) -> int:
        body = (
            f"<< {dictionary} /Length {len(data)} >>\nstream\n".encode("utf-8")
            + data
            + b"\nendstream"
        )
        return self.add(body)

    def build(self, root_id: int) -> bytes:
        output = bytearray(b"%PDF-1.7\n%\xE2\xE3\xCF\xD3\n")
        offsets = [0]
        for index, body in enumerate(self.objects, start=1):
            offsets.append(len(output))
            output.extend(f"{index} 0 obj\n".encode("ascii"))
            output.extend(body)
            output.extend(b"\nendobj\n")
        xref_start = len(output)
        output.extend(f"xref\n0 {len(self.objects) + 1}\n".encode("ascii"))
        output.extend(b"0000000000 65535 f \n")
        for offset in offsets[1:]:
            output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
        output.extend(
            f"trailer\n<< /Size {len(self.objects) + 1} /Root {root_id} 0 R >>\n"
            f"startxref\n{xref_start}\n%%EOF\n".encode("ascii")
        )
        return bytes(output)


def make_tounicode_cmap(chars: list[int]) -> bytes:
    chunks = [
        "/CIDInit /ProcSet findresource begin",
        "12 dict begin",
        "begincmap",
        "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def",
        "/CMapName /Adobe-Identity-UCS def",
        "/CMapType 2 def",
        "1 begincodespacerange",
        "<0000> <FFFF>",
        "endcodespacerange",
    ]
    for start in range(0, len(chars), 100):
        group = chars[start : start + 100]
        chunks.append(f"{len(group)} beginbfchar")
        for codepoint in group:
            chunks.append(f"<{codepoint:04X}> <{codepoint:04X}>")
        chunks.append("endbfchar")
    chunks.extend(["endcmap", "CMapName currentdict /CMap defineresource pop", "end", "end"])
    return ("\n".join(chunks) + "\n").encode("ascii")


def make_cid_to_gid_map(chars: list[int], font: TrueTypeFont) -> bytes:
    max_cid = max(chars + [255])
    mapping = bytearray((max_cid + 1) * 2)
    for codepoint in chars:
        gid = min(font.glyph_id(codepoint), 0xFFFF)
        mapping[codepoint * 2 : codepoint * 2 + 2] = struct.pack(">H", gid)
    return bytes(mapping)


def make_width_array(chars: list[int], font: TrueTypeFont) -> str:
    entries = []
    for codepoint in chars:
        gid = font.glyph_id(codepoint)
        entries.append(f"{codepoint} [{font.width(gid)}]")
    return "[ " + " ".join(entries) + " ]"


def make_text_pdf(text: str, output_path: Path, title: str) -> None:
    font_path = find_pdf_font(text)
    font = TrueTypeFont(font_path)
    font_label = pdf_name(font_path.stem)
    lines = wrap_text_for_pdf(text)

    page_width = 595
    page_height = 842
    margin = 48
    font_size = 11
    leading = 16
    lines_per_page = max(1, int((page_height - margin * 2) / leading))
    pages = [lines[index : index + lines_per_page] for index in range(0, len(lines), lines_per_page)]

    chars = sorted({ord(char) for line in lines for char in line if ord(char) <= 0xFFFF} | {32})
    builder = PDFBuilder()

    font_file_id = builder.stream("", font.data)
    cid_map_id = builder.stream("", make_cid_to_gid_map(chars, font))
    tounicode_id = builder.stream("", make_tounicode_cmap(chars))

    x_min, y_min, x_max, y_max = (font.scale(value) for value in font.bbox)
    descriptor_id = builder.add(
        f"<< /Type /FontDescriptor /FontName /{font_label} /Flags 4 "
        f"/FontBBox [{x_min} {y_min} {x_max} {y_max}] "
        f"/Ascent {font.scale(font.ascent)} /Descent {font.scale(font.descent)} "
        f"/CapHeight {font.scale(font.ascent)} /ItalicAngle 0 /StemV 80 "
        f"/FontFile2 {font_file_id} 0 R >>"
    )
    cid_font_id = builder.add(
        f"<< /Type /Font /Subtype /CIDFontType2 /BaseFont /{font_label} "
        f"/CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> "
        f"/FontDescriptor {descriptor_id} 0 R /CIDToGIDMap {cid_map_id} 0 R "
        f"/DW 1000 /W {make_width_array(chars, font)} >>"
    )
    type0_font_id = builder.add(
        f"<< /Type /Font /Subtype /Type0 /BaseFont /{font_label} /Encoding /Identity-H "
        f"/DescendantFonts [{cid_font_id} 0 R] /ToUnicode {tounicode_id} 0 R >>"
    )

    content_ids = []
    for page_lines in pages:
        content = [
            "BT",
            f"/F1 {font_size} Tf",
            f"{leading} TL",
            f"1 0 0 1 {margin} {page_height - margin - font_size} Tm",
        ]
        for line in page_lines:
            content.append(f"<{pdf_hex_text(line, font)}> Tj")
            content.append("T*")
        content.append("ET")
        content_ids.append(builder.stream("", ("\n".join(content) + "\n").encode("ascii")))

    first_page_id = len(builder.objects) + 1
    pages_id = first_page_id + len(content_ids)
    page_ids = []
    for content_id in content_ids:
        page_ids.append(
            builder.add(
                f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {page_width} {page_height}] "
                f"/Resources << /Font << /F1 {type0_font_id} 0 R >> >> "
                f"/Contents {content_id} 0 R >>"
            )
        )
    builder.add(
        f"<< /Type /Pages /Count {len(page_ids)} /Kids ["
        + " ".join(f"{page_id} 0 R" for page_id in page_ids)
        + "] >>"
    )
    catalog_id = builder.add(f"<< /Type /Catalog /Pages {pages_id} 0 R >>")
    output_path.write_bytes(builder.build(catalog_id))


def text_for_pdf(input_path: Path) -> str:
    suffix = input_path.suffix.lower()
    if suffix == ".hwpx":
        return extract_hwpx_text(input_path)
    if suffix == ".json":
        data = json.loads(read_text_file(input_path))
        return json.dumps(data, ensure_ascii=False, indent=2)
    return read_text_file(input_path)


def convert_text_to_pdf(input_path: Path, output_path: Path, original_name: str) -> None:
    text = text_for_pdf(input_path)
    make_text_pdf(text, output_path, Path(original_name).stem)


def zip_single_file(input_path: Path, output_path: Path, original_name: str) -> None:
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(input_path, arcname=original_name)


def clean_process_output(text: str) -> str:
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[-1200:] if text else "알 수 없는 변환 오류"


def limited_preexec(timeout: int):
    if resource is None or os.name != "posix":
        return None

    def apply_limits() -> None:
        cpu_seconds = max(1, timeout + 5)
        limits = [
            (resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 5)),
            (resource.RLIMIT_FSIZE, (MAX_OUTPUT_BYTES, MAX_OUTPUT_BYTES)),
            (resource.RLIMIT_NOFILE, (MAX_PROCESS_FILES, MAX_PROCESS_FILES)),
            (resource.RLIMIT_AS, (MAX_PROCESS_MEMORY_BYTES, MAX_PROCESS_MEMORY_BYTES)),
        ]
        if hasattr(resource, "RLIMIT_NPROC"):
            limits.append((resource.RLIMIT_NPROC, (MAX_PROCESS_COUNT, MAX_PROCESS_COUNT)))
        for limit_name, values in limits:
            try:
                resource.setrlimit(limit_name, values)
            except (OSError, ValueError):
                continue

    return apply_limits


def conversion_env(extra_env: dict | None = None) -> dict:
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", os.environ.get("LANG", "C.UTF-8")),
        "HOME": os.environ.get("HOME", str(DATA_DIR)),
    }
    if IMAGEMAGICK_POLICY_DIR.exists():
        existing = os.environ.get("MAGICK_CONFIGURE_PATH")
        env["MAGICK_CONFIGURE_PATH"] = (
            f"{IMAGEMAGICK_POLICY_DIR}{os.pathsep}{existing}" if existing else str(IMAGEMAGICK_POLICY_DIR)
        )
    if extra_env:
        env.update({key: str(value) for key, value in extra_env.items()})
    return env


def terminate_process_group(process: subprocess.Popen) -> None:
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
            return
        except ProcessLookupError:
            return
        except OSError:
            pass
    process.kill()


def docker_user_spec() -> str | None:
    if not hasattr(os, "getuid") or not hasattr(os, "getgid"):
        return None
    uid = os.getuid()
    gid = os.getgid()
    if uid == 0:
        return None
    return f"{uid}:{gid}"


def translate_command_paths(command: list[str], path_map: dict[Path, str] | None) -> list[str]:
    if not path_map:
        return command
    replacements = sorted(
        ((str(path.resolve()), target) for path, target in path_map.items()),
        key=lambda item: len(item[0]),
        reverse=True,
    )
    translated = []
    for arg in command:
        value = str(arg)
        for source, target in replacements:
            value = value.replace(source, target)
        translated.append(value)
    return translated


def docker_mount_args(mounts: list[tuple[Path, str, str]]) -> list[str]:
    args = []
    seen_targets = set()
    for source, target, mode in mounts:
        if target in seen_targets:
            continue
        seen_targets.add(target)
        readonly = ",readonly" if mode == "ro" else ""
        args.extend(
            [
                "--mount",
                f"type=bind,source={source.resolve()},target={target}{readonly}",
            ]
        )
    return args


def docker_wrapped_command(
    command: list[str],
    mounts: list[tuple[Path, str, str]],
    path_map: dict[Path, str] | None,
    extra_env: dict | None,
) -> list[str]:
    docker = local_tool_path("docker")
    if not docker:
        raise ConversionError("Docker worker 모드가 켜져 있지만 docker 실행 파일을 찾지 못했습니다.")

    docker_command = [
        docker,
        "run",
        "--rm",
        "--pull=never",
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges:true",
        "--pids-limit",
        str(MAX_PROCESS_COUNT),
        "--memory",
        str(MAX_PROCESS_MEMORY_BYTES),
        "--cpus",
        "1.0",
        "--tmpfs",
        " /tmp:rw,nosuid,nodev,noexec,size=256m".strip(),
        "--tmpfs",
        " /var/tmp:rw,nosuid,nodev,noexec,size=128m".strip(),
        "--workdir",
        "/work",
    ]
    user_spec = docker_user_spec()
    if user_spec:
        docker_command.extend(["--user", user_spec])

    docker_command.extend(docker_mount_args(mounts))

    container_env = {"HOME": "/tmp", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
    if IMAGEMAGICK_POLICY_DIR.exists():
        docker_command.extend(
            [
                "--mount",
                f"type=bind,source={IMAGEMAGICK_POLICY_DIR.resolve()},target=/etc/file-trans-imagemagick,readonly",
            ]
        )
        container_env["MAGICK_CONFIGURE_PATH"] = "/etc/file-trans-imagemagick"
    if extra_env:
        container_env.update({key: str(value) for key, value in extra_env.items()})
    for key, value in container_env.items():
        docker_command.extend(["--env", f"{key}={value}"])

    docker_command.append(CONVERT_WORKER_IMAGE)
    docker_command.extend(translate_command_paths(command, path_map))
    return docker_command


def run_checked(
    command: list[str],
    timeout: int = MAX_CONVERSION_SECONDS,
    cwd: Path | None = None,
    extra_env: dict | None = None,
    docker_mounts: list[tuple[Path, str, str]] | None = None,
    path_map: dict[Path, str] | None = None,
) -> subprocess.CompletedProcess:
    use_docker = USE_DOCKER_WORKER and docker_mounts is not None
    if use_docker:
        command = docker_wrapped_command(command, docker_mounts, path_map, extra_env)
        cwd = None
        extra_env = None
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
            cwd=str(cwd) if cwd else None,
            env=conversion_env(extra_env) if not use_docker else None,
            start_new_session=(os.name == "posix"),
            preexec_fn=None if use_docker else limited_preexec(timeout),
        )
    except FileNotFoundError as exc:
        raise ConversionError(f"실행 파일을 찾지 못했습니다: {command[0]}") from exc
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        terminate_process_group(process)
        stdout, stderr = process.communicate()
        raise ConversionError("변환 시간이 초과되었습니다.") from exc
    if process.returncode != 0:
        raise ConversionError(clean_process_output(stderr or stdout))
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def convert_with_ffmpeg(input_path: Path, output_path: Path, target: str) -> None:
    ffmpeg = tool_path("ffmpeg")
    if not ffmpeg:
        raise ConversionError("ffmpeg가 설치되어 있지 않습니다. scripts/install-ubuntu-deps.sh를 실행하세요.")

    command = [ffmpeg, "-nostdin", "-hide_banner", "-v", "error", "-y", "-i", str(input_path)]
    if target in AUDIO_TARGETS:
        command.extend(["-vn", "-map_metadata", "-1"])
        if target == "mp3":
            command.extend(["-codec:a", "libmp3lame", "-q:a", "2"])
        elif target == "wav":
            command.extend(["-codec:a", "pcm_s16le"])
        elif target == "flac":
            command.extend(["-codec:a", "flac"])
        elif target == "opus":
            command.extend(["-codec:a", "libopus"])
    elif target == "mp4":
        command.extend(["-c:v", "libx264", "-c:a", "aac", "-movflags", "+faststart"])
    elif target == "webm":
        command.extend(["-c:v", "libvpx-vp9", "-c:a", "libopus"])
    elif target == "gif":
        command.extend(["-vf", "fps=12,scale=960:-1:flags=lanczos"])
    command.append(str(output_path))
    run_checked(
        command,
        cwd=output_path.parent,
        docker_mounts=[(input_path.parent, "/input", "ro"), (output_path.parent, "/work", "rw")],
        path_map={input_path: f"/input/{input_path.name}", output_path: f"/work/{output_path.name}"},
    )


def convert_with_imagemagick(input_path: Path, output_path: Path) -> None:
    magick = tool_path("magick")
    limit_args = [
        "-limit",
        "time",
        str(MAX_CONVERSION_SECONDS),
        "-limit",
        "memory",
        "256MiB",
        "-limit",
        "map",
        "512MiB",
        "-limit",
        "disk",
        "1GiB",
        "-limit",
        "area",
        "128MP",
    ]
    if magick:
        command = [magick, *limit_args, str(input_path), str(output_path)]
    else:
        convert = tool_path("convert")
        if not convert:
            raise ConversionError("ImageMagick이 설치되어 있지 않습니다. scripts/install-ubuntu-deps.sh를 실행하세요.")
        command = [convert, *limit_args, str(input_path), str(output_path)]
    run_checked(
        command,
        cwd=output_path.parent,
        docker_mounts=[(input_path.parent, "/input", "ro"), (output_path.parent, "/work", "rw")],
        path_map={input_path: f"/input/{input_path.name}", output_path: f"/work/{output_path.name}"},
    )


def convert_pdf_to_image(input_path: Path, output_path: Path, target: str) -> None:
    pdftoppm = tool_path("pdftoppm")
    if not pdftoppm:
        raise ConversionError("poppler-utils가 설치되어 있지 않습니다. scripts/install-ubuntu-deps.sh를 실행하세요.")

    output_prefix = output_path.with_suffix("")
    command = [pdftoppm, "-singlefile", "-r", "160"]
    command.append("-jpeg" if target in {"jpg", "jpeg"} else "-png")
    command.extend([str(input_path), str(output_prefix)])
    run_checked(
        command,
        cwd=output_path.parent,
        docker_mounts=[(input_path.parent, "/input", "ro"), (output_path.parent, "/work", "rw")],
        path_map={
            input_path: f"/input/{input_path.name}",
            output_prefix: f"/work/{output_prefix.name}",
            output_path: f"/work/{output_path.name}",
        },
    )

    generated = output_prefix.with_suffix(".jpg" if target in {"jpg", "jpeg"} else ".png")
    if generated != output_path:
        generated.replace(output_path)


def convert_pdf_to_text(input_path: Path, output_path: Path) -> None:
    pdftotext = tool_path("pdftotext")
    if not pdftotext:
        raise ConversionError("poppler-utils가 설치되어 있지 않습니다. scripts/install-ubuntu-deps.sh를 실행하세요.")
    command = [pdftotext, "-enc", "UTF-8", "-layout", str(input_path), str(output_path)]
    run_checked(
        command,
        cwd=output_path.parent,
        docker_mounts=[(input_path.parent, "/input", "ro"), (output_path.parent, "/work", "rw")],
        path_map={input_path: f"/input/{input_path.name}", output_path: f"/work/{output_path.name}"},
    )


def convert_with_libreoffice(input_path: Path, output_path: Path, target: str) -> None:
    office = tool_path("libreoffice", "soffice")
    if not office:
        raise ConversionError("LibreOffice가 설치되어 있지 않습니다. scripts/install-ubuntu-deps.sh를 실행하세요.")

    outdir = output_path.parent
    profile_dir = outdir / ".libreoffice-profile"
    mkdir_private(profile_dir)
    command = [
        office,
        "--headless",
        "--nologo",
        "--nolockcheck",
        "--nodefault",
        "--nofirststartwizard",
        f"-env:UserInstallation=file://{profile_dir.resolve()}",
        "--convert-to",
        target,
        "--outdir",
        str(outdir),
        str(input_path),
    ]
    try:
        run_checked(
            command,
            timeout=max(MAX_CONVERSION_SECONDS, 90),
            cwd=outdir,
            extra_env={"HOME": str(profile_dir)},
            docker_mounts=[(input_path.parent, "/input", "ro"), (outdir, "/work", "rw")],
            path_map={input_path: f"/input/{input_path.name}", outdir: "/work", profile_dir: "/work/.libreoffice-profile"},
        )
        expected = outdir / f"{input_path.stem}.{target}"
        if not expected.exists():
            matches = sorted(outdir.glob(f"*.{target}"), key=lambda item: item.stat().st_mtime, reverse=True)
            if not matches:
                raise ConversionError("LibreOffice 변환 결과 파일을 찾지 못했습니다.")
            expected = matches[0]
        if expected != output_path:
            expected.replace(output_path)
    finally:
        remove_tree(profile_dir)


def convert_with_pandoc(input_path: Path, output_path: Path, target: str) -> None:
    pandoc = tool_path("pandoc")
    if not pandoc:
        raise ConversionError("pandoc이 설치되어 있지 않습니다. scripts/install-ubuntu-deps.sh를 실행하세요.")

    command = [
        pandoc,
        str(input_path),
        "--standalone",
        "--metadata",
        f"title={input_path.stem}",
        "-o",
        str(output_path),
    ]
    if target == "html":
        command.insert(2, "--embed-resources")
    run_checked(
        command,
        timeout=max(MAX_CONVERSION_SECONDS, 90),
        cwd=output_path.parent,
        docker_mounts=[(input_path.parent, "/input", "ro"), (output_path.parent, "/work", "rw")],
        path_map={input_path: f"/input/{input_path.name}", output_path: f"/work/{output_path.name}"},
    )


def convert_with_calibre(input_path: Path, output_path: Path) -> None:
    calibre = tool_path("ebook-convert")
    if not calibre:
        raise ConversionError("Calibre ebook-convert가 설치되어 있지 않습니다. scripts/install-ubuntu-deps.sh를 실행하세요.")

    profile_dir = output_path.parent / ".calibre-profile"
    mkdir_private(profile_dir)
    command = [
        calibre,
        str(input_path),
        str(output_path),
        "--disable-font-rescaling",
    ]
    try:
        run_checked(
            command,
            timeout=max(MAX_CONVERSION_SECONDS, 120),
            cwd=output_path.parent,
            extra_env={"HOME": str(profile_dir), "CALIBRE_CONFIG_DIRECTORY": str(profile_dir)},
            docker_mounts=[(input_path.parent, "/input", "ro"), (output_path.parent, "/work", "rw")],
            path_map={input_path: f"/input/{input_path.name}", output_path: f"/work/{output_path.name}", profile_dir: "/work/.calibre-profile"},
        )
    finally:
        remove_tree(profile_dir)


def convert_file(input_path: Path, original_name: str, target: str, job_output_dir: Path) -> Path:
    source_ext = input_path.suffix.lower().lstrip(".")
    target = target.lower().lstrip(".")
    if source_ext not in ALLOWED_INPUT_EXTS:
        raise ConversionError(f".{source_ext} 파일은 업로드 허용 목록에 없습니다.")
    if not EXT_RE.match(target) or target not in ALLOWED_TARGET_EXTS:
        raise ConversionError(f".{target} 출력 형식은 허용되지 않습니다.")
    allowed_targets = targets_for_extension(source_ext)
    if target not in allowed_targets:
        raise ConversionError(f".{source_ext} 파일은 .{target} 형식으로 변환할 수 없습니다.")

    output_name = f"{stem_for_output(original_name)}.{target}"
    output_path = job_output_dir / output_name

    if target == "zip":
        zip_single_file(input_path, output_path, original_name)
    elif source_ext == "csv" and target == "json":
        convert_csv_to_json(input_path, output_path)
    elif source_ext == "tsv" and target == "json":
        convert_tsv_to_json(input_path, output_path)
    elif source_ext == "ndjson" and target == "json":
        convert_ndjson_to_json(input_path, output_path)
    elif source_ext == "json" and target == "csv":
        convert_json_to_csv(input_path, output_path)
    elif source_ext == "json" and target == "tsv":
        convert_json_to_tsv(input_path, output_path)
    elif source_ext == "ndjson" and target == "csv":
        convert_ndjson_to_csv(input_path, output_path)
    elif source_ext == "ndjson" and target == "tsv":
        convert_ndjson_to_tsv(input_path, output_path)
    elif source_ext == "srt" and target == "vtt":
        convert_srt_to_vtt(input_path, output_path)
    elif source_ext == "vtt" and target == "srt":
        convert_vtt_to_srt(input_path, output_path)
    elif source_ext in (MARKUP_EXTS | {"html", "htm"}) and target in MARKUP_TARGETS and target not in {"html", "pdf"}:
        convert_with_pandoc(input_path, output_path, target)
    elif source_ext in EBOOK_EXTS and target in EBOOK_TARGETS:
        convert_with_calibre(input_path, output_path)
    elif source_ext in {"html", "htm", "md", "pdf", "rtf", "txt"} and target in {"azw3", "epub", "mobi"}:
        convert_with_calibre(input_path, output_path)
    elif target == "html" and source_ext in TEXT_EXTS:
        convert_text_to_html(input_path, output_path, original_name)
    elif target == "pdf" and source_ext in TEXT_EXTS:
        convert_text_to_pdf(input_path, output_path, original_name)
    elif target in AUDIO_TARGETS or (source_ext in VIDEO_EXTS and target in VIDEO_TARGETS):
        convert_with_ffmpeg(input_path, output_path, target)
    elif source_ext == "pdf" and target in PDF_IMAGE_TARGETS:
        convert_pdf_to_image(input_path, output_path, target)
    elif source_ext == "pdf" and target == "txt":
        convert_pdf_to_text(input_path, output_path)
    elif source_ext in IMAGE_EXTS:
        convert_with_imagemagick(input_path, output_path)
    elif target == "pdf" and source_ext in DOCUMENT_EXTS:
        convert_with_libreoffice(input_path, output_path, target)
    else:
        raise ConversionError(f".{source_ext} -> .{target} 변환 엔진이 아직 없습니다.")

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise ConversionError("변환 결과 파일이 생성되지 않았습니다.")
    return output_path


class FileTransHandler(BaseHTTPRequestHandler):
    server_version = "FileTrans/0.1"

    def log_message(self, fmt: str, *args) -> None:
        message = clean_process_output(fmt % args)
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {self.client_ip()} {message}")

    def client_ip(self) -> str:
        return self.client_address[0] if self.client_address else "unknown"

    def send_security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; object-src 'none'; frame-ancestors 'none'")

    def send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_security_headers()
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def send_error_json(self, message: str, status: HTTPStatus = HTTPStatus.BAD_REQUEST) -> None:
        self.send_json({"ok": False, "error": message}, status)

    def send_error(self, code, message=None, explain=None) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        status = HTTPStatus(code)
        text = message or status.phrase
        data = f"{status.value} {text}\n".encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_security_headers()
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        path = unquote(self.path.split("?", 1)[0])
        if path == "/api/capabilities":
            self.send_json({"ok": True, **capabilities()})
            return
        if path.startswith("/download/"):
            self.serve_download(path)
            return
        self.serve_static(path)

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/convert":
            self.handle_convert()
            return
        self.send_error_json("알 수 없는 POST 경로입니다.", HTTPStatus.NOT_FOUND)

    def serve_static(self, request_path: str) -> None:
        if request_path in {"", "/"}:
            request_path = "/index.html"
        relative = Path(request_path.lstrip("/"))
        if ".." in relative.parts:
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        file_path = PUBLIC_DIR / relative
        if not file_path.exists() or not file_path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
        data = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_security_headers()
        self.send_header("Cache-Control", "no-store" if file_path.name == "index.html" else "public, max-age=300")
        self.end_headers()
        self.wfile.write(data)

    def serve_download(self, request_path: str) -> None:
        parts = Path(request_path.lstrip("/")).parts
        if len(parts) < 4:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        _, job_id, token, *_name_parts = parts
        if not TOKEN_RE.match(token):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        metadata = load_download_metadata(job_id)
        if not metadata or not secrets.compare_digest(str(metadata.get("token", "")), token):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        filename = sanitize_filename(str(metadata.get("outputName", "download.bin")))
        file_path = OUTPUT_DIR / job_id / filename
        try:
            file_path.resolve().relative_to(OUTPUT_DIR.resolve())
        except ValueError:
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if not file_path.exists() or not file_path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if file_path.stat().st_size != int(metadata.get("outputSize", -1)):
            self.send_error(HTTPStatus.GONE)
            return
        with file_path.open("rb") as handle:
            current_sha256 = hashlib.file_digest(handle, "sha256").hexdigest()
        if not secrets.compare_digest(current_sha256, str(metadata.get("outputSha256", ""))):
            self.send_error(HTTPStatus.GONE)
            return
        content_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(file_path.stat().st_size))
        fallback_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", file_path.name) or "download"
        encoded_name = quote(file_path.name)
        self.send_header(
            "Content-Disposition",
            f"attachment; filename=\"{fallback_name}\"; filename*=UTF-8''{encoded_name}",
        )
        self.send_security_headers()
        self.send_header("Cache-Control", "private, max-age=0, no-store")
        self.end_headers()
        with file_path.open("rb") as handle:
            shutil.copyfileobj(handle, self.wfile, length=CHUNK_SIZE)

    def handle_convert(self) -> None:
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_error_json("Content-Length가 올바르지 않습니다.")
            return
        if content_length <= 0:
            self.send_error_json("업로드된 파일이 없습니다.")
            return
        if content_length > MAX_UPLOAD_BYTES:
            self.send_error_json("업로드 용량 제한을 초과했습니다.", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return
        if "multipart/form-data" not in self.headers.get("Content-Type", ""):
            self.send_error_json("multipart/form-data 요청만 지원합니다.")
            return
        if not rate_limiter.allow(self.client_ip()):
            self.send_error_json("요청이 너무 많습니다. 잠시 후 다시 시도하세요.", HTTPStatus.TOO_MANY_REQUESTS)
            return

        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={
                "REQUEST_METHOD": "POST",
                "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                "CONTENT_LENGTH": str(content_length),
            },
        )
        file_item = form["file"] if "file" in form else None
        if isinstance(file_item, list):
            file_item = file_item[0] if file_item else None
        target = (form.getfirst("target") or "").lower().strip()
        if file_item is None or not getattr(file_item, "filename", ""):
            self.send_error_json("파일을 선택하세요.")
            return
        if not target or not EXT_RE.match(target) or target not in ALLOWED_TARGET_EXTS:
            self.send_error_json("변환할 형식을 선택하세요.")
            return

        job_id = uuid.uuid4().hex
        job_upload_dir = UPLOAD_DIR / job_id
        job_output_dir = OUTPUT_DIR / job_id
        mkdir_private(job_upload_dir)
        mkdir_private(job_output_dir)

        original_name = sanitize_filename(file_item.filename)
        source_ext = Path(original_name).suffix.lower().lstrip(".")
        if not source_ext:
            remove_tree(job_upload_dir)
            remove_tree(job_output_dir)
            self.send_error_json("확장자가 있는 파일만 업로드할 수 있습니다.")
            return
        input_path = job_upload_dir / f"input.{source_ext}"

        error_message = None
        error_status = HTTPStatus.BAD_REQUEST
        output_path = None
        metadata = None
        try:
            size, digest = copy_stream_limited(file_item.file, input_path, MAX_UPLOAD_BYTES)
            source = validate_upload_file(input_path, original_name, size, digest)
            if target not in targets_for_extension(source.ext):
                raise ConversionError(f".{source.ext} 파일은 .{target} 형식으로 변환할 수 없습니다.")
            output_path = convert_file(input_path, original_name, target, job_output_dir)
            if output_path.stat().st_size > MAX_OUTPUT_BYTES:
                raise ConversionError("변환 결과 파일 크기가 제한을 초과했습니다.")
            metadata = create_download_metadata(job_id, output_path, original_name, source)
        except ConversionError as exc:
            remove_tree(job_output_dir)
            error_message = str(exc)
        except Exception as exc:
            remove_tree(job_output_dir)
            error_message = f"변환 중 오류가 발생했습니다: {exc}"
            error_status = HTTPStatus.INTERNAL_SERVER_ERROR
        finally:
            safe_unlink(input_path)
            remove_tree(job_upload_dir)

        if error_message:
            self.send_error_json(error_message, error_status)
            return
        if output_path is None or metadata is None:
            self.send_error_json("변환 결과를 확인하지 못했습니다.", HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        self.send_json(
            {
                "ok": True,
                "jobId": job_id,
                "outputName": output_path.name,
                "size": output_path.stat().st_size,
                "expiresAt": metadata["expiresAt"],
                "downloadUrl": f"/download/{job_id}/{metadata['token']}/{quote(output_path.name)}",
            }
        )


def main() -> None:
    ensure_dirs()
    server = ThreadingHTTPServer((HOST, PORT), FileTransHandler)
    print(f"FileTrans running at http://{HOST}:{PORT}")
    print("Tools:", json.dumps(installed_tools(), ensure_ascii=False))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
