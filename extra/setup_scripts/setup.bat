@echo off
REM Job Application Bot Setup Script (Windows)
REM Run: setup.bat

setlocal enabledelayedexpansion

echo.
echo ╔═══════════════════════════════════════╗
echo ║ Job Application Bot Setup (Windows)   ║
echo ╚═══════════════════════════════════════╝
echo.

REM Check Python version
python --version > nul 2>&1
if errorlevel 1 (
    echo ✗ Python not found. Install Python 3.10+ from python.org
    pause
    exit /b 1
)

for /f "tokens=2" %%i in ('python --version 2^>^&1') do set python_version=%%i
echo ✓ Python version: %python_version%

REM Create virtual environment
if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
    echo ✓ Virtual environment created
) else (
    echo ✓ Virtual environment already exists
)

REM Activate virtual environment
call venv\Scripts\activate.bat
echo ✓ Virtual environment activated

REM Install dependencies
echo Installing dependencies...
pip install --upgrade pip > nul 2>&1
pip install -r requirements.txt > nul 2>&1
echo ✓ Dependencies installed

REM Install Playwright browsers
echo Installing Playwright browsers...
playwright install chromium > nul 2>&1
echo ✓ Playwright chromium installed

REM Setup .env
if not exist ".env" (
    echo Creating .env from .env.example...
    copy .env.example .env > nul
    echo ✓ .env created (edit with your settings)
) else (
    echo ✓ .env already exists
)

REM Verify data files
if not exist "data\base_resume.json" (
    echo ⚠️  Warning: data\base_resume.json not found
) else (
    echo ✓ data\base_resume.json verified
)

if not exist "data\user_profile.json" (
    echo ⚠️  Warning: data\user_profile.json not found
) else (
    echo ✓ data\user_profile.json verified
)

echo.
echo ╔═══════════════════════════════════════╗
echo ║ Setup Complete!                       ║
echo ╚═══════════════════════════════════════╝
echo.
echo Next steps:
echo 1. Edit .env with your LLM settings
echo 2. Start Ollama: ollama serve (if using OLLAMA)
echo 3. Run: python main.py --url "https://..."
echo.
echo For more info, see README.md
echo.
pause
