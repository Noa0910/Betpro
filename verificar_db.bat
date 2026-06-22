@echo off
cd /d "%~dp0"
echo Verificando base de datos BetPro...
python check_db.py
echo.
pause
