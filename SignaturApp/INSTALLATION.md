# Installations-Anleitung für SignaturApp

## Schnellstart für macOS

### 1. Homebrew installieren (falls noch nicht vorhanden)

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

### 2. wkhtmltopdf installieren

```bash
brew install wkhtmltopdf
```

### 3. Python-Abhängigkeiten installieren

```bash
pip3 install -r requirements.txt
```

### 4. E-Mail-Konfiguration

Erstellen Sie eine `.env` Datei:

```bash
cp env.example .env
```

Bearbeiten Sie `.env` und fügen Sie Ihre E-Mail-Daten ein:

```env
MAIL_USERNAME=ihre-email@gmail.com
MAIL_PASSWORD=ihr-app-passwort
```

**Für Gmail - App-Passwort erstellen:**
1. Gehen Sie zu https://myaccount.google.com/apppasswords
2. Erstellen Sie ein neues App-Passwort
3. Verwenden Sie dieses Passwort in der `.env` Datei

### 5. Anwendung starten

```bash
python3 app.py
```

Die Anwendung läuft nun auf: http://localhost:5000

## Schnellstart für Ubuntu/Debian

### 1. System-Updates und Abhängigkeiten

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-pip wkhtmltopdf
```

### 2. Python-Abhängigkeiten installieren

```bash
pip3 install -r requirements.txt
```

### 3. E-Mail-Konfiguration

```bash
cp env.example .env
nano .env
```

Fügen Sie Ihre E-Mail-Daten ein.

### 4. Anwendung starten

```bash
python3 app.py
```

## Windows Installation

### 1. Python installieren

Laden Sie Python 3.8+ von https://www.python.org/ herunter und installieren Sie es.

### 2. wkhtmltopdf installieren

- Laden Sie die Windows-Version von https://wkhtmltopdf.org/downloads.html herunter
- Führen Sie das Installationsprogramm aus
- Fügen Sie wkhtmltopdf zum System-PATH hinzu

### 3. Repository

```bash
cd SignaturApp
pip install -r requirements.txt
```

### 4. E-Mail konfigurieren

Erstellen Sie eine `.env` Datei mit Ihren E-Mail-Daten.

### 5. Starten

```bash
python app.py
```

## Erste Schritte

1. Öffnen Sie http://localhost:5000 im Browser
2. Klicken Sie auf "Template hochladen"
3. Laden Sie das Beispiel-Template hoch: `templates/contracts/example.html`
4. Klicken Sie auf "Neuen Vertrag erstellen"
5. Wählen Sie ein Template aus und füllen Sie die Daten aus
6. Der Vertrag wird automatisch versendet!

## Troubleshooting

### wkhtmltopdf nicht gefunden

**macOS:**
```bash
brew reinstall wkhtmltopdf
```

**Linux:**
```bash
which wkhtmltopdf
# Falls nicht gefunden:
sudo apt-get install --reinstall wkhtmltopdf
```

### E-Mail funktioniert nicht

Stellen Sie sicher, dass:
- `.env` Datei existiert
- Gmail App-Passwort korrekt ist
- 2-Faktor-Authentifizierung bei Gmail aktiviert ist

### Port bereits belegt

Ändern Sie den Port in `app.py`:

```python
app.run(debug=True, port=5001)  # Verwenden Sie einen anderen Port
```

## Entwicklung

Für Entwicklung mit Auto-Reload:

```bash
flask run --debug
```

## Produktion

Für den produktiven Einsatz verwenden Sie gunicorn:

```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 app:app
```

