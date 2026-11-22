@echo off
rem odw2json for Windows (Python 3.13).
rem   start.bat               -> converts .\input\<case>\*.pdf to .\output\<case>\*.json
rem   start.bat web           -> web UI on http://127.0.0.1:8000
rem   start.bat [CLI options] -> passed to the CLI, e.g. start.bat --input D:\sprawy --output D:\json
rem The first run creates .venv and installs requirements.txt (once; reinstalls when requirements.txt changes).
setlocal
cd /d "%~dp0"
set "PY=.venv\Scripts\python.exe"

if not exist "%PY%" (
  echo [odw2json] Tworze srodowisko .venv ...
  py -3.13 -m venv .venv 2>nul || python -m venv .venv
  if not exist "%PY%" (
    echo [odw2json] Nie znaleziono Pythona 3.13. Zainstaluj go z https://www.python.org/downloads/ i uruchom ponownie.
    exit /b 1
  )
)

fc /b requirements.txt .venv\requirements.installed >nul 2>&1
if errorlevel 1 (
  echo [odw2json] Instaluje zaleznosci ^(jednorazowo, kilka minut^) ...
  "%PY%" -m pip install --disable-pip-version-check -q -r requirements.txt || exit /b 1
  copy /y requirements.txt .venv\requirements.installed >nul
)

if /i "%~1"=="web" (
  echo [odw2json] Interfejs: http://127.0.0.1:8000  ^(Ctrl+C konczy^)
  "%PY%" -X utf8 -m web --host 127.0.0.1 --port 8000
  exit /b %errorlevel%
)

if not exist input mkdir input
if not exist output mkdir output
"%PY%" -X utf8 -m odw2json %*
