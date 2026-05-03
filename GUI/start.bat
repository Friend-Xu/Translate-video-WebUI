@echo off
cd /d "%~dp0\.."
set ROOT=%cd%

echo ==========================================
echo   Translate Video GUI - Starting...
echo ==========================================
echo.

:: Backend
echo [1/2] Starting backend server...
start "Translate Video - Backend" cmd /k "cd /d "%ROOT%" && .venv\Scripts\python.exe -m uvicorn GUI.server:app --host 127.0.0.1 --port 8000 && echo. && echo Backend stopped. Close this window."
echo   Backend: http://127.0.0.1:8000
echo   Logs:    %ROOT%\GUI\logs\server.log

:: Frontend
echo [2/2] Starting frontend dev server...
start "Translate Video - Frontend" cmd /k "cd /d "%ROOT%\GUI" && npm run dev -- --clearScreen=false && echo. && echo Frontend stopped. Close this window."
echo   Frontend: http://localhost:5173

:: Open browser
echo.
echo Opening browser...
start http://localhost:5173

echo.
echo ==========================================
echo   Both servers are starting!
echo   Close each window to stop that server.
echo ==========================================
