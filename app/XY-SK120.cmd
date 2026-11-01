@echo off
rem XY-SK120 desktop version (no browser). API key: set XY_API_KEY or put it into apppi_key.txt
cd /d "%~dp0"
start "" pythonw desktop.py %*
