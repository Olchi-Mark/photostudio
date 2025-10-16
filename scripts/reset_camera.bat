@echo off
REM UTF-8 코드페이지 설정 (한글 주석/출력용)
chcp 65001 >nul 2>&1

REM 카메라 연결 바쁨(BUSY) 상태 해소 스크립트
REM - photostudio 관련 프로세스 종료 (타겟팅)
REM - 카메라 관련 핵심 서비스 재시작(안전 범위)
REM - (선택) 벤더 유틸 종료/USB 장치 재시작(devcon 존재 시) 주석 제공

echo [reset_camera] 시작합니다. 관리자 권한 필요.

REM 관리자 권한 체크
net session >nul 2>&1
if %errorlevel% NEQ 0 (
    echo 관리자 권한으로 다시 실행하세요. (우클릭^>관리자 권한으로 실행)
    exit /b 1
)

echo [1/4] photostudio 관련 프로세스 종료 중...
REM photostudio 경로로 실행된 python/photostudio 프로세스만 강제 종료 (안전)
powershell -NoProfile -Command "try { Get-CimInstance Win32_Process ^| Where-Object { ($_.CommandLine -match 'C:\\dev\\photostudio') -and ($_.Name -match '^(python\.exe|photostudio\.exe)$') } ^| ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue } } catch { }"

REM (선택) 공용 카메라/화상회의 앱이 점유할 수 있으니 필요 시 주석 해제 후 사용
REM for %%P in ("EOS Utility.exe" "EOSUtility.exe" "ImagingEdgeDesktop.exe" "Nikon Message Center 2.exe" "NikonMessageCenter2.exe" "PTPCamera.exe" "WindowsCamera.exe" "Zoom.exe" "Teams.exe" "Skype.exe") do (
REM   taskkill /IM "%%~P" /F >nul 2>&1
REM )

echo [2/4] 카메라 관련 서비스 재시작 중...
REM Windows Image Acquisition (WIA)
net stop stisvc >nul 2>&1
net start stisvc >nul 2>&1

REM Windows Camera Frame Server
sc query FrameServer >nul 2>&1
if %errorlevel% EQU 0 (
    net stop FrameServer >nul 2>&1
    net start FrameServer >nul 2>&1
)

REM Device Association Service (장치 연결 관리)
net stop DeviceAssociationService >nul 2>&1
net start DeviceAssociationService >nul 2>&1

echo [3/4] 잠시 대기...
timeout /t 2 >nul 2>&1

REM (선택) devcon.exe가 있을 경우 특정 카메라 장치를 재시작할 수 있습니다.
REM   - devcon은 WDK 구성요소이며, 동일 폴더에 devcon.exe가 있을 때만 동작합니다.
REM   - 아래 예시는 하드웨어 ID 패턴을 편집해 사용하세요 (장치 관리자^>자세히^>하드웨어 ID 확인).
REM if exist "%~dp0devcon.exe" (
REM   echo [선택] devcon을 사용해 장치 재시작 시도...
REM   "%~dp0devcon.exe" restart "USB\VID_*&PID_*"
REM )

echo [4/4] 완료됐습니다. 이제 photostudio를 다시 실행해 보세요.
exit /b 0

