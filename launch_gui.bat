@echo off

chcp 65001
echo.

@REM Python 설치 확인
where python >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo Python이 설치되어 있지 않습니다.
    echo https://www.python.org/downloads/ 에서 Python을 설치해주세요.
    pause
    exit /b 1
)

set "VIRTUAL_ENV=%~dp0ffmpegGUI_venv"

@REM venv 폴더 존재 확인
if not exist "%VIRTUAL_ENV%" (
    echo 가상환경을 생성합니다...
    python -m venv ffmpegGUI_venv
    if %ERRORLEVEL% neq 0 (
        echo 가상환경 생성에 실패했습니다.
        pause
        exit /b 1
    )
    echo 가상환경이 생성되었습니다.
    echo.
)

set "PATH=%VIRTUAL_ENV%\Scripts;%PATH%"
set "PYTHONPATH=%VIRTUAL_ENV%\Lib\site-packages;%PYTHONPATH%"

echo 가상환경 경로: %VIRTUAL_ENV%
echo Python 인터프리터: "%VIRTUAL_ENV%\Scripts\python.exe"

@REM Python 인터프리터 존재 확인
if exist "%VIRTUAL_ENV%\Scripts\python.exe" (
    "%VIRTUAL_ENV%\Scripts\python.exe" -c "import sys; print('Python 버전:', sys.version)"
) else (
    echo 오류: Python 인터프리터를 찾을 수 없습니다.
    echo 경로: "%VIRTUAL_ENV%\Scripts\python.exe"
    pause
    exit /b 1
)

echo 가상환경이 활성화되었습니다.
echo.

@REM main.py 실행
if exist "%~dp0main.py" (
    "%VIRTUAL_ENV%\Scripts\python.exe" "%~dp0main.py"
) else (
    echo 오류: main.py 파일을 찾을 수 없습니다.
    pause
    exit /b 1
)

pause