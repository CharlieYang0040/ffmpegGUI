@echo off
REM ffmpegGUI Nuitka Build Script

REM Activate virtual environment
call ffmpegGUI_venv\Scripts\activate.bat

REM Run Nuitka build command
echo Building ffmpegGUI with Nuitka...
python -m nuitka ^
    --standalone ^
    --onefile ^
    --onefile-no-compression ^
    --enable-plugin=pyside6 ^
    --enable-plugin=upx ^
    --upx-binary="D:\WORKDATA\upx-5.1.0-win64\upx.exe" ^
    --include-data-file=libs/ffmpeg-7.1-full_build/bin/ffmpeg.exe=libs/ffmpeg-7.1-full_build/bin/ffmpeg.exe ^
    --include-data-file=libs/ffmpeg-7.1-full_build/bin/ffprobe.exe=libs/ffmpeg-7.1-full_build/bin/ffprobe.exe ^
    --include-data-file=icon.png=icon.png ^
    --include-data-file=icon.ico=icon.ico ^
    --windows-icon-from-ico=icon.ico ^
    --output-dir=dist ^
    --remove-output ^
    main.py

echo Build complete. executable is in dist/main.exe (you may want to rename it to ffmpegGUI.exe)
pause
