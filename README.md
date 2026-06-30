# File Trans

File Trans는 브라우저에서 파일을 업로드하고 서버에서 변환한 뒤 결과 파일을 내려받는 파일 변환 웹 앱입니다.

프론트엔드는 도구 선택 화면을 메인으로 사용하고, 실제 변환 화면은 `/csvtojson/tran`, `/hwpxtopdf/tran`, `/filetozip/tran` 같은 경로로 바로 열 수 있습니다.

## 실행

로컬에서 한 번에 실행:

```bash
make run
```

프론트엔드와 백엔드를 분리해서 실행:

```bash
FILE_TRANS_ALLOWED_ORIGINS=http://127.0.0.1:4762 HOST=127.0.0.1 PORT=8766 python3 server.py
FRONTEND_PORT=4762 make run-frontend
```

- 프론트엔드: `http://127.0.0.1:4762`
- 백엔드: `http://127.0.0.1:8766`

## 오프라인 동작

프론트엔드는 CDN 없이 `public/` 정적 파일만 사용합니다. 백엔드도 로컬 프로세스로 실행되므로, 필요한 변환 프로그램이 PC에 설치되어 있으면 인터넷 없이 사용할 수 있습니다.

인터넷이 필요한 경우는 의존성 설치나 업데이트 단계입니다.

## 의존성

Ubuntu/WSL 기준 의존성 설치:

```bash
make install-deps
```

주요 변환 엔진:

- `ffmpeg`: 영상/오디오 변환
- `LibreOffice`: 문서 PDF 변환
- `libreoffice-h2orestart`: HWP PDF 변환용 필터
- `ImageMagick`, `Poppler`: 이미지/PDF 관련 변환
- `Pandoc`: 마크업 문서 변환
- `Calibre`: 전자책 변환

설치되지 않은 엔진이 필요한 변환 도구는 화면에서 비활성화됩니다. 특히 `hwp -> pdf`는 LibreOffice만으로는 부족할 수 있고, `libreoffice-h2orestart`가 설치되어 있어야 활성화됩니다.

## 지원 형식

설치된 변환 엔진에 따라 실제 가능한 변환 목록이 달라집니다.

- 이미지: `jpg`, `png`, `webp`, `gif`, `bmp`, `tiff`, `ico` 등
- 문서: `pdf`, `docx`, `pptx`, `xlsx`, `hwp`, `hwpx`, `html`, `md` 등
- 데이터/자막: `csv`, `tsv`, `json`, `xml`, `yaml`, `srt`, `vtt` 등
- 오디오/영상: `mp3`, `wav`, `flac`, `mp4`, `mov`, `mkv`, `webm` 등
- 전자책: `epub`, `mobi`, `azw3`, `fb2`, `cbz` 등
- 압축: 선택한 파일을 `zip`으로 묶기

## 확인

```bash
make check
make smoke-test
```

프론트엔드만 빠르게 확인:

```bash
make frontend-smoke-test
```

## 범위

이 앱은 파일 변환기입니다. 사용자 제출 코드를 컴파일하거나 실행하는 온라인 컴파일러 기능은 포함하지 않습니다.
