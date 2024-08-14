@echo off
start /B pythonw D:\Projekte\02-Privat\GPU-Monitor\monitor.py
echo GPU-Ueberwachung gestartet.
echo Das Fenster schliesst sich in 2 Sekunden...
timeout /t 2 /nobreak >nul