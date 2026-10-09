@echo off
cd /d "%~dp0"
py resistance_logger.py
if errorlevel 1 pause
