@echo off
REM Starts the Hospital Analytics server. Other computers open http://SERVER-IP:8501
cd /d "%~dp0"
call venv\Scripts\activate
streamlit run app.py
pause
