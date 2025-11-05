# SignaturApp - Digitale Unterschriften-System

Ein vollständiges System für digitale Vertragsunterschriften mit HTML-Templates, PDF-Generierung, E-Mail-Versand und Touch-Signatur-Funktionalität.

## Features

✅ **HTML-Template-Management**: Laden Sie HTML-Vorlagen für Verträge hoch
✅ **Dynamische Variablen**: Füllen Sie Verträge automatisch mit Kundendaten
✅ **PDF-Konvertierung**: Automatische Umwandlung von HTML zu PDF
✅ **E-Mail-Versand**: Versenden Sie Verträge automatisch an Kunden
✅ **Touch-Signatur**: Kunden können mit dem Finger auf Touch-Geräten unterschreiben
✅ **Download & Speicherung**: Unterschriebene Verträge werden automatisch gespeichert

## Installation

### Voraussetzungen

- Python 3.8+
- wkhtmltopdf (für PDF-Generierung)

### macOS Installation von wkhtmltopdf

```bash
brew install wkhtmltopdf
```

### Ubuntu/Debian

```bash
sudo apt-get install wkhtmltopdf
```

### Windows

Laden Sie das Installationsprogramm von [wkhtmltopdf.org](https://wkhtmltopdf.org/downloads.html) herunter.

### Projekt-Setup

1. Repository klonen oder Dateien extrahieren
2. Abhängigkeiten installieren:

```bash
pip install -r requirements.txt
```

3. Umgebungsvariablen konfigurieren:

Erstellen Sie eine `.env` Datei:

```env
MAIL_USERNAME=ihre-email@gmail.com
MAIL_PASSWORD=ihr-app-passwort
```

**Wichtig für Gmail**: Sie müssen ein App-Passwort erstellen:
1. Gehen Sie zu Ihrem Google-Account
2. Sicherheit → 2-Faktor-Authentifizierung aktivieren
3. App-Passwörter → Neue App erstellen
4. Verwenden Sie das generierte Passwort in `.env`

4. Starten Sie die Anwendung:

```bash
python app.py
```

5. Öffnen Sie im Browser: http://localhost:5000

## Verwendung

### 1. Template hochladen

1. Erstellen Sie eine HTML-Datei mit Ihrem Vertragstext
2. Verwenden Sie `{variablenname}` für Variablen (z.B. `{vertragsnummer}`)
3. Fügen Sie den Platzhalter hinzu: `<div id="signature-placeholder"></div>`
4. Laden Sie die Datei im Dashboard hoch

**Beispiel-Template**:
```html
<html>
<body>
    <h1>Vertrag</h1>
    <p>Vertragsnummer: {vertragsnummer}</p>
    <p>Kunde: {kundenname}</p>
    <p>Betrag: {betrag}</p>
    
    <!-- WICHTIG: Dieser Platzhalter MUSS vorhanden sein -->
    <div id="signature-placeholder"></div>
</body>
</html>
```

### 2. Vertrag erstellen und versenden

1. Wählen Sie ein Template aus
2. Geben Sie Kundendaten ein
3. Erstellen Sie die Variablen im JSON-Format:
```json
{
  "vertragsnummer": "VERT-2024-001",
  "datum": "01.01.2024",
  "betrag": "1.000,00 €",
  "kundenname": "Max Mustermann"
}
```
4. Klicken Sie auf "Vertrag erstellen & versenden"

Der Vertrag wird automatisch:
- Zu PDF konvertiert
- Per E-Mail an den Kunden versendet

### 3. Kunden-Signatur

Der Kunde erhält eine E-Mail mit einem "Jetzt signieren"-Button:
- Der Vertrag öffnet sich im Browser
- Beim Scrollen zur Unterschrift erscheint der Button "Jetzt unterschreiben"
- Im Popup kann der Kunde mit Finger/Maus unterschreiben
- Nach dem Speichern wird der Vertrag automatisch im CRM gespeichert
- Der Kunde kann das unterschriebene PDF herunterladen

## Ordner-Struktur

```
SignaturApp/
├── app.py                  # Haupt-Flask-Anwendung
├── requirements.txt        # Python-Abhängigkeiten
├── templates/
│   ├── dashboard.html      # CRM-Dashboard
│   └── contracts/          # Contract-Templates
├── static/
│   ├── css/style.css       # Dashboard-Styling
│   └── js/dashboard.js     # Dashboard-Logik
├── uploads/                # Temporäre PDF-Dateien
├── signed_contracts/       # Unterschriebene Verträge
└── signaturapp.db          # SQLite-Datenbank
```

## API Endpoints

- `GET /` - Dashboard
- `GET /api/templates` - Liste aller Templates
- `POST /api/templates` - Template hochladen
- `GET /api/contracts` - Liste aller Verträge
- `POST /api/contracts` - Neuen Vertrag erstellen
- `GET /sign/<contract_id>` - Signatur-Page für Kunde
- `POST /api/signature` - Signatur speichern
- `GET /api/download/<contract_id>` - PDF herunterladen

## Datenbank-Modell

- **ContractTemplate**: Gespeicherte HTML-Templates
- **Contract**: Einzelne Verträge mit Kundendaten
- **Signature**: Gespeicherte Signaturen

## Anpassungen

### E-Mail-Server konfigurieren

In `app.py` können Sie die E-Mail-Konfiguration anpassen:

```python
app.config['MAIL_SERVER'] = 'smtp.example.com'
app.config['MAIL_PORT'] = 587
```

### PDF-Optionen anpassen

In der Funktion `html_to_pdf()` in `app.py`:

```python
options = {
    'page-size': 'A4',
    'margin-top': '0.75in',
    # Weitere Optionen...
}
```

## Fehlerbehebung

### wkhtmltopdf nicht gefunden

```bash
# Pfad setzen
export PATH=$PATH:/usr/local/bin
```

### E-Mail-Versand funktioniert nicht

- Überprüfen Sie die `.env` Datei
- Verwenden Sie ein App-Passwort für Gmail
- Testen Sie mit einem anderen SMTP-Server

### PDF-Generierung fehlt

- Stellen Sie sicher, dass wkhtmltopdf installiert ist
- Überprüfen Sie die Befehlszeilen-Anwendung: `wkhtmltopdf --version`

## Lizenz

Dieses Projekt ist für den privaten und kommerziellen Gebrauch freigegeben.

## Support

Bei Problemen oder Fragen, erstellen Sie ein Issue oder kontaktieren Sie den Entwickler.

