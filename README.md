# FFmpegGUI by LHCinema

![image](https://github.com/user-attachments/assets/6a97dcd9-3c8d-459f-b391-985d936426b3)


FFmpegGUI는 FFmpeg를 사용하여 비디오 파일을 쉽게 편집하고 인코딩할 수 있는 그래픽 사용자 인터페이스(GUI) 애플리케이션입니다.

## 기능 소개



### 파일목록

![image](https://github.com/user-attachments/assets/6f3189f9-405b-4ef2-bfd3-133b9b65d61a)  
![image](https://github.com/user-attachments/assets/619be8ba-1891-4d12-9b8e-8d4347294c56)  



- 비디오 파일을 쉽게 추가하고 관리할 수 있습니다.
- 드래그 앤 드롭으로 파일 추가 가능

### 순서정렬

![image](https://github.com/user-attachments/assets/7fea9482-ed54-4564-ad27-ca0d795498d0)  


- 이름 순 정렬: 파일을 알파벳 순으로 정렬합니다.
- 순서 반대로: 현재 목록의 순서를 반대로 뒤집습니다.
- 수동 정렬: 원하는 순서로 파일을 드래그하여 재배치할 수 있습니다.

### 트림기능

![image](https://github.com/user-attachments/assets/7b2bc81e-8567-490b-97d9-b9ad319d2a68)
![image](https://github.com/user-attachments/assets/d73d5103-e787-4f37-90f4-ff3667602cbb)  


- 전체 트림: 모든 비디오에 동일한 트림 설정을 적용합니다.
- 개별 트림: 각 비디오마다 다른 트림 설정을 적용할 수 있습니다.

### 옵션설정

![image](https://github.com/user-attachments/assets/7b59cbb9-30c8-41c9-bff9-c9d0db1008b6)  


- 프레임레이트 조정: 1-60 FPS 범위 내 설정 가능
- 해상도 변경: 사전 정의된 해상도 또는 사용자 지정 해상도 선택
- 다양한 인코딩 옵션 제공: H.264, H.265, VP9 등 코덱 선택 가능

### Preview 기능

![image](https://github.com/user-attachments/assets/1c24afa7-b1da-406a-80b5-e7d52b559597)  


- 재생속도 조절이 가능한 미리보기 기능
- 0.25x에서 8x까지 재생 속도 조절

### 출력 경로

![image](https://github.com/user-attachments/assets/e0162672-2e79-4ea3-8098-dddc57759aac)  


- 인코딩된 파일의 저장 위치를 지정할 수 있습니다.
- 이전에 사용했던 저장 위치를 자동으로 기억합니다.

### 인코딩 시작

![image](https://github.com/user-attachments/assets/f517ced9-fbef-460b-889f-f7f096f65654)  


- 설정한 옵션으로 인코딩 프로세스를 시작합니다.
- 진행 상황을 실시간으로 확인할 수 있는 프로그레스 바

### 업데이트 확인

![image](https://github.com/user-attachments/assets/c528a119-d7c8-4222-935a-279070ffcd80)  


- 최신 버전의 소프트웨어를 자동으로 확인하고 업데이트할 수 있습니다.
- 업데이트 알림 및 자동 업데이트 옵션

## 사용 방법

1. 목록에 파일 또는 폴더를 드래그 하여 추가합니다.
2. 파일 순서를 맞추고 세부 설정을 합니다.
3. 출력 경로를 지정합니다.
4. 인코딩 시작을 눌러 인코딩을 합니다.
5. 진행 상황을 확인하고 완료될 때까지 기다립니다.

## 빌드 방법

1. 이 저장소를 클론합니다:
   ```
   git clone https://github.com/CharlieYang0040/ffmpegGUI
   ```
2. 필요한 라이브러리를 설치합니다:
   ```
   pip install PyQt5 ffmpeg-python opencv-python-headless
   ```
3. 프로젝트 디렉토리로 이동합니다:
   ```
   cd ffmpegGUI
   ```
4. 애플리케이션을 실행합니다:
   ```
   python main.py
   ```

## 주의사항

- FFmpegGUI를 사용하기 위해서는 FFmpeg가 시스템에 설치되어 있어야 합니다.
- 대용량 비디오 파일을 처리할 때는 충분한 저장 공간과 메모리가 필요할 수 있습니다.
- 인코딩 과정은 컴퓨터 성능에 따라 시간이 오래 걸릴 수 있습니다.
- 저작권이 있는 콘텐츠를 처리할 때는 관련 법규를 준수해야 합니다.

## 기여하기

버그 리포트, 기능 제안 또는 풀 리퀘스트는 언제나 환영합니다. 기여하기 전에 프로젝트의 기여 가이드라인을 확인해주세요.

1. 프로젝트를 포크합니다.
2. 새로운 브랜치를 생성합니다 (`git checkout -b feature/AmazingFeature`).
3. 변경사항을 커밋합니다 (`git commit -m 'Add some AmazingFeature'`).
4. 브랜치에 푸시합니다 (`git push origin feature/AmazingFeature`).
5. 풀 리퀘스트를 생성합니다.

## 라이선스

이 프로젝트는 [MIT 라이선스](LICENSE)에 따라 라이선스가 부여됩니다.

## 연락처

LHCinema - [charlieyang@lionhearts.co.kr]

프로젝트 링크: https://github.com/CharlieYang0040/ffmpegGUI
