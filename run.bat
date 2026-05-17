@echo off
setlocal

echo Starting Applying Bot Local Environment...
echo.

REM Each spawned window has its title forced via `title ...` AS THE FIRST
REM command — so taskkill can find it later by WINDOWTITLE filter regardless
REM of what the inner process does.

echo [1/3] Launching Backend Server (FastAPI)...
start "Applying Bot Backend" cmd /k "title Applying Bot Backend && venv\Scripts\activate.bat & python server.py"

echo [2/3] Waiting for backend to respond on http://127.0.0.1:8000 ...
:waitloop
powershell -NoProfile -Command ^
    "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/api/login-status' -UseBasicParsing -TimeoutSec 2; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }"
if errorlevel 1 (
    timeout /t 1 /nobreak >nul
    goto waitloop
)
echo       Backend is up.
echo.

echo [3/3] Launching Frontend Server (Vite)...
start "Applying Bot Frontend" cmd /k "title Applying Bot Frontend && cd frontend & npm run dev"

echo.
echo ==================================================
echo Both servers are running in separate windows.
echo.
echo Backend  : http://127.0.0.1:8000
echo Frontend : http://localhost:5173
echo ==================================================
echo.
echo Press Ctrl+C in THIS window to stop ALL services
echo (backend and frontend windows will be closed automatically).
echo.

REM PowerShell handles the wait + cleanup. try/finally fires on Ctrl+C, so the
REM taskkills run BEFORE PowerShell exits — meaning the child windows are gone
REM before the .bat resumes. `start` detaches the spawned cmd windows with no
REM parent-child relationship, so killing them by window title (with /T to
REM kill the whole tree, including python.exe and node.exe) is the only
REM reliable handle we have.
powershell -NoProfile -Command ^
    "try { while ($true) { Start-Sleep -Seconds 60 } } finally { Write-Host '' ; Write-Host 'Stopping services...' ; & taskkill /F /FI 'WINDOWTITLE eq Applying Bot Backend*' /T 2>$null | Out-Null ; & taskkill /F /FI 'WINDOWTITLE eq Applying Bot Frontend*' /T 2>$null | Out-Null ; Write-Host 'Stopped.' }"

endlocal
