@echo off
setlocal
title WWE GM 2000 - Launcher
cd /d "%~dp0"

echo.
echo   WWE GM 2000
echo   Women's division - WWF / WCW / ECW - resets to January 2000
echo.

rem --- the game is nothing without the harvested dataset ---
if not exist "data\gm2000.db" (
  echo   [!] data\gm2000.db is missing.
  echo       Rebuild it with:  cd harvester ^&^& python normalize.py ..\data\raw\roster_1980_2000.json ..\data\gm2000.db
  echo.
  pause
  exit /b 1
)

rem --- first run installs frontend packages ---
if not exist "frontend\node_modules" (
  echo   First run - installing frontend packages, this takes a minute...
  pushd frontend
  call npm install
  popd
  echo.
)

rem A leftover uvicorn from a previous run will hold 8010 and the new one dies
rem on bind, leaving the UI talking to stale code. Clear it first.
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:"LISTENING" ^| findstr ":8010 "') do (
  echo   Freeing port 8010 ^(was PID %%p^)
  taskkill /F /PID %%p >nul 2>&1
)
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:"LISTENING" ^| findstr ":5180 "') do (
  echo   Freeing port 5180 ^(was PID %%p^)
  taskkill /F /PID %%p >nul 2>&1
)

echo   Starting API on  http://localhost:8010
start "WWE GM 2000 - API" cmd /k "cd /d "%~dp0backend" && python -m uvicorn main:app --port 8010 --host 127.0.0.1"

rem Vite proxies /api to the backend, so the UI must not race ahead of it.
echo   Waiting for the API to come up...
set /a tries=0
:waitloop
set /a tries+=1
timeout /t 1 /nobreak >nul
curl -s -o nul http://127.0.0.1:8010/api/health && goto ready
if %tries% lss 30 goto waitloop
echo   [!] API did not respond after 30s - starting the UI anyway.
echo       Check the API window for the error.
goto startui

:ready
echo   API is up.

:startui
echo   Starting UI on   http://localhost:5180
start "WWE GM 2000 - UI" cmd /k "cd /d "%~dp0frontend" && npm run dev"

timeout /t 4 /nobreak >nul
start http://localhost:5180

echo.
echo   Running. Close the two command windows to stop the game.
echo.
timeout /t 6 /nobreak >nul
endlocal
