@echo off
title BeamNG RP Relay Server
echo [1/2] Killing previous Node processes...
taskkill /F /IM node.exe >nul 2>&1
echo [2/2] Starting Relay Server on port 3000...
node relay-server.cjs
pause
