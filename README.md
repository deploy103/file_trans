# File Trans

브라우저에서 파일을 업로드하고 서버에서 변환한 뒤 결과 파일을 내려받는 로컬 웹 앱입니다.

## 실행

```bash
make build-tools
make run
```

기본 주소는 `http://127.0.0.1:8000`입니다.

변환기를 Docker worker 안에서 실행하려면 먼저 이미지를 빌드한 뒤 worker 모드로 실행합니다.

```bash
make build-worker
make run-docker-worker
```

Docker worker 모드는 변환 프로세스에 `network none`, `read-only` root filesystem, `no-new-privileges`, `cap-drop ALL`, PID/메모리 제한을 적용합니다.

## apt 의존성

```bash
make install-deps
```

설치 대상:

- `ffmpeg`: `mp4 -> mp3` 같은 영상/오디오 변환
- `libreoffice`: `hwp`, `docx`, `pptx`, `xlsx` 같은 문서의 PDF 변환
- `imagemagick`: 이미지 형식 변환
- `ghostscript`, `poppler-utils`, `fonts-nanum`: PDF/이미지/한글 폰트 보강
- `g++`, `default-jdk`, `rustc`, `cargo`, `mono-devel`: C++, Java, Rust, C# 빌드 도구

Python만 있어도 `csv -> json`, `json -> csv`, `txt/md/hwpx -> html`, `txt/md/hwpx -> pdf`, `파일 -> zip`은 동작합니다.

## 보안 기본값

- 업로드 확장자 allowlist와 파일 시그니처 검사를 함께 수행합니다.
- 원본 파일은 UUID 작업 디렉터리에 임시 이름으로 저장하고 변환 후 삭제합니다.
- 다운로드 URL은 작업 ID와 랜덤 토큰을 모두 요구합니다.
- 변환 프로세스는 timeout, 출력 크기 제한, stdin 차단, 제한된 환경변수로 실행됩니다.
- ImageMagick은 `config/imagemagick/policy.xml` 정책을 사용합니다.
- `data/`, `build/`, `deploy/`, `.env*`, `개발일지.md`, `요구사항`은 Git 추적에서 제외합니다.

## 빌드 구조

`make build-tools`는 C++, Rust, Java, C#로 작성한 파일 분석 보조 도구를 `build/tools/` 아래에 빌드합니다. 웹 서버의 `/api/capabilities`에서 컴파일러와 보조 도구 상태를 같이 확인할 수 있습니다.
