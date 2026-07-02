@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo.
where python >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo Python is not installed or not on PATH.
    echo Install Python from https://www.python.org/downloads/ and try again.
    pause
    exit /b 1
)

set "VIRTUAL_ENV=%~dp0.venv"
set "PYTHON_EXE=%VIRTUAL_ENV%\Scripts\python.exe"

if not exist "%PYTHON_EXE%" (
    echo Creating virtual environment...
    python -m venv "%VIRTUAL_ENV%"
    if %ERRORLEVEL% neq 0 (
        echo Failed to create virtual environment.
        pause
        exit /b 1
    )
)

if not exist "%PYTHON_EXE%" (
    echo Python interpreter was not found: "%PYTHON_EXE%"
    pause
    exit /b 1
)

if exist "%~dp0requirements.txt" (
    "%PYTHON_EXE%" -c "import PySide6, appdirs, psutil" >nul 2>nul
    if %ERRORLEVEL% neq 0 (
        echo Installing requirements...
        "%PYTHON_EXE%" -m pip install --upgrade pip
        if %ERRORLEVEL% neq 0 goto install_failed
        "%PYTHON_EXE%" -m pip install -r "%~dp0requirements.txt"
        if %ERRORLEVEL% neq 0 goto install_failed
    )
) else (
    echo requirements.txt was not found.
    pause
    exit /b 1
)

if exist "%~dp0main.py" (
    "%PYTHON_EXE%" "%~dp0main.py"
) else (
    echo main.py was not found.
    pause
    exit /b 1
)

pause
exit /b 0

:install_failed
echo Failed to install requirements.
pause
exit /b 1
