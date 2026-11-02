@echo off
rem sets BLACK_EXE/BLACK_DIR: BLACK.exe beside these scripts (a package), else the repository's release build
set "BLACK_ROOT=%~dp0..\.."
for %%d in ("%~dp0." "%~dp0.." "%BLACK_ROOT%\out\build\win-release") do (
    if exist "%%~fd\BLACK.exe" (
        set "BLACK_DIR=%%~fd"
        set "BLACK_EXE=%%~fd\BLACK.exe"
        exit /b 0
    )
)
echo BLACK.exe not found: build it with build.bat first.
exit /b 1
