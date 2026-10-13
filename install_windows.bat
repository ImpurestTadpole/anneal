@echo off
rem Anneal installer for Windows 10/11 (x64). Needs Python 3.10 - 3.13 from python.org
rem (tick "Add python.exe to PATH" or keep the "py" launcher, which is the default).
rem Required packages (numpy, scipy, pyamg, trimesh, scikit-image, matplotlib, manifold3d) must
rem install. Optional packages (STEP support, desktop window, gmsh) may fail: Anneal still starts.
setlocal
cd /d "%~dp0"

rem Use the newest Python from 3.13 down to 3.10. Python 3.14 is not used: pyamg has no
rem ready-made package (wheel) for it on Windows yet.
set "PY="
where py >nul 2>nul
if %errorlevel%==0 (
  for %%V in (3.13 3.12 3.11 3.10) do (
    if not defined PY (
      py -%%V -c "import sys" >nul 2>nul && set "PY=py -%%V"
    )
  )
  if not defined PY set "PY=py -3"
)
if not defined PY (
  where python >nul 2>nul || (
    echo Python was not found. Install Python 3.13 from https://www.python.org/downloads/windows/
    echo and run this file again.
    pause & exit /b 1
  )
  set "PY=python"
)
echo Using Python: %PY%
%PY% --version

%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)"
if errorlevel 1 (
  echo Anneal needs Python 3.10 or newer. Install it from https://www.python.org/downloads/windows/
  pause & exit /b 1
)
%PY% -c "import sys; sys.exit(0 if sys.version_info[:2] <= (3,13) else 1)"
if errorlevel 1 (
  echo WARNING: this Python is newer than 3.13. pyamg may need a C++ compiler to install.
  echo If the install fails, install Python 3.13 from python.org and run this file again.
)

echo Creating a private Python environment in .venv ...
%PY% -m venv .venv || (echo Could not create the environment. & pause & exit /b 1)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -e . || (echo Installing the core packages failed. See the messages above. & pause & exit /b 1)
python -c "import numpy, scipy, pyamg, trimesh, skimage, matplotlib, manifold3d" || (echo A required package does not load. See the messages above. & pause & exit /b 1)

echo Installing optional STEP support ...
python -m pip install cadquery-ocp || echo STEP support not installed. Export STL from CAD instead.

echo Installing the desktop window (uses Microsoft Edge WebView2, part of Windows 10/11) ...
python -m pip install "pywebview>=5.0" || echo Desktop window not installed. Anneal will open in your browser instead.

echo Installing optional gmsh (for the CalculiX large-deformation check) ...
python -m pip install gmsh || echo gmsh not installed. The CalculiX check is skipped.

echo Adding Anneal to the desktop and the Start menu ...
python -m anneal shortcut

echo.
echo Checking the start-up path ...
python -m anneal doctor
echo.
echo Checking the solver ...
python -m anneal validate
echo.
echo Installed. Open Anneal from the icon on your desktop or in the Start menu.
echo You can also drag a model onto Anneal.bat, or run:  .venv\Scripts\anneal run examples\bracket.json
echo If the icon does nothing, run "Anneal GUI.bat" and read %USERPROFILE%\Anneal Projects\anneal-startup.log
pause
