@echo off
rem Drag a model (STL, OBJ, STEP...) onto this file: Anneal writes a starter spec and opens it.
rem Drag the saved .json spec onto this file: Anneal optimizes the part and opens the report.
setlocal
set "HERE=%~dp0"
if not exist "%HERE%.venv\Scripts\python.exe" (
  echo Anneal is not installed yet. Run install_windows.bat first.
  pause & exit /b 1
)
if "%~1"=="" (
  echo Drag a model or a .json spec onto Anneal.bat.
  "%HERE%.venv\Scripts\python.exe" -m anneal --help
  pause & exit /b 0
)
"%HERE%.venv\Scripts\python.exe" -m anneal drop "%~1"
echo.
pause
