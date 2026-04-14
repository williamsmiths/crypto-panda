@echo off
setlocal

echo [1/3] Installing Node dependencies...
call npm install
if errorlevel 1 goto :error

echo [2/3] Building Electron Windows package...
call npm run build:win
if errorlevel 1 goto :error

echo [3/3] Build completed. Check dist\ for artifacts.
goto :eof

:error
echo Build failed.
exit /b 1

endlocal

