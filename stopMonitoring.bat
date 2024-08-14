@echo off
setlocal enabledelayedexpansion

if not exist gpu_monitor.pid (
    echo GPU-Ueberwachung laeuft nicht.
    goto :END
)

set /p PID=<gpu_monitor.pid
echo Versuche, GPU-Ueberwachung (PID: !PID!) zu beenden...

echo. > stop_monitor.txt

timeout /t 5 /nobreak >nul

taskkill /PID !PID! /F

if !ERRORLEVEL! EQU 0 (
    echo GPU-Ueberwachung erfolgreich beendet.
    del gpu_monitor.pid
) else (
    echo Konnte GPU-Ueberwachung nicht beenden. Moeglicherweise laeuft sie bereits nicht mehr.
)

if exist stop_monitor.txt del stop_monitor.txt

:END
echo.
echo Das Fenster schliesst sich in 2 Sekunden...
timeout /t 2 /nobreak >nul