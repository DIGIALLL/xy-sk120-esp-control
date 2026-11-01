@echo off
rem XY-SK120 web version (Edge/Chrome app window). API key: set XY_API_KEY or put it into apppi_key.txt
cd /d "%~dp0"
start "" pythonw server.py %*
