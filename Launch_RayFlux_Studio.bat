@echo off
cd /d "%~dp0"
echo Starting RayFlux Studio Control Center...
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" rayflux_studio.py
) else (
    python rayflux_studio.py
)
pause
