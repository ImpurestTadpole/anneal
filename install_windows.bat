@echo off
rem Anneal installer for Windows 10/11 (x64). Needs Python 3.10 - 3.13 from python.org
rem (tick "Add python.exe to PATH" or keep the "py" launcher, which is the default).
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
  set "PY=py -3"
) else (
  where python >nul 2>nul || (
    echo Python was not found. Install Python 3.11 or newer from https://www.python.org/downloads/windows/
    echo and run this file again.
    pause & exit /b 1
  )
  set "PY=python"
)

%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)"
if errorlevel 1 (
  echo Anneal needs Python 3.10 or newer. Install it from https://www.python.org/downloads/windows/
  pause & exit /b 1
)

echo Creating a private Python environment in .venv ...
%PY% -m venv .venv || (echo Could not create the environment. & pause & exit /b 1)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -e . || (echo Installing the core packages failed. & pause & exit /b 1)

echo Installing optional STEP support ...
python -m pip install cadquery-ocp || echo STEP support not installed. Export STL from CAD instead.

echo Installing the desktop window (uses Microsoft Edge WebView2, part of Windows 10/11) ...
python -m pip install pywebview || echo Desktop window not installed. Anneal will open in your browser instead.

echo Adding Anneal to the desktop and the Start menu ...
python -m anneal shortcut

echo.
echo Checking the solver ...
python -m anneal validate
echo.
echo Installed. Open Anneal from the icon on your desktop or in the Start menu.
echo You can also drag a model onto Anneal.bat, or run:  .venv\Scripts\anneal run examples\bracket.json
pause
