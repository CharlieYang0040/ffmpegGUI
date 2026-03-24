@echo off

echo =======================================================
echo.
echo           ffmpegGUI 런처 및 자동 업데이트기
echo.
echo =======================================================
echo.

REM 1. 사용자 설정 라인 (네트워크 경로를 본인 환경에 맞게 수정하세요)
set "NETWORK_DIR=\\192.168.2.215\Share_151\art\영상연출\util\ffmpegGUI"

REM 2. 사용자 로컬 동기화 경로 (로컬 PC에서 가장 빠른 C드라이브 계정 폴더)
set "LOCAL_DIR=%LocalAppData%\LHCinema\ffmpegGUI_App"

REM 네트워크 경로 존재 여부 확인
if exist "%NETWORK_DIR%" goto SYNC_START

color 0C
echo [경고] 네트워크 경로에 접근할 수 없거나 폴더를 찾지 못했습니다!
echo 경로 탐색 실패: %NETWORK_DIR%
echo 기존 로컬 버전이 있다면 그냥 실행합니다.
echo.
timeout /t 3 >nul
color 07
goto RUN_APP

:SYNC_START
echo 최신 버전 파일을 네트워크에서 검색하고 로컬로 초고속 동기화하는 중입니다...
echo (이 창은 동기화가 끝나면 자동으로 닫힙니다)

REM 3. Robocopy를 이용한 증분 미러링 (변경된 파일만 초고속 덮어쓰기)
robocopy "%NETWORK_DIR%" "%LOCAL_DIR%" /MIR /R:0 /W:0 /NDL /NFL /NJH /NJS /nc /ns /np

REM 복사 오류 검사 (robocopy는 8 이상이면 심각한 에러)
if %errorlevel% GEQ 8 goto SYNC_ERROR
goto RUN_APP

:SYNC_ERROR
color 0E
echo [경고] 다운로드 중 일부 오류가 발생했습니다.
echo 앱을 켜둔 상태이면 덮어쓰기가 안 되었을 수 있습니다. 앱을 끄고 다시 시도하세요.
timeout /t 3 >nul
color 07

:RUN_APP
REM 4. 앱 실행
if exist "%LOCAL_DIR%\ffmpegGUI.exe" goto LAUNCH_SUCCESS

color 0C
echo [오류] 로컬 폴더에 실행 파일(ffmpegGUI.exe)이 존재하지 않습니다!
echo 네트워크 경로(%NETWORK_DIR%)가 올바른지 다시 확인해 주세요.
pause
color 07
exit

:LAUNCH_SUCCESS
echo.
echo -------------------------------------------------------
echo 동기화 완료! ffmpegGUI를 실행합니다...
echo -------------------------------------------------------
start "" "%LOCAL_DIR%\ffmpegGUI.exe"
exit