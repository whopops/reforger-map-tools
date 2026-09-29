@echo off
setlocal
cd /d "%~dp0.."
where python >nul 2>&1
if %ERRORLEVEL%==0 (
  python "py\run_export.py" %*
  exit /b %ERRORLEVEL%
)
where py >nul 2>&1
if %ERRORLEVEL%==0 (
  py -3 "py\run_export.py" %*
  exit /b %ERRORLEVEL%
)
echo python not found
exit /b 2
