@echo off
REM Daily database backup (schedule this with Windows Task Scheduler)
cd /d "%~dp0"
call venv\Scripts\activate
python backup.py
