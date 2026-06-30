"""cgi 모듈 제거 대비용으로 추가한 MultipartForm 파서 테스트."""

import io
import unittest

import server


class FakeStream:
    """BytesIO 와 동일한 read 인터페이스만 가진 더미."""

    def __init__(self, data: bytes):
        self._buffer = io.BytesIO(data)

    def read(self, size: int = -1) -> bytes:
        return self._buffer.read(size)


def build_body(parts: list[tuple[str, str | None, bytes | str]], boundary: str = "X-BOUNDARY") -> bytes:
    """주어진 파트로 multipart 본문을 생성합니다."""

    chunks: list[bytes] = []
    for name, filename, payload in parts:
        chunks.append(f"--{boundary}\r\n".encode("ascii"))
        if filename is not None:
            chunks.append(
                f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode("ascii")
            )
            chunks.append(b"Content-Type: application/octet-stream\r\n")
        else:
            chunks.append(f'Content-Disposition: form-data; name="{name}"\r\n'.encode("ascii"))
        chunks.append(b"\r\n")
        if isinstance(payload, str):
            chunks.append(payload.encode("utf-8"))
        else:
            chunks.append(payload)
        chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode("ascii"))
    return b"".join(chunks)


class MultipartFormTests(unittest.TestCase):
    def test_parse_returns_text_values(self):
        body = build_body([("target", None, "pdf")])
        form = server.MultipartForm(
            fp=FakeStream(body),
            content_type=f'multipart/form-data; boundary="X-BOUNDARY"',
            content_length=len(body),
        )
        self.assertIn("target", form)
        self.assertEqual(form.getfirst("target"), "pdf")
        self.assertEqual(form.getlist("target"), ["pdf"])

    def test_parse_returns_single_file_item(self):
        body = build_body([("file", "hello.txt", "hello world")])
        form = server.MultipartForm(
            fp=FakeStream(body),
            content_type="multipart/form-data; boundary=X-BOUNDARY",
            content_length=len(body),
        )
        files = form["file"]
        self.assertFalse(isinstance(files, list))
        self.assertEqual(files.filename, "hello.txt")
        self.assertEqual(files.file.read(), b"hello world")

    def test_parse_preserves_file_trailing_crlf(self):
        body = build_body([("file", "lines.txt", b"line 1\r\nline 2\r\n")])
        form = server.MultipartForm(
            fp=FakeStream(body),
            content_type="multipart/form-data; boundary=X-BOUNDARY",
            content_length=len(body),
        )
        files = form["file"]
        self.assertEqual(files.file.read(), b"line 1\r\nline 2\r\n")

    def test_parse_preserves_file_trailing_dashes(self):
        body = build_body([("file", "dash.txt", b"value--")])
        form = server.MultipartForm(
            fp=FakeStream(body),
            content_type="multipart/form-data; boundary=X-BOUNDARY",
            content_length=len(body),
        )
        files = form["file"]
        self.assertEqual(files.file.read(), b"value--")

    def test_parse_accepts_lowercase_part_headers(self):
        boundary = "X-BOUNDARY"
        body = (
            f"--{boundary}\r\n"
            'content-disposition: form-data; name="file"; filename="hello.txt"\r\n'
            "content-type: text/plain\r\n"
            "\r\n"
            "hello\r\n"
            f"--{boundary}--\r\n"
        ).encode("utf-8")
        form = server.MultipartForm(
            fp=FakeStream(body),
            content_type="multipart/form-data; boundary=X-BOUNDARY",
            content_length=len(body),
        )
        files = form["file"]
        self.assertEqual(files.filename, "hello.txt")
        self.assertEqual(files.content_type, "text/plain")
        self.assertEqual(files.file.read(), b"hello")

    def test_parse_returns_multiple_file_items(self):
        body = build_body([
            ("file", "a.txt", "AAA"),
            ("file", "b.txt", "BBB"),
        ])
        form = server.MultipartForm(
            fp=FakeStream(body),
            content_type="multipart/form-data; boundary=X-BOUNDARY",
            content_length=len(body),
        )
        files = form["file"]
        self.assertIsInstance(files, list)
        self.assertEqual(len(files), 2)
        self.assertEqual([f.filename for f in files], ["a.txt", "b.txt"])
        self.assertEqual([f.file.read() for f in files], [b"AAA", b"BBB"])

    def test_parse_preserves_relative_path_order(self):
        body = build_body([
            ("file", "a.txt", "AAA"),
            ("file", "b.txt", "BBB"),
            ("relativePath", None, "folder/a.txt"),
            ("relativePath", None, "folder/b.txt"),
        ])
        form = server.MultipartForm(
            fp=FakeStream(body),
            content_type="multipart/form-data; boundary=X-BOUNDARY",
            content_length=len(body),
        )
        self.assertEqual(
            server.form_file_items(form),
            server.form_file_items(form),
        )
        self.assertEqual(
            server.form_text_values(form, "relativePath"),
            ["folder/a.txt", "folder/b.txt"],
        )

    def test_missing_field_returns_default(self):
        body = build_body([("file", "a.txt", "AAA")])
        form = server.MultipartForm(
            fp=FakeStream(body),
            content_type="multipart/form-data; boundary=X-BOUNDARY",
            content_length=len(body),
        )
        self.assertIsNone(form.getfirst("nope"))
        self.assertEqual(form.getlist("nope"), [])
        self.assertNotIn("nope", form)

    def test_filename_with_path_is_trimmed(self):
        body = build_body([("file", "\\\\evil\\\\name.txt", "data")])
        form = server.MultipartForm(
            fp=FakeStream(body),
            content_type="multipart/form-data; boundary=X-BOUNDARY",
            content_length=len(body),
        )
        files = server.form_file_items(form)
        self.assertEqual(files[0].filename, "name.txt")

    def test_no_boundary_is_noop(self):
        body = b"target=pdf"
        form = server.MultipartForm(
            fp=FakeStream(body),
            content_type="text/plain",
            content_length=len(body),
        )
        self.assertNotIn("target", form)


if __name__ == "__main__":
    unittest.main()
