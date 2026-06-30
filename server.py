#!/usr/bin/env python3
import csv
import html
import json
import mimetypes
import os
import re
import shutil
import struct
import subprocess
import time
import unicodedata
import uuid
import warnings
import zipfile
from http import HTTPStatus
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import quote, unquote
from xml.etree import ElementTree

warnings.filterwarnings("ignore", category=DeprecationWarning, message="'cgi' is deprecated.*")
import cgi


ROOT = Path(__file__).resolve().parent
PUBLIC_DIR = ROOT / "public"
DATA_DIR = ROOT / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
OUTPUT_DIR = DATA_DIR / "outputs"
BUILD_DIR = ROOT / "build"
MAX_UPLOAD_BYTES = int(os.environ.get("FILE_TRANS_MAX_UPLOAD", str(512 * 1024 * 1024)))
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8000"))

DOCUMENT_EXTS = {
    "doc",
    "docx",
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
TEXT_EXTS = {"txt", "md", "csv", "json", "xml", "log", "srt", "vtt", "hwpx"}
VIDEO_EXTS = {"mp4", "mov", "mkv", "avi", "webm", "m4v", "flv", "wmv"}
AUDIO_EXTS = {"mp3", "wav", "aac", "m4a", "ogg", "flac", "opus", "wma"}
IMAGE_EXTS = {"jpg", "jpeg", "png", "webp", "gif", "bmp", "tif", "tiff", "heic", "avif"}

AUDIO_TARGETS = {"mp3", "wav", "aac", "m4a", "ogg", "flac", "opus"}
VIDEO_TARGETS = {"mp4", "webm", "mov", "mkv", "gif"}
IMAGE_TARGETS = {"jpg", "jpeg", "png", "webp", "gif", "bmp", "tiff", "pdf"}
PDF_IMAGE_TARGETS = {"jpg", "jpeg", "png"}


class ConversionError(Exception):
    pass


def ensure_dirs() -> None:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def sanitize_filename(name: str) -> str:
    name = Path(name or "upload.bin").name
    name = re.sub(r"[^\w.\-가-힣()\[\] ]+", "_", name, flags=re.UNICODE).strip()
    return name or "upload.bin"


def stem_for_output(original_name: str) -> str:
    stem = Path(original_name).stem
    stem = re.sub(r"[^\w.\-가-힣()\[\] ]+", "_", stem, flags=re.UNICODE).strip()
    return stem or "converted"


def tool_path(*names: str) -> str | None:
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return None


def installed_tools() -> dict:
    return {
        "ffmpeg": tool_path("ffmpeg"),
        "libreoffice": tool_path("libreoffice", "soffice"),
        "imagemagick": tool_path("magick", "convert"),
        "g++": tool_path("g++"),
        "java": tool_path("javac"),
        "rust": tool_path("rustc"),
        "csharp": tool_path("dotnet", "mcs", "csc"),
    }


def built_helpers() -> dict:
    helpers = {
        "cpp_probe": BUILD_DIR / "tools" / "fileprobe-cpp",
        "rust_probe": BUILD_DIR / "tools" / "fileprobe-rust",
        "java_probe": BUILD_DIR / "tools" / "java" / "FileProbe.class",
        "csharp_probe": BUILD_DIR / "tools" / "fileprobe-cs.exe",
    }
    return {name: str(path) if path.exists() else None for name, path in helpers.items()}


def operations() -> list[dict]:
    tools = installed_tools()
    has_ffmpeg = bool(tools["ffmpeg"])
    has_office = bool(tools["libreoffice"])
    has_image = bool(tools["imagemagick"])

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
            "available": bool(tool_path("pdftoppm")),
        },
        {
            "id": "csv-json",
            "label": "CSV -> JSON",
            "from": ["csv"],
            "to": ["json"],
            "engine": "python",
            "available": True,
        },
        {
            "id": "json-csv",
            "label": "JSON -> CSV",
            "from": ["json"],
            "to": ["csv"],
            "engine": "python",
            "available": True,
        },
        {
            "id": "text-html",
            "label": "텍스트/Markdown/HWPX -> HTML",
            "from": sorted(TEXT_EXTS),
            "to": ["html"],
            "engine": "python",
            "available": True,
        },
        {
            "id": "text-pdf",
            "label": "텍스트/HWPX -> PDF",
            "from": sorted(TEXT_EXTS),
            "to": ["pdf"],
            "engine": "python",
            "available": True,
        },
        {
            "id": "zip",
            "label": "파일 -> ZIP",
            "from": ["*"],
            "to": ["zip"],
            "engine": "python",
            "available": True,
        },
    ]
    return ops


