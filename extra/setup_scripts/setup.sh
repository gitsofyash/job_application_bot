#!/bin/bash
# Job Application Bot Setup Script
# Run: bash setup.sh

set -e

echo "╔═══════════════════════════════════════╗"
echo "║ Job Application Bot Setup             ║"
echo "╚═══════════════════════════════════════╝"
echo ""

# Check Python version
python_version=$(python --version 2>&1 | awk '{print $2}')
echo "✓ Python version: $python_version"

# Create virtual environment
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python -m venv venv
    echo "✓ Virtual environment created"
else
    echo "✓ Virtual environment already exists"
fi

# Activate virtual environment
source venv/bin/activate
echo "✓ Virtual environment activated"

# Install dependencies
echo "Installing dependencies..."
pip install --upgrade pip > /dev/null 2>&1
pip install -r requirements.txt > /dev/null 2>&1
echo "✓ Dependencies installed"

# Install Playwright browsers
echo "Installing Playwright browsers..."
playwright install chromium > /dev/null 2>&1
echo "✓ Playwright chromium installed"

# Setup .env
if [ ! -f ".env" ]; then
    echo "Creating .env from .env.example..."
    cp .env.example .env
    echo "✓ .env created (edit with your settings)"
else
    echo "✓ .env already exists"
fi

# Verify data files
if [ ! -f "data/base_resume.json" ]; then
    echo "⚠️  Warning: data/base_resume.json not found"
else
    echo "✓ data/base_resume.json verified"
fi

if [ ! -f "data/user_profile.json" ]; then
    echo "⚠️  Warning: data/user_profile.json not found"
else
    echo "✓ data/user_profile.json verified"
fi

echo ""
echo "╔═══════════════════════════════════════╗"
echo "║ Setup Complete!                       ║"
echo "╚═══════════════════════════════════════╝"
echo ""
echo "Next steps:"
echo "1. Edit .env with your LLM settings"
echo "2. Start Ollama: ollama serve (if using OLLAMA)"
echo "3. Run: python main.py --url 'https://...'"
echo ""
echo "For more info, see README.md"
