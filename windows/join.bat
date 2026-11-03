@echo off
rem join.bat <ip[:port]> [name] [password]   joins a BLACK TDM host (UDP 1508 by default)
setlocal
if "%~1"=="" (
    echo usage: join.bat ^<ip[:port]^> [name] [password]
    exit /b 2
)
call "%~dp0find_black.bat" || exit /b 1
set "ADDR=%~1"
echo %ADDR% | findstr ":" >nul || set "ADDR=%ADDR%:1508"
set "NAME=%~2"
if "%NAME%"=="" set "NAME=%USERNAME%"
pushd "%BLACK_DIR%" || exit /b 1
set "PASS="
if not "%~3"=="" set PASS=--password "%~3"
"%BLACK_EXE%" --tdm --connect %ADDR% --name "%NAME%" %PASS%
