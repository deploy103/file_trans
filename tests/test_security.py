import hashlib
import os
import stat
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

import server


class SecurityValidationTests(unittest.TestCase):
    def test_rate_limiter_enforces_window_limit(self):
        limiter = server.UploadRateLimiter(window_seconds=60, max_uploads=2)
        self.assertTrue(limiter.allow("127.0.0.1"))
        self.assertTrue(limiter.allow("127.0.0.1"))
        self.assertFalse(limiter.allow("127.0.0.1"))

    def test_rate_limiter_can_be_disabled(self):
        limiter = server.UploadRateLimiter(window_seconds=60, max_uploads=0)
        for _ in range(5):
            self.assertTrue(limiter.allow("127.0.0.1"))

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

    def test_zip_symlink_member_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "symlink.docx"
            link = zipfile.ZipInfo("word/link")
            link.external_attr = (stat.S_IFLNK | 0o777) << 16
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("[Content_Types].xml", "<Types/>")
                archive.writestr("word/document.xml", "<document/>")
                archive.writestr(link, "document.xml")
            with self.assertRaises(server.ConversionError):
                server.archive_names(path)

    def test_archive_member_count_limit_is_enforced(self):
        previous = server.MAX_ARCHIVE_MEMBERS
        server.MAX_ARCHIVE_MEMBERS = 1
        try:
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "many.docx"
                with zipfile.ZipFile(path, "w") as archive:
                    archive.writestr("word/document.xml", "<document/>")
                    archive.writestr("word/extra.xml", "<extra/>")
                with self.assertRaises(server.ConversionError):
                    server.archive_names(path)
        finally:
            server.MAX_ARCHIVE_MEMBERS = previous

    def test_archive_uncompressed_size_limit_is_enforced(self):
        previous = server.MAX_ARCHIVE_UNCOMPRESSED_BYTES
        server.MAX_ARCHIVE_UNCOMPRESSED_BYTES = 1
        try:
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "large.docx"
                with zipfile.ZipFile(path, "w") as archive:
                    archive.writestr("word/document.xml", "xx")
                with self.assertRaises(server.ConversionError):
                    server.archive_names(path)
        finally:
            server.MAX_ARCHIVE_UNCOMPRESSED_BYTES = previous

    def test_docx_zip_structure_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.docx"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("[Content_Types].xml", "<Types/>")
                archive.writestr("word/document.xml", "<document/>")
            data = path.read_bytes()
            result = server.validate_upload_file(path, "sample.docx", len(data), hashlib.sha256(data).hexdigest())
            self.assertEqual(result.detected, "docx")

    def test_docx_external_relationship_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "remote.docx"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("[Content_Types].xml", "<Types/>")
                archive.writestr("word/document.xml", "<document/>")
                archive.writestr(
                    "word/_rels/document.xml.rels",
                    '<Relationship Target="http://169.254.169.254/latest/meta-data/" TargetMode="External"/>',
                )
            data = path.read_bytes()
            with self.assertRaises(server.ConversionError):
                server.validate_upload_file(path, "remote.docx", len(data), hashlib.sha256(data).hexdigest())

    def test_html_external_reference_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "remote.html"
            text = '<!doctype html><img src="http://169.254.169.254/latest/meta-data/">'
            data = text.encode("utf-8")
            path.write_bytes(data)
            with self.assertRaises(server.ConversionError):
                server.validate_upload_file(path, "remote.html", len(data), hashlib.sha256(data).hexdigest())

    def test_markdown_external_reference_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "remote.md"
            text = "![x](file:///etc/passwd)\n"
            data = text.encode("utf-8")
            path.write_bytes(data)
            with self.assertRaises(server.ConversionError):
                server.validate_upload_file(path, "remote.md", len(data), hashlib.sha256(data).hexdigest())

    def test_late_markdown_external_reference_is_rejected(self):
        text = ("a" * (1024 * 1024 + 16)) + "\n[x]: http://169.254.169.254/latest/meta-data/\n"
        self.assertTrue(server.text_has_external_reference(text))

    def test_flat_open_document_external_reference_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "remote.fodt"
            text = (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<office:document><draw:image xlink:href="http://169.254.169.254/latest/meta-data/"/>'
                "</office:document>"
            )
            data = text.encode("utf-8")
            path.write_bytes(data)
            with self.assertRaises(server.ConversionError):
                server.validate_upload_file(path, "remote.fodt", len(data), hashlib.sha256(data).hexdigest())

    def test_xml_dtd_or_entity_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "entity.fodt"
            text = '<?xml version="1.0"?><!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><foo/>'
            data = text.encode("utf-8")
            path.write_bytes(data)
            with self.assertRaisesRegex(server.ConversionError, "DTD 또는 ENTITY"):
                server.validate_upload_file(path, "entity.fodt", len(data), hashlib.sha256(data).hexdigest())

    def test_markup_external_reference_patterns(self):
        samples = [
            ".. image:: http://169.254.169.254/latest/meta-data/\n",
            "[[file:///etc/passwd]]\n",
            "\\href{https://example.test/file}{x}",
            'image("https://example.test/file")',
            "<https://example.test/file>",
            "[ref]: https://example.test/file",
        ]
        for sample in samples:
            with self.subTest(sample=sample):
                self.assertTrue(server.text_has_external_reference(sample))

    def test_ndjson_to_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "events.ndjson"
            output_path = Path(tmp) / "events.csv"
            input_path.write_text('{"name":"kim","score":10}\n{"name":"lee","score":20}\n', encoding="utf-8")
            server.convert_ndjson_to_csv(input_path, output_path)
            text = output_path.read_text(encoding="utf-8-sig")
            self.assertIn("name,score", text)
            self.assertIn("lee,20", text)

    def test_ndjson_record_limit_is_enforced(self):
        previous = server.MAX_DATA_RECORDS
        server.MAX_DATA_RECORDS = 1
        try:
            with tempfile.TemporaryDirectory() as tmp:
                input_path = Path(tmp) / "events.ndjson"
                input_path.write_text('{"a":1}\n{"a":2}\n', encoding="utf-8")
                with self.assertRaises(server.ConversionError):
                    server.read_ndjson(input_path)
        finally:
            server.MAX_DATA_RECORDS = previous

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
        self.assertGreaterEqual(capabilities["maxFilenameChars"], 1)
        self.assertGreaterEqual(capabilities["maxConcurrentConversions"], 1)
        self.assertGreaterEqual(capabilities["requestTimeoutSeconds"], 1)
        self.assertGreaterEqual(capabilities["maxMultipartOverheadBytes"], 0)
        self.assertGreaterEqual(capabilities["maxOutputBytes"], 1)
        self.assertGreaterEqual(capabilities["maxProcessMemoryBytes"], 1)
        self.assertGreaterEqual(capabilities["maxProcessFiles"], 1)
        self.assertGreaterEqual(capabilities["maxProcessCount"], 1)
        self.assertGreaterEqual(capabilities["maxDataRecords"], 1)
        self.assertGreaterEqual(capabilities["maxArchiveMembers"], 1)
        self.assertGreaterEqual(capabilities["maxArchiveUncompressedBytes"], 1)
        self.assertGreaterEqual(capabilities["cleanupIntervalSeconds"], 1)
        self.assertGreaterEqual(capabilities["maxReferenceScanBytes"], 1)
        self.assertIn("malwareScanEnabled", capabilities)
        self.assertIn("malwareScanAvailable", capabilities)
        self.assertGreaterEqual(capabilities["malwareScanTimeoutSeconds"], 1)
        self.assertIn("hwpFilterAvailable", capabilities)

    def test_compilers_are_not_exposed_as_conversion_tools(self):
        capabilities = server.capabilities()
        exposed_tools = set(capabilities["tools"])
        self.assertFalse(exposed_tools & {"g++", "java", "rust", "csharp"})
        self.assertNotIn("helpers", capabilities)

    def test_hwp_pdf_requires_hwp_filter_marker(self):
        previous_marker = server.HWP_FILTER_MARKER
        try:
            with tempfile.TemporaryDirectory() as tmp:
                server.HWP_FILTER_MARKER = Path(tmp) / "missing-h2orestart.jar"
                self.assertFalse(server.hwp_filter_available())
                self.assertNotIn("pdf", server.targets_for_extension("hwp"))
                self.assertIn("zip", server.targets_for_extension("hwp"))
        finally:
            server.HWP_FILTER_MARKER = previous_marker

    def test_http_server_uses_restart_friendly_defaults(self):
        self.assertTrue(server.FileTransServer.daemon_threads)
        self.assertTrue(server.FileTransServer.allow_reuse_address)

    def test_same_origin_post_is_allowed(self):
        self.assertTrue(server.request_origin_allowed("http://127.0.0.1:8000", "127.0.0.1:8000"))
        self.assertTrue(server.request_origin_allowed(None, "127.0.0.1:8000"))

    def test_configured_frontend_origin_is_allowed(self):
        previous = server.ALLOWED_ORIGINS
        server.ALLOWED_ORIGINS = {"http://127.0.0.1:4762"}
        try:
            self.assertTrue(server.request_origin_allowed("http://127.0.0.1:4762", "127.0.0.1:8766"))
            self.assertEqual(
                server.parse_allowed_origins("http://127.0.0.1:4762/, https://example.test/path"),
                {"http://127.0.0.1:4762", "https://example.test"},
            )
        finally:
            server.ALLOWED_ORIGINS = previous

    def test_cross_origin_post_is_rejected(self):
        self.assertFalse(server.request_origin_allowed("https://example.test", "127.0.0.1:8000"))
        self.assertFalse(server.request_origin_allowed("null", "127.0.0.1:8000"))
        self.assertFalse(server.request_origin_allowed(None, "127.0.0.1:8000", "cross-site"))

    def test_clamscan_infected_result_is_rejected(self):
        with self.assertRaises(server.ConversionError):
            server.raise_for_clamscan_result(1, "Eicar-Test-Signature FOUND")

    def test_clamscan_engine_error_is_sanitized(self):
        with self.assertRaisesRegex(server.ConversionError, "악성코드 검사가 실패했습니다"):
            server.raise_for_clamscan_result(2, "failed\x00with\nerror")

    def test_clamscan_disabled_is_noop(self):
        previous = server.ENABLE_CLAMSCAN
        server.ENABLE_CLAMSCAN = False
        try:
            server.scan_upload_for_malware(Path("does-not-need-to-exist"))
        finally:
            server.ENABLE_CLAMSCAN = previous

    def test_conversion_environment_uses_safe_path(self):
        previous = server.CONVERSION_PATH
        server.CONVERSION_PATH = "/usr/bin:/bin"
        try:
            env = server.conversion_env()
            self.assertEqual(env["PATH"], "/usr/bin:/bin")
            self.assertNotIn(os.getcwd(), env["PATH"].split(os.pathsep))
            self.assertNotIn(".", env["PATH"].split(os.pathsep))
        finally:
            server.CONVERSION_PATH = previous

    def test_conversion_path_ignores_relative_entries(self):
        value = os.pathsep.join([".", "relative/bin", "/usr/bin", "/bin", "/usr/bin", ""])
        self.assertEqual(server.normalize_conversion_path(value), "/usr/bin:/bin")

    def test_download_tokens_are_redacted_from_logs(self):
        text = (
            '"GET /download/0123456789abcdef0123456789abcdef/'
            'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMN0123456789_a/file.txt HTTP/1.1" 200 -'
        )
        redacted = server.redact_log_text(text)
        self.assertIn("/download/0123456789abcdef0123456789abcdef/<token>/file.txt", redacted)
        self.assertNotIn("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMN0123456789_a", redacted)

    def test_filename_is_sanitized_and_limited(self):
        previous = server.MAX_FILENAME_CHARS
        server.MAX_FILENAME_CHARS = 16
        try:
            name = server.sanitize_filename("../bad<script>" + ("a" * 40) + ".txt")
            self.assertLessEqual(len(name), 16)
            self.assertTrue(name.endswith(".txt"))
            self.assertNotIn("<", name)
            self.assertNotIn(">", name)
        finally:
            server.MAX_FILENAME_CHARS = previous

    def test_tiny_filename_limit_is_still_enforced(self):
        previous = server.MAX_FILENAME_CHARS
        server.MAX_FILENAME_CHARS = 3
        try:
            name = server.sanitize_filename("abcdef.txt")
            self.assertLessEqual(len(name), 3)
        finally:
            server.MAX_FILENAME_CHARS = previous

    def test_download_metadata_does_not_store_original_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "secret-contract.txt"
            output_path.write_text("result", encoding="utf-8")
            source = server.FileValidation(ext="txt", detected="text", size=6, sha256=hashlib.sha256(b"source").hexdigest())
            metadata = server.create_download_metadata("0" * 32, output_path, source)
            self.assertNotIn("originalName", metadata)
            self.assertEqual(metadata["outputName"], "secret-contract.txt")
            self.assertEqual(metadata["outputSize"], len("result"))
            self.assertEqual(metadata["outputSha256"], hashlib.sha256(b"result").hexdigest())

    def test_cleanup_removes_expired_output_jobs(self):
        previous_output_dir = server.OUTPUT_DIR
        try:
            with tempfile.TemporaryDirectory() as tmp:
                output_dir = Path(tmp) / "outputs"
                job_dir = output_dir / ("a" * 32)
                job_dir.mkdir(parents=True)
                (job_dir / "result.txt").write_text("old", encoding="utf-8")
                server.write_json(job_dir / ".job.json", {"expiresAt": 0})
                server.OUTPUT_DIR = output_dir
                server.cleanup_expired_jobs()
                self.assertFalse(job_dir.exists())
        finally:
            server.OUTPUT_DIR = previous_output_dir

    def test_maybe_cleanup_removes_expired_output_jobs(self):
        previous_output_dir = server.OUTPUT_DIR
        previous_last_cleanup = server.last_cleanup_at
        try:
            with tempfile.TemporaryDirectory() as tmp:
                output_dir = Path(tmp) / "outputs"
                job_dir = output_dir / ("b" * 32)
                job_dir.mkdir(parents=True)
                (job_dir / "result.txt").write_text("old", encoding="utf-8")
                server.write_json(job_dir / ".job.json", {"expiresAt": 0})
                server.OUTPUT_DIR = output_dir
                server.last_cleanup_at = time.monotonic() - server.CLEANUP_INTERVAL_SECONDS - 1
                server.maybe_cleanup_expired_jobs()
                self.assertFalse(job_dir.exists())
        finally:
            server.OUTPUT_DIR = previous_output_dir
            server.last_cleanup_at = previous_last_cleanup

    def test_static_symlink_escape_is_rejected(self):
        previous_public_dir = server.PUBLIC_DIR
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                public_dir = root / "public"
                public_dir.mkdir()
                secret_path = root / "secret.txt"
                secret_path.write_text("secret", encoding="utf-8")
                link_path = public_dir / "secret.txt"
                try:
                    os.symlink(secret_path, link_path)
                except (OSError, NotImplementedError) as exc:
                    self.skipTest(f"symlink unavailable: {exc}")
                server.PUBLIC_DIR = public_dir
                self.assertIsNone(server.safe_public_file_path("/secret.txt"))
        finally:
            server.PUBLIC_DIR = previous_public_dir


if __name__ == "__main__":
    unittest.main()
