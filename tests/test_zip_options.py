"""ZIP 압축 옵션 테스트."""

import io
import tempfile
import unittest
import zipfile
from pathlib import Path

import server


class ZipCompressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _make_file(self, name: str, content: bytes) -> tuple[Path, str]:
        path = self.tmp_dir / name
        path.write_bytes(content)
        return path, name

    def test_zip_single_file_uses_default_compression(self):
        source_path, original = self._make_file("a.txt", b"hello world " * 200)
        output_path = self.tmp_dir / "out.zip"
        server.zip_single_file(source_path, output_path, original)
        with zipfile.ZipFile(output_path) as archive:
            self.assertEqual(archive.namelist(), [original])
            self.assertEqual(archive.read(original), b"hello world " * 200)
            info = archive.getinfo(original)
            self.assertEqual(info.compress_type, zipfile.ZIP_DEFLATED)

    def test_zip_single_file_store_mode_skips_compression(self):
        source_path, original = self._make_file("a.txt", b"hello")
        output_path = self.tmp_dir / "out.zip"
        server.zip_single_file(source_path, output_path, original, level="store")
        with zipfile.ZipFile(output_path) as archive:
            info = archive.getinfo(original)
            self.assertEqual(info.compress_type, zipfile.ZIP_STORED)

    def test_zip_uploaded_files_supports_levels(self):
        path1, name1 = self._make_file("a.txt", b"alpha")
        path2, name2 = self._make_file("b.txt", b"beta")
        files = [
            server.UploadedFile(
                path=path1,
                original_name=name1,
                archive_name="a.txt",
                validation=server.FileValidation(ext="txt", detected="text", size=5, sha256="x"),
            ),
            server.UploadedFile(
                path=path2,
                original_name=name2,
                archive_name="b.txt",
                validation=server.FileValidation(ext="txt", detected="text", size=4, sha256="y"),
            ),
        ]
        for level in server.ZIP_COMPRESSION_OPTIONS:
            output_path = self.tmp_dir / f"out-{level}.zip"
            server.zip_uploaded_files(files, output_path, level=level)
            with zipfile.ZipFile(output_path) as archive:
                expected_type = server.ZIP_COMPRESSION_OPTIONS[level][0]
                for member in archive.infolist():
                    self.assertEqual(member.compress_type, expected_type)
                self.assertEqual(
                    sorted(archive.namelist()),
                    ["a.txt", "b.txt"],
                )

    def test_invalid_level_falls_back_to_default(self):
        source_path, original = self._make_file("a.txt", b"hello")
        output_path = self.tmp_dir / "out.zip"
        server.zip_single_file(source_path, output_path, original, level="not-a-level")
        with zipfile.ZipFile(output_path) as archive:
            info = archive.getinfo(original)
            self.assertEqual(info.compress_type, zipfile.ZIP_DEFLATED)


class ConversionOptionParserTests(unittest.TestCase):
    def test_parse_quality_clamps_range(self):
        self.assertEqual(server.parse_quality("10"), 10)
        self.assertEqual(server.parse_quality("200"), 100)
        self.assertEqual(server.parse_quality("-5"), 1)
        self.assertEqual(server.parse_quality(None), 85)
        self.assertEqual(server.parse_quality("not-a-number"), 85)

    def test_parse_dpi_clamps_range(self):
        self.assertEqual(server.parse_dpi("100"), 100)
        self.assertEqual(server.parse_dpi("1000"), 600)
        self.assertEqual(server.parse_dpi("10"), 50)
        self.assertEqual(server.parse_dpi(None, default=160), 160)

    def test_parse_audio_bitrate_uses_presets_and_values(self):
        self.assertEqual(server.parse_audio_bitrate("low"), 96)
        self.assertEqual(server.parse_audio_bitrate("normal"), 192)
        self.assertEqual(server.parse_audio_bitrate("high"), 320)
        self.assertEqual(server.parse_audio_bitrate("128"), 128)
        self.assertEqual(server.parse_audio_bitrate("128k"), 128)
        self.assertEqual(server.parse_audio_bitrate("999"), 320)
        self.assertEqual(server.parse_audio_bitrate("10"), 32)
        self.assertEqual(server.parse_audio_bitrate(None), 192)

    def test_parse_video_quality_normalizes(self):
        self.assertEqual(server.parse_video_quality("HIGH"), "high")
        self.assertEqual(server.parse_video_quality("bogus"), "normal")
        self.assertEqual(server.parse_video_quality(None), "normal")


class CapabilitiesExposesOptionsTests(unittest.TestCase):
    def test_options_block_lists_allowed_values(self):
        caps = server.capabilities()
        opts = caps["options"]
        self.assertEqual(sorted(opts["zipLevels"]), sorted(server.ALLOWED_ZIP_LEVELS))
        self.assertIn("normal", opts["zipLevels"])
        self.assertIn("high", opts["videoQualities"])
        self.assertIn("normal", opts["audioBitrates"])
        self.assertIn("a4", opts["pdfPageSizes"])
        self.assertEqual(opts["pdfDpi"]["default"], server.DEFAULT_PDF_DPI)


class ImagePdfGeometryTests(unittest.TestCase):
    def test_fit_returns_none(self):
        self.assertIsNone(server.image_pdf_geometry("fit", "auto", "none"))

    def test_a4_portrait_no_margin(self):
        width, height, margin = server.image_pdf_geometry("a4", "portrait", "none")
        self.assertEqual(width, 1240)
        self.assertEqual(height, 1754)
        self.assertEqual(margin, 0)

    def test_a4_landscape_swaps_dimensions(self):
        width, height, _ = server.image_pdf_geometry("a4", "landscape", "none")
        self.assertEqual(width, 1754)
        self.assertEqual(height, 1240)

    def test_legal_with_large_margin(self):
        width, height, margin = server.image_pdf_geometry("legal", "portrait", "large")
        self.assertEqual(width, 1275)
        self.assertEqual(height, 2100)
        self.assertEqual(margin, 72)

    def test_a5_dimensions(self):
        width, height, _ = server.image_pdf_geometry("a5", "portrait", "none")
        self.assertEqual(width, 874)
        self.assertEqual(height, 1240)

    def test_unknown_size_falls_back_to_a4(self):
        width, height, _ = server.image_pdf_geometry("bogus", "portrait", "none")
        self.assertEqual((width, height), (1240, 1754))


if __name__ == "__main__":
    unittest.main()
