#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

# Create venv if missing
if [ ! -d .venv ]; then
    python3 -m venv .venv
    echo "Created .venv"
fi

# Activate and install
. .venv/bin/activate
pip install -r requirements.txt -q

# Create .env from template if missing
if [ ! -f .env ]; then
    cp .env.example .env
    echo "Created .env — edit it to set API_KEY and ALLOWED_MODELS"
fi

echo "Setup done. Run: source .venv/bin/activate && python proxy.py"
