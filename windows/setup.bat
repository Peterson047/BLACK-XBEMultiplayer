@echo off
rem setup.bat   derives the multiplayer map, arsenal and audio from your own Black.iso (run once)
rem needs Python 3 (python.org, "Add python.exe to PATH") and Black.iso + default.xbe in assets\
setlocal
call "%~dp0find_black.bat" || exit /b 1
rem a package keeps tools\ and assets\ beside BLACK.exe; the repository keeps them at its root
set "ROOT=%BLACK_ROOT%"
if exist "%BLACK_DIR%\tools\extract_mp_map.py" set "ROOT=%BLACK_DIR%"
for %%r in ("%ROOT%") do set "ROOT=%%~fr"
if not exist "%ROOT%\assets\Black.iso" (
    echo Put Black.iso and default.xbe from your copy of the game in %ROOT%\assets first.
    exit /b 1
)
where python >nul 2>nul || (echo Python 3 was not found on PATH. & exit /b 1)
python "%ROOT%\tools\extract_mp_map.py" --iso "%ROOT%\assets\Black.iso" --out "%ROOT%\assets\levels\level_mp00" || exit /b 1
python "%ROOT%\tools\prepare_pvp_weapons.py" --iso "%ROOT%\assets\Black.iso" --package "%ROOT%\assets\levels\level_mp00" || exit /b 1
echo Ready. Use host.bat or join.bat ^<ip^>.
