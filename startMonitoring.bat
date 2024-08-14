@echo off
start /B pythonw monitor.py
echo GPU-Ueberwachung gestartet.
echo Das Fenster schliesst sich in 2 Sekunden...
timeout /t 2 /nobreak >nul