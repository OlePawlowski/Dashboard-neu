#!/bin/bash

echo "🚀 Starte SignaturApp..."
echo ""

# Prüfe ob wkhtmltopdf installiert ist
if ! command -v wkhtmltopdf &> /dev/null; then
    echo "⚠️  wkhtmltopdf nicht gefunden!"
    echo "📦 Installiere wkhtmltopdf..."
    
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS
        echo "🍎 macOS erkannt"
        if command -v brew &> /dev/null; then
            brew install wkhtmltopdf
        else
            echo "❌ Homebrew nicht gefunden. Bitte installieren Sie: https://brew.sh"
            exit 1
        fi
    elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
        # Linux
        echo "🐧 Linux erkannt"
        sudo apt-get update && sudo apt-get install -y wkhtmltopdf
    else
        echo "❌ Nicht unterstütztes System"
        exit 1
    fi
fi

# Prüfe Python-Version
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 nicht gefunden!"
    exit 1
fi

# Installiere Abhängigkeiten
if [ ! -f "venv" ]; then
    echo "📦 Installiere Python-Abhängigkeiten..."
    pip3 install -r requirements.txt
fi

# Prüfe .env Datei
if [ ! -f ".env" ]; then
    echo "⚠️  .env Datei nicht gefunden!"
    echo "📝 Erstelle .env aus env.example..."
    cp env.example .env
    echo ""
    echo "❗ Bitte bearbeiten Sie .env und fügen Sie Ihre E-Mail-Daten ein!"
    echo "Drücken Sie Enter zum Fortfahren..."
    read
fi

# Starte die Anwendung
echo ""
echo "✨ Starte SignaturApp..."
echo ""

python3 app.py

