@echo off
REM ============================================================
REM  Task B unit tests (transfer flow + simulated payment)
REM  Covers apps.transfers (32 cases) + apps.payments (11 cases)
REM  = 43 test cases in total
REM  Env: Windows + uv + Django (SQLite in-memory test DB)
REM ============================================================
chcp 65001 >nul
cd /d "%~dp0"

echo Running Task B unit tests...
echo.

uv run python manage.py test apps.transfers apps.payments -v 2

echo.
echo Exit code: %ERRORLEVEL%
