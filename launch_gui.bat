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

set "VIRTUAL_ENV=%~dp0ffmpeg_venv"

@REM venv 폴더 존재 확인
@REM if not exist "%VIRTUAL_ENV%" (
@REM     echo 가상환경을 생성합니다...
@REM     python -m venv ffmpeg_venv
@REM     if %ERRORLEVEL% neq 0 (
@REM         echo 가상환경 생성에 실패했습니다.
@REM         pause
@REM         exit /b 1
@REM     )
@REM     echo 가상환경이 생성되었습니다.
@REM     echo.
@REM )

set "PATH=%VIRTUAL_ENV%\Scripts;%PATH%"
set "PYTHONPATH=%VIRTUAL_ENV%\Lib\site-packages;%PYTHONPATH%"

echo 가상환경 경로: %VIRTUAL_ENV%
echo Python 인터프리터: "%VIRTUAL_ENV%\Scripts\python.exe"
"%VIRTUAL_ENV%\Scripts\python.exe" -c "import sys; print('Python 버전:', sys.version)"


echo 가상환경이 활성화되었습니다.
echo.

"%VIRTUAL_ENV%\Scripts\python.exe" "%~dp0main.py"

pause 