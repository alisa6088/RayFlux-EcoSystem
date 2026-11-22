@echo off
cd /d "%~dp0"
echo Starting RayFlux Studio Control Center...
".venv\Scripts\python.exe" rayflux_studio.py
pause
