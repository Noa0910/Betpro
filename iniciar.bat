@echo off
cd /d "%~dp0"
python -m pip install -r requirements.txt -q
python seed.py
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
