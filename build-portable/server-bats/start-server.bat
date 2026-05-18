@echo off
chcp 65001 >nul
setlocal

set "BASE_DIR=%~dp0"
set "PYTHON_EXE=%BASE_DIR%python\python.exe"

if not exist "%PYTHON_EXE%" (
    echo ERROR: Khong tim thay Python embedded
    pause
    exit /b 1
)

set "PYTHONHOME=%BASE_DIR%python"
set "PYTHONDONTWRITEBYTECODE=1"
set "QT6_BIN=%BASE_DIR%python\Lib\site-packages\PyQt6\Qt6\bin"
set "PATH=%QT6_BIN%;%BASE_DIR%python;%BASE_DIR%python\Lib\site-packages;%BASE_DIR%;%PATH%"

rem Doc host/port dung section tu config.ini
set "HOST=0.0.0.0"
set "PORT=8443"
set "HTTP_MODE=0"
set "PWA_ENABLED=1"
set "PWA_PORT=8444"
for /f "tokens=1,* delims==" %%A in ('"%PYTHON_EXE%" -c "import configparser, os; c=configparser.ConfigParser(); c.read(os.path.join(os.environ['BASE_DIR'], 'config.ini'), encoding='utf-8'); s=c['ServerSettings'] if c.has_section('ServerSettings') else {}; p=c['OfflinePWA'] if c.has_section('OfflinePWA') else {}; v=p.get('enabled','true').strip().lower(); print('HOST='+s.get('host','0.0.0.0')); print('PORT='+s.get('port','8443')); print('HTTP_MODE='+s.get('http_mode','0')); print('PWA_ENABLED='+('1' if v in ('1','true','yes','on') else '0')); print('PWA_PORT='+p.get('port','8444'))" 2^>nul') do set "%%A=%%B"

if "%HTTP_MODE%"=="1" (set "PROTO=http") else (set "PROTO=https")

echo ===================================
echo  Sherpa Vietnamese ASR - Server
echo ===================================
echo.
echo  Bind:  %HOST%:%PORT%
echo.
echo  Truy cap:
if "%HOST%"=="0.0.0.0" (
    echo    %PROTO%://localhost:%PORT%
    echo    %PROTO%://[IP-may-nay]:%PORT%
    if "%PWA_ENABLED%"=="1" (
        echo.
        echo  PWA offline:
        echo    %PROTO%://localhost:%PWA_PORT%
        echo    %PROTO%://[IP-may-nay]:%PWA_PORT%
    )
) else (
    echo    %PROTO%://%HOST%:%PORT%
    if "%PWA_ENABLED%"=="1" (
        echo.
        echo  PWA offline:
        echo    %PROTO%://%HOST%:%PWA_PORT%
    )
)
echo.
echo  Dang nhap admin de quan tri qua web.
echo  Nhan Ctrl+C de dung server.
echo ===================================
echo.

"%PYTHON_EXE%" "%BASE_DIR%server_launcher.py" --no-gui

if %errorlevel% neq 0 (
    echo.
    echo [Loi] Server dung voi ma loi %errorlevel%
    pause
)

exit /b %errorlevel%
