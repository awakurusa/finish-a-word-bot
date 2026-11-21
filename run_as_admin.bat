@echo off
rem Starts Finish the Word Assistant as Administrator (required when Roblox runs as admin).
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    set "PY=%~dp0.venv\Scripts\python.exe"
) else (
    set "PY=python"
)
powershell -NoProfile -Command "Start-Process -Verb RunAs -FilePath '%PY%' -ArgumentList '-m','finish_the_word' -WorkingDirectory '%~dp0'"
