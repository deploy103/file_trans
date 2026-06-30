# File Trans

브라우저에서 파일을 업로드하고 서버에서 변환한 뒤 결과 파일을 내려받는 로컬 웹 앱입니다.

## 실행

```bash
make build-tools
make run
```

기본 주소는 `http://127.0.0.1:8000`입니다.

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

## 빌드 구조

`make build-tools`는 C++, Rust, Java, C#로 작성한 파일 분석 보조 도구를 `build/tools/` 아래에 빌드합니다. 웹 서버의 `/api/capabilities`에서 컴파일러와 보조 도구 상태를 같이 확인할 수 있습니다.
