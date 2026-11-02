@echo off
rem host.bat [port] [name]   hosts a BLACK TDM match (UDP 1509, LAN discovery on UDP 1508)
setlocal
call "%~dp0find_black.bat" || exit /b 1
set "PORT=%~1"
if "%PORT%"=="" set "PORT=1509"
set "NAME=%~2"
if "%NAME%"=="" set "NAME=%USERNAME%"
pushd "%BLACK_DIR%" || exit /b 1
"%BLACK_EXE%" --tdm --host %PORT% --name "%NAME%"
