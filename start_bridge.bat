@echo off
chcp 65001 >nul
title BeamNG RP Bridge
echo Starting BeamNG Bridge...
set "PYEXE="

where python >nul 2>&1 && set "PYEXE=python"
if not defined PYEXE where py >nul 2>&1 && set "PYEXE=py -3"

if not defined PYEXE (
  for %%V in (313 312 311 310 39 38) do (
    if exist "%LocalAppData%\Programs\Python\Python%%V\python.exe" set "PYEXE=%LocalAppData%\Programs\Python\Python%%V\python.exe"
  )
)

if not defined PYEXE (
  if exist "C:\Python313\python.exe" set "PYEXE=C:\Python313\python.exe"
  if exist "C:\Python312\python.exe" set "PYEXE=C:\Python312\python.exe"
  if exist "C:\Python311\python.exe" set "PYEXE=C:\Python311\python.exe"
  if exist "C:\Python310\python.exe" set "PYEXE=C:\Python310\python.exe"
)

if not defined PYEXE (
  echo [ERROR] Python not found.
  echo Install Python 3.10+ from python.org and check "Add Python to PATH".
  echo Then install deps: pip install beamngpy requests
  pause
  exit /b 1
)

echo Using: %PYEXE%
echo Installing/validating dependencies...
%PYEXE% -m ensurepip --upgrade
%PYEXE% -m pip install --user --upgrade pip
%PYEXE% -m pip install --user --disable-pip-version-check requests beamngpy
if errorlevel 1 (
  echo [ERROR] Failed to install dependencies.
  echo Try manually:
  echo   %PYEXE% -m pip install --user requests beamngpy
  pause
  exit /b 1
)
%PYEXE% beamng_bridge.py
pause
