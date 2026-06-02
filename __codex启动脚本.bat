@echo off
rem Auto-relaunch in Windows Terminal if not already running there
if not defined WT_SESSION (
    wt.exe --title "Claude Code" -d "%CD%" cmd /k "%~f0"
    exit /b
)

chcp 65001 >nul
title Codex

set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
set LANG=zh_CN.UTF-8
set LC_ALL=zh_CN.UTF-8

echo [Launch] Starting Codex...
echo.
Codex
