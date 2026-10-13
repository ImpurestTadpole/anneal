@echo off
rem Opens the Anneal window with a console beside it (useful if something goes wrong).
rem Normal use: the Anneal icon on the desktop or in the Start menu.
setlocal
set "HERE=%~dp0"
if not exist "%HERE%.venv\Scripts\python.exe" (
  echo Anneal is not installed yet. Run install_windows.bat first.
  pause & exit /b 1
)
"%HERE%.venv\Scripts\python.exe" -m anneal app
if errorlevel 1 (
  echo.
  echo Anneal stopped with an error. The report is in:
  echo   %USERPROFILE%\Anneal Projects\anneal-startup.log
  echo To check the installation, run:  "%HERE%.venv\Scripts\python.exe" -m anneal doctor
  pause
)