def targets_for_extension(ext: str) -> list[str]:
    ext = ext.lower().lstrip(".")
    targets = set()
    for op in operations():
        if "*" in op["from"] or ext in op["from"]:
            targets.update(op["to"])
    targets.discard(ext)
    return sorted(targets)


def capabilities() -> dict:
    return {
        "tools": installed_tools(),
        "helpers": built_helpers(),
        "operations": operations(),
        "maxUploadBytes": MAX_UPLOAD_BYTES,
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


def convert_csv_to_json(input_path: Path, output_path: Path) -> None:
    text = read_text_file(input_path)
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample)
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.DictReader(text.splitlines(), dialect=dialect))
    write_json(output_path, rows)


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


def convert_json_to_csv(input_path: Path, output_path: Path) -> None:
    data = json.loads(read_text_file(input_path))
    rows, fieldnames = normalize_json_records(data)
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def extract_hwpx_text(path: Path) -> str:
    paragraphs: list[str] = []
    try:
        with zipfile.ZipFile(path) as archive:
            xml_names = [
                name
                for name in archive.namelist()
                if name.lower().startswith("contents/section") and name.lower().endswith(".xml")
            ]
            if not xml_names:
                xml_names = [name for name in archive.namelist() if name.lower().endswith(".xml")]
            for name in sorted(xml_names):
                root = ElementTree.fromstring(archive.read(name))
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
                    root = ElementTree.fromstring(archive.read(name))
                    paragraphs.extend(
                        element.text
                        for element in root.iter()
                        if local_name(element.tag) in {"t", "text"} and element.text
                    )
    except (zipfile.BadZipFile, ElementTree.ParseError) as exc:
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


def run_checked(command: list[str], timeout: int = 900) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise ConversionError(f"실행 파일을 찾지 못했습니다: {command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ConversionError("변환 시간이 초과되었습니다.") from exc
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "알 수 없는 변환 오류").strip()
        raise ConversionError(message[-1200:])
    return result


def convert_with_ffmpeg(input_path: Path, output_path: Path, target: str) -> None:
    ffmpeg = tool_path("ffmpeg")
    if not ffmpeg:
        raise ConversionError("ffmpeg가 설치되어 있지 않습니다. scripts/install-ubuntu-deps.sh를 실행하세요.")

    command = [ffmpeg, "-y", "-i", str(input_path)]
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
    run_checked(command)


def convert_with_imagemagick(input_path: Path, output_path: Path) -> None:
    magick = tool_path("magick")
    if magick:
        command = [magick, str(input_path), str(output_path)]
    else:
        convert = tool_path("convert")
        if not convert:
            raise ConversionError("ImageMagick이 설치되어 있지 않습니다. scripts/install-ubuntu-deps.sh를 실행하세요.")
        command = [convert, str(input_path), str(output_path)]
    run_checked(command)


def convert_pdf_to_image(input_path: Path, output_path: Path, target: str) -> None:
    pdftoppm = tool_path("pdftoppm")
    if not pdftoppm:
        raise ConversionError("poppler-utils가 설치되어 있지 않습니다. scripts/install-ubuntu-deps.sh를 실행하세요.")

    output_prefix = output_path.with_suffix("")
    command = [pdftoppm, "-singlefile", "-r", "160"]
    command.append("-jpeg" if target in {"jpg", "jpeg"} else "-png")
    command.extend([str(input_path), str(output_prefix)])
    run_checked(command)

    generated = output_prefix.with_suffix(".jpg" if target in {"jpg", "jpeg"} else ".png")
    if generated != output_path:
        generated.replace(output_path)


def convert_with_libreoffice(input_path: Path, output_path: Path, target: str) -> None:
    office = tool_path("libreoffice", "soffice")
    if not office:
        raise ConversionError("LibreOffice가 설치되어 있지 않습니다. scripts/install-ubuntu-deps.sh를 실행하세요.")

    outdir = output_path.parent
    command = [
        office,
        "--headless",
        "--convert-to",
        target,
        "--outdir",
        str(outdir),
        str(input_path),
    ]
    run_checked(command)
    expected = outdir / f"{input_path.stem}.{target}"
    if not expected.exists():
        matches = sorted(outdir.glob(f"*.{target}"), key=lambda item: item.stat().st_mtime, reverse=True)
        if not matches:
            raise ConversionError("LibreOffice 변환 결과 파일을 찾지 못했습니다.")
        expected = matches[0]
    if expected != output_path:
        expected.replace(output_path)


