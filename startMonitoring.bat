@echo off
start /B pythonw monitor.py
if %errorlevel% equ 0 (
    echo GPU-Ueberwachung gestartet oder laeuft bereits.
) else (
    echo Fehler beim Starten der GPU-Ueberwachung.
)
echo Das Fenster schliesst sich in 2 Sekunden...
timeout /t 2 /nobreak >nul