import hashlib
import tempfile
import unittest
import zipfile
from pathlib import Path

import server


class SecurityValidationTests(unittest.TestCase):
    def test_fake_png_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fake.png"
            data = b"not a png\n"
            path.write_bytes(data)
            with self.assertRaises(server.ConversionError):
                server.validate_upload_file(path, "fake.png", len(data), hashlib.sha256(data).hexdigest())

    def test_zip_slip_member_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.docx"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("../evil.txt", "owned")
            with self.assertRaises(server.ConversionError):
                server.archive_names(path)

    def test_docx_zip_structure_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.docx"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("[Content_Types].xml", "<Types/>")
                archive.writestr("word/document.xml", "<document/>")
            data = path.read_bytes()
            result = server.validate_upload_file(path, "sample.docx", len(data), hashlib.sha256(data).hexdigest())
            self.assertEqual(result.detected, "docx")

    def test_ndjson_to_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "events.ndjson"
            output_path = Path(tmp) / "events.csv"
            input_path.write_text('{"name":"kim","score":10}\n{"name":"lee","score":20}\n', encoding="utf-8")
            server.convert_ndjson_to_csv(input_path, output_path)
            text = output_path.read_text(encoding="utf-8-sig")
            self.assertIn("name,score", text)
            self.assertIn("lee,20", text)

    def test_srt_to_vtt(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "caption.srt"
            output_path = Path(tmp) / "caption.vtt"
            input_path.write_text("1\n00:00:01,000 --> 00:00:02,000\nhello\n", encoding="utf-8")
            server.convert_srt_to_vtt(input_path, output_path)
            text = output_path.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("WEBVTT"))
            self.assertIn("00:00:01.000 --> 00:00:02.000", text)

    def test_format_counts_cover_public_requirement(self):
        capabilities = server.capabilities()
        self.assertGreaterEqual(capabilities["inputFormatCount"], 40)
        self.assertGreaterEqual(capabilities["targetFormatCount"], 20)


if __name__ == "__main__":
    unittest.main()