def convert_file(input_path: Path, original_name: str, target: str, job_output_dir: Path) -> Path:
    source_ext = input_path.suffix.lower().lstrip(".")
    target = target.lower().lstrip(".")
    allowed_targets = targets_for_extension(source_ext)
    if target not in allowed_targets:
        raise ConversionError(f".{source_ext} 파일은 .{target} 형식으로 변환할 수 없습니다.")

    output_name = f"{stem_for_output(original_name)}.{target}"
    output_path = job_output_dir / output_name

    if target == "zip":
        zip_single_file(input_path, output_path, original_name)
    elif source_ext == "csv" and target == "json":
        convert_csv_to_json(input_path, output_path)
    elif source_ext == "json" and target == "csv":
        convert_json_to_csv(input_path, output_path)
    elif target == "html" and source_ext in TEXT_EXTS:
        convert_text_to_html(input_path, output_path, original_name)
    elif target == "pdf" and source_ext in TEXT_EXTS:
        convert_text_to_pdf(input_path, output_path, original_name)
    elif target in AUDIO_TARGETS or (source_ext in VIDEO_EXTS and target in VIDEO_TARGETS):
        convert_with_ffmpeg(input_path, output_path, target)
    elif source_ext == "pdf" and target in PDF_IMAGE_TARGETS:
        convert_pdf_to_image(input_path, output_path, target)
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
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {self.address_string()} {fmt % args}")

    def send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_error_json(self, message: str, status: HTTPStatus = HTTPStatus.BAD_REQUEST) -> None:
        self.send_json({"ok": False, "error": message}, status)

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
        self.end_headers()
        self.wfile.write(data)

    def serve_download(self, request_path: str) -> None:
        parts = Path(request_path.lstrip("/")).parts
        if len(parts) < 3:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        _, job_id, *name_parts = parts
        filename = sanitize_filename("/".join(name_parts))
        file_path = OUTPUT_DIR / job_id / filename
        try:
            file_path.resolve().relative_to(OUTPUT_DIR.resolve())
        except ValueError:
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if not file_path.exists() or not file_path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
        data = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        fallback_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", file_path.name) or "download"
        encoded_name = quote(file_path.name)
        self.send_header(
            "Content-Disposition",
            f"attachment; filename=\"{fallback_name}\"; filename*=UTF-8''{encoded_name}",
        )
        self.end_headers()
        self.wfile.write(data)

    def handle_convert(self) -> None:
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0:
            self.send_error_json("업로드된 파일이 없습니다.")
            return
        if content_length > MAX_UPLOAD_BYTES:
            self.send_error_json("업로드 용량 제한을 초과했습니다.", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return
        if "multipart/form-data" not in self.headers.get("Content-Type", ""):
            self.send_error_json("multipart/form-data 요청만 지원합니다.")
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
        target = (form.getfirst("target") or "").lower().strip()
        if file_item is None or not getattr(file_item, "filename", ""):
            self.send_error_json("파일을 선택하세요.")
            return
        if not target:
            self.send_error_json("변환할 형식을 선택하세요.")
            return

        job_id = uuid.uuid4().hex
        job_upload_dir = UPLOAD_DIR / job_id
        job_output_dir = OUTPUT_DIR / job_id
        job_upload_dir.mkdir(parents=True, exist_ok=True)
        job_output_dir.mkdir(parents=True, exist_ok=True)

        original_name = sanitize_filename(file_item.filename)
        input_path = job_upload_dir / original_name
        with input_path.open("wb") as handle:
            shutil.copyfileobj(file_item.file, handle)

        try:
            output_path = convert_file(input_path, original_name, target, job_output_dir)
        except ConversionError as exc:
            self.send_error_json(str(exc))
            return
        except Exception as exc:
            self.send_error_json(f"변환 중 오류가 발생했습니다: {exc}", HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        self.send_json(
            {
                "ok": True,
                "jobId": job_id,
                "outputName": output_path.name,
                "size": output_path.stat().st_size,
                "downloadUrl": f"/download/{job_id}/{output_path.name}",
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
