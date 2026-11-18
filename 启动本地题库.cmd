@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  python -X utf8 "%~dp0scripts\local_site.py" --open
) else (
  py -3 -X utf8 "%~dp0scripts\local_site.py" --open
)
if errorlevel 1 pause
