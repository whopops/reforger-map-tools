@echo off
rem Reforger Map Tools: double-click to open the desktop app.
rem The first time it makes a private Python environment in .venv\ beside this file and installs what the app needs
rem (requirements.txt: PySide6, numpy, Pillow, SciPy; a few minutes). After that it just opens the window. It installs
rem again by itself whenever requirements.txt changes. Delete .venv\ to start over.
rem   "Reforger Map Tools.bat" --console    open the window with a console beside it, to see any error
setlocal
cd /d "%~dp0"
set "VENV=%~dp0.venv"
set "VPY=%VENV%\Scripts\python.exe"

if exist "%VPY%" goto packages

echo Reforger Map Tools: first start, setting up Python for the app...
set "PY="
call :try py -3
if not defined PY call :try python
if not defined PY call :try python3
if not defined PY goto nopython
echo Using %PY%
%PY% -m venv "%VENV%"
if errorlevel 1 goto venvfail

:packages
fc /b "requirements.txt" "%VENV%\rmt-requirements.txt" >nul 2>nul
if not errorlevel 1 goto launch
echo Installing what the app needs: PySide6, numpy, Pillow, SciPy. The first time takes a few minutes...
"%VPY%" -m pip install --disable-pip-version-check --upgrade pip >nul
"%VPY%" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto pipfail
copy /y "requirements.txt" "%VENV%\rmt-requirements.txt" >nul

:launch
if /i "%~1"=="--console" goto console
start "" "%VENV%\Scripts\pythonw.exe" "%~dp0rmt_gui.py"
exit /b 0

:console
"%VPY%" "%~dp0rmt_gui.py"
pause
exit /b

:try
rem A real Python 3.10 or newer? (The Microsoft Store "python" shortcut without Python installed fails this.)
%* -c "import sys, venv; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if not errorlevel 1 set "PY=%*"
exit /b

:nopython
echo.
echo Python 3.10 or newer was not found.
echo Install it from https://www.python.org/downloads/ (tick "Add python.exe to PATH"),
echo then double-click this file again.
pause
exit /b 1

:venvfail
echo.
echo Could not make the Python environment in %VENV%.
pause
exit /b 1

:pipfail
echo.
echo Installing the packages failed (see above). Check the internet connection and double-click this file again.
pause
exit /b 1
