# File Trans

브라우저에서 파일을 업로드하고 서버에서 변환한 뒤 결과 파일을 내려받는 로컬 웹 앱입니다.

## 실행

```bash
make run
```

기본 주소는 `http://127.0.0.1:8000`입니다.

기본 동작 검증:

```bash
make check
make smoke-test
```

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
- HTML/마크업 입력의 원격 URL 및 `file:` 참조는 변환 전에 차단합니다.
- 원본 파일은 UUID 작업 디렉터리에 임시 이름으로 저장하고 변환 후 삭제합니다.
- 파일명은 안전 문자로 정규화하고 기본 180자로 제한합니다.
- 다운로드 URL은 작업 ID와 랜덤 토큰을 모두 요구합니다.
- 변환 프로세스는 timeout, 출력 크기 제한, stdin 차단, 제한된 환경변수로 실행됩니다.
- 변환 프로세스의 `HOME`은 `data/runtime-home` 전용 디렉터리로 고정합니다.
- 동시 변환 수는 기본 2개로 제한하며 `FILE_TRANS_MAX_CONCURRENT`로 조정할 수 있습니다.
- 요청 읽기 timeout은 기본 30초이며 `FILE_TRANS_REQUEST_TIMEOUT`으로 조정할 수 있습니다.
- 데이터 변환 레코드 수는 기본 100,000개로 제한하며 `FILE_TRANS_MAX_DATA_RECORDS`로 조정할 수 있습니다.
- 문서 컨테이너 내부 외부 참조 검사 범위는 기본 20MiB이며 `FILE_TRANS_MAX_REFERENCE_SCAN`으로 조정할 수 있습니다.
- 선택적으로 ClamAV `clamscan` 업로드 검사를 켤 수 있습니다: `FILE_TRANS_ENABLE_CLAMSCAN=1`.
- 만료 결과 정리는 기본 10분 간격이며 `FILE_TRANS_CLEANUP_INTERVAL`로 조정할 수 있습니다.
- ImageMagick은 `config/imagemagick/policy.xml` 정책을 사용합니다.
- `data/`, `build/`, `deploy/`, `.env*`, `개발일지.md`, `요구사항`은 Git 추적에서 제외합니다.

## 빌드 구조

`make build-tools`는 C++, Rust, Java, C#로 작성한 로컬 파일 분석 probe를 `build/tools/` 아래에 빌드하는 개발용 작업입니다. 웹 서버는 사용자 제출 코드를 컴파일하거나 실행하지 않으며, `/api/capabilities`에도 컴파일러 상태를 노출하지 않습니다.
