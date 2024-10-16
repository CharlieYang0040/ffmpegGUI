# FFmpegGUI by LHCinema

FFmpegGUI는 FFmpeg를 사용하여 비디오 파일을 쉽게 편집하고 인코딩할 수 있는 그래픽 사용자 인터페이스(GUI) 애플리케이션입니다.

## 주요 기능

- 다중 비디오 파일 연결
- 비디오 미리보기 기능
- 재생 속도 조절
- 2f offset 적용 옵션
- 사용자 정의 프레임레이트 및 해상도 설정
- 다양한 인코딩 옵션 지원 (코덱, 픽셀 포맷, 색공간 등)
- 드래그 앤 드롭으로 파일 추가
- 디버그 모드 지원

## 설치 방법

1. 이 저장소를 클론합니다:
   ```
   git clone https://github.com/CharlieYang0040/ffmpegGUI
   ```
2. 필요한 라이브러리를 설치합니다:
   ```
   pip install PyQt5
   ```
3. FFmpeg를 다운로드하여 `libs/ffmpeg-7.1-full_build/bin/` 디렉토리에 설치합니다.

## 사용 방법

1. 다음 명령어로 애플리케이션을 실행합니다:
   ```
   python main.py
   ```
2. '파일 추가' 버튼을 클릭하거나 파일을 창으로 드래그하여 비디오 파일을 추가합니다.
3. 원하는 인코딩 옵션을 설정합니다.
4. '인코딩 시작' 버튼을 클릭하여 처리를 시작합니다.

## 주의사항

- 이 애플리케이션은 Windows 환경에서 개발 및 테스트되었습니다.
- FFmpeg가 올바르게 설치되어 있어야 합니다.

## 기여하기

버그 리포트, 기능 제안 또는 풀 리퀘스트는 언제나 환영합니다. 기여하기 전에 프로젝트의 기여 가이드라인을 확인해주세요.

## 라이선스

이 프로젝트는 [MIT 라이선스](LICENSE)에 따라 라이선스가 부여됩니다.

## 연락처

LHCinema - [charlieyang@lionhearts.co.kr]

프로젝트 링크: https://github.com/CharlieYang0040/ffmpegGUI