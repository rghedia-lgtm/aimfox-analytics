@echo off
:: Run this once as Administrator to register the Windows Task Scheduler job
:: It will start the Aimfox scheduler automatically on every system boot.

set TASK_NAME=AimfoxAnalyticsScheduler
set SCRIPT_PATH=D:\Smartlead-Automation\aimfox-analytics\scheduler.py
set PYTHON=python

echo Registering Windows Task: %TASK_NAME%

schtasks /create /tn "%TASK_NAME%" ^
  /tr "%PYTHON% \"%SCRIPT_PATH%\" --run-now --time 07:00 --interval 6" ^
  /sc ONLOGON ^
  /ru "%USERNAME%" ^
  /rl HIGHEST ^
  /f

if %ERRORLEVEL% == 0 (
    echo Task registered successfully!
    echo The scheduler will start automatically on next login.
    echo To start it now, run: start_scheduler.bat
) else (
    echo Failed to register task. Try running as Administrator.
)
pause
