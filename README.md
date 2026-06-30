# File Trans

브라우저에서 파일을 업로드하고 서버에서 변환한 뒤 결과 파일을 내려받는 로컬 웹 앱입니다.

## 실행

```bash
make run
```

기본 주소는 `http://127.0.0.1:8000`입니다.

프론트엔드와 백엔드를 분리해서 띄우려면 백엔드 origin 허용값을 지정하고 프론트 서버를 실행합니다.

```bash
FILE_TRANS_ALLOWED_ORIGINS=http://127.0.0.1:4762 HOST=127.0.0.1 PORT=8766 python3 server.py
FRONTEND_PORT=4762 make run-frontend
```

프론트 메인은 도구 선택 화면이고, 변환 화면은 `/csvtojson/tran`, `/hwpxtopdf/tran`, `/filetozip/tran` 같은 경로로 직접 열 수 있습니다.

분리 프론트 포트에서 접속하면 기본 백엔드 주소는 `http://127.0.0.1:8766`으로 추론합니다. 다른 백엔드를 붙일 때는 `http://127.0.0.1:4762/?api=http://127.0.0.1:9000`처럼 `api` 쿼리로 override할 수 있습니다.

## 오프라인 동작

프론트엔드는 CDN이나 원격 asset 없이 `public/` 정적 파일만 사용합니다. 백엔드도 로컬 프로세스로 실행되므로, 필요한 변환 엔진만 이 PC에 설치되어 있으면 인터넷 연결 없이 변환할 수 있습니다.

인터넷이 필요한 경우는 의존성 설치/업데이트 단계입니다. 예를 들어 `ffmpeg`, `LibreOffice`, `ImageMagick`, `Poppler`, `Pandoc`, `Calibre` 설치는 apt 저장소 접근이 필요할 수 있습니다. 설치되지 않은 엔진에 의존하는 변환 도구는 메인 화면에서 비활성화됩니다.

기본 동작 검증:

```bash
make check
make smoke-test
```

`make smoke-test`는 변환 API와 다운로드 보안 흐름을 확인한 뒤, 별도 프론트 서버의 SPA fallback, favicon, 캐시 방지/보안 헤더도 확인합니다. 프론트 서버만 빠르게 확인하려면 `make frontend-smoke-test`를 사용할 수 있습니다.

프론트 작업 화면은 한 번에 최대 30개 파일을 다룹니다. 브라우저에서 결과를 ZIP으로 묶는 기능은 총 512MiB까지 사용하고, 그보다 큰 결과는 개별 다운로드를 사용해야 합니다.

변환기를 Docker worker 안에서 실행하려면 먼저 이미지를 빌드한 뒤 worker 모드로 실행합니다.

```bash
make build-worker
make run-docker-worker
```

Docker worker 모드는 변환 프로세스에 `network none`, `read-only` root filesystem, `no-new-privileges`, `cap-drop ALL`, non-root 사용자, PID/메모리 제한을 적용합니다.

## apt 의존성

```bash
make install-deps
```

설치 대상:

- `ffmpeg`: `mp4 -> mp3` 같은 영상/오디오 변환
- `libreoffice`: `hwp`, `docx`, `pptx`, `xlsx` 같은 문서의 PDF 변환
- `imagemagick`: 이미지 형식 변환
- `ghostscript`, `poppler-utils`, `fonts-nanum`: PDF/이미지/한글 폰트 보강
- `pandoc`: Markdown, reStructuredText, Org, LaTeX, Typst, Notebook 같은 마크업 문서 변환
- `calibre`: EPUB, MOBI, AZW3, FB2, CBZ 같은 전자책 변환

Python만 있어도 `csv/tsv -> json`, `json/ndjson -> csv/tsv`, `srt <-> vtt`, `txt/md/hwpx -> html`, `txt/md/hwpx -> pdf`, `파일 -> zip`은 동작합니다.

## 지원 형식

현재 서버 allowlist 기준 입력 형식은 90개 이상입니다. UI의 `/api/capabilities` 응답에서 설치된 엔진 기준으로 실제 선택 가능한 출력 형식을 확인합니다.

- 이미지: `jpg`, `png`, `webp`, `gif`, `bmp`, `tiff`, `ico`, `avif`, `heic`, `psd`, `tga`, `pnm`
- 문서/마크업: `pdf`, `doc`, `docx`, `ppt`, `pptx`, `xls`, `xlsx`, `odt`, `ods`, `odp`, `rtf`, `hwp`, `hwpx`, `html`, `md`, `rst`, `org`, `tex`, `typ`, `ipynb`
- 데이터/자막: `csv`, `tsv`, `json`, `ndjson`, `xml`, `yaml`, `yml`, `srt`, `vtt`
- 오디오/영상: `mp3`, `wav`, `flac`, `aac`, `m4a`, `ogg`, `opus`, `mp4`, `mov`, `mkv`, `webm`, `avi`, `flv`, `wmv`, `mpeg`, `ts`
- 전자책: `epub`, `mobi`, `azw3`, `fb2`, `cbz`, `djvu`, `chm`

## 보안 기본값

자세한 운영 보안 메모는 [SECURITY.md](SECURITY.md)를 확인하세요.

- 업로드 확장자 allowlist와 파일 시그니처 검사를 함께 수행합니다.
- HTML/마크업/flat XML 문서 입력의 원격 URL 및 `file:` 참조는 변환 전에 차단합니다.
- XML 계열 입력의 DTD/ENTITY 선언은 변환 전에 차단합니다.
- 원본 파일은 UUID 작업 디렉터리에 임시 이름으로 저장하고 변환 후 삭제합니다.
- 데이터 루트는 기본 `data/`이며 `FILE_TRANS_DATA_DIR`로 분리할 수 있습니다.
- 파일명은 안전 문자로 정규화하고 기본 180자로 제한합니다.
- 다운로드 URL은 작업 ID와 랜덤 토큰을 모두 요구합니다.
- 브라우저의 명시적인 cross-site 변환 POST 요청은 `Origin`/`Sec-Fetch-Site` 검사로 차단합니다.
- 프론트와 백엔드를 다른 포트로 띄울 때는 `FILE_TRANS_ALLOWED_ORIGINS`에 프론트 origin을 명시합니다.
- 변환 프로세스는 timeout, 출력 크기 제한, stdin 차단, 제한된 환경변수로 실행됩니다.
- 변환 프로세스의 `HOME`은 `data/runtime-home` 전용 디렉터리로 고정합니다.
- 변환 도구 탐색/실행 `PATH`는 안전한 시스템 경로로 제한하며 `FILE_TRANS_CONVERT_PATH`로 조정할 수 있습니다.
- 동시 변환 수는 기본 2개로 제한하며 `FILE_TRANS_MAX_CONCURRENT`로 조정할 수 있습니다.
- 요청 읽기 timeout은 기본 30초이며 `FILE_TRANS_REQUEST_TIMEOUT`으로 조정할 수 있습니다.
- 데이터 변환 레코드 수는 기본 100,000개로 제한하며 `FILE_TRANS_MAX_DATA_RECORDS`로 조정할 수 있습니다.
- 문서 컨테이너 내부 외부 참조 검사 범위는 기본 20MiB이며 `FILE_TRANS_MAX_REFERENCE_SCAN`으로 조정할 수 있습니다.
- 선택적으로 ClamAV `clamscan` 업로드 검사를 켤 수 있습니다: `FILE_TRANS_ENABLE_CLAMSCAN=1`.
- 만료 결과 정리는 기본 10분 간격이며 `FILE_TRANS_CLEANUP_INTERVAL`로 조정할 수 있습니다.
- ImageMagick은 `config/imagemagick/policy.xml` 정책을 사용합니다.
- `data/`, `build/`, `deploy/`, `.env*`, `개발일지.md`, `요구사항`은 Git 추적에서 제외합니다.

## 범위

이 앱은 파일 변환기이며 사용자 제출 코드를 컴파일하거나 실행하지 않습니다. C++, Java, Rust, C# 같은 온라인 컴파일러 기능은 포함하지 않습니다.
