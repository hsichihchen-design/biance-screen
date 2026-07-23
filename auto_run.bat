@echo off
setlocal EnableExtensions

cd /d "%~dp0"
if errorlevel 1 exit /b 1

echo [%date% %time%] START

rem Find a real Python interpreter.
set "PYTHON_EXE="
set "USE_PY_LAUNCHER="

if exist "%USERPROFILE%\anaconda3\python.exe" set "PYTHON_EXE=%USERPROFILE%\anaconda3\python.exe"
if not defined PYTHON_EXE if exist "%USERPROFILE%\miniconda3\python.exe" set "PYTHON_EXE=%USERPROFILE%\miniconda3\python.exe"
if not defined PYTHON_EXE if exist "C:\ProgramData\anaconda3\python.exe" set "PYTHON_EXE=C:\ProgramData\anaconda3\python.exe"
if not defined PYTHON_EXE if exist "C:\ProgramData\miniconda3\python.exe" set "PYTHON_EXE=C:\ProgramData\miniconda3\python.exe"

if not defined PYTHON_EXE (
    where py.exe >nul 2>&1
    if not errorlevel 1 set "USE_PY_LAUNCHER=1"
)

if not defined PYTHON_EXE if not defined USE_PY_LAUNCHER (
    for /f "delims=" %%P in ('where python.exe 2^>nul') do (
        if not defined PYTHON_EXE set "PYTHON_EXE=%%P"
    )
)

if not defined PYTHON_EXE if not defined USE_PY_LAUNCHER (
    echo [ERROR] Python was not found.
    echo Install Python or edit PYTHON_EXE in this BAT file.
    exit /b 1
)

if defined USE_PY_LAUNCHER (
    echo [INFO] Python: py -3
) else (
    echo [INFO] Python: %PYTHON_EXE%
)

rem Update local repository first.
git pull origin main
if errorlevel 1 (
    echo [ERROR] git pull failed.
    exit /b 1
)

rem Run the scanner.
if defined USE_PY_LAUNCHER (
    py -3 update_data.py
) else (
    "%PYTHON_EXE%" update_data.py
)

if errorlevel 1 (
    echo [ERROR] update_data.py failed.
    exit /b 1
)

rem Commit only the intended project files.
git config user.email "bot@windows.local"
git config user.name "Windows Auto Bot"
git add uptrend_results.json update_data.py app.py requirements.txt auto_run.bat

git diff --cached --quiet
if not errorlevel 1 (
    echo [INFO] No changes to commit.
    exit /b 0
)

git commit -m "Scheduled 60-bar update: %date% %time%"
if errorlevel 1 (
    echo [ERROR] git commit failed.
    exit /b 1
)

git push origin main
if errorlevel 1 (
    echo [ERROR] git push failed.
    exit /b 1
)

echo [OK] Update completed.
exit /b 0
