# Projekt-Struktur

## 📁 Dateien und Ordner

```
SignaturApp/
│
├── 🐍 Python Backend
│   ├── app.py                      # Haupt-Flask-Anwendung
│   └── requirements.txt            # Python-Abhängigkeiten
│
├── 🌐 Frontend Templates
│   ├── templates/
│   │   ├── dashboard.html          # CRM-Dashboard Interface
│   │   └── contracts/
│   │       └── example.html        # Beispiel-Vertrag (Template)
│   │
│   └── static/
│       ├── css/
│       │   └── style.css           # Dashboard Styling
│       └── js/
│           └── dashboard.js        # Dashboard Funktionalität
│
├── 📄 Dokumentation
│   ├── README.md                   # Haupt-Dokumentation
│   ├── INSTALLATION.md            # Detaillierte Installation
│   ├── QUICK_START.md             # Schnellstart-Anleitung
│   └── PROJECT_STRUCTURE.md       # Diese Datei
│
├── ⚙️ Konfiguration
│   ├── .gitignore                  # Git Ignore-Regeln
│   ├── env.example                 # E-Mail-Konfiguration Vorlage
│   └── .env                        # Ihre E-Mail-Konfiguration (wird erstellt)
│
├── 🚀 Skripte
│   └── start.sh                    # Start-Skript (macOS/Linux)
│
├── 💾 Datenbank (wird erstellt)
│   └── signaturapp.db              # SQLite Datenbank
│
├── 📂 Temporäre Ordner (werden erstellt)
│   ├── uploads/                    # Temporäre PDFs
│   └── signed_contracts/           # Unterschriebene Verträge
```

## 🔄 Workflow

### 1. Template erstellen
```
Benutzer → Dashboard → Template hochladen
                ↓
           HTML-Datei
                ↓
        ContractTemplate Tabelle
```

### 2. Vertrag erstellen
```
Benutzer → Dashboard → Vertrag erstellen
                ↓
       Kundendaten + Variablen
                ↓
       HTML mit Variablen füllen
                ↓
        PDF-Generierung
                ↓
        E-Mail versenden
                ↓
         Contract Tabelle
```

### 3. Signatur-Prozess
```
Kunde → E-Mail → "Jetzt signieren"
           ↓
     Signatur-Page
           ↓
    Touch/Maus Signatur
           ↓
   Signatur speichern
           ↓
 PDF mit Signatur generieren
           ↓
   Download + CRM-Speicherung
```

## 🗄️ Datenbank-Schema

### ContractTemplate
- `id` (Primary Key)
- `name` - Name des Templates
- `filename` - Original-Dateiname
- `content` - HTML-Inhalt
- `created_at` - Erstellungsdatum

### Contract
- `id` (Primary Key) - Einzigartige Contract-ID
- `template_id` - Foreign Key zu ContractTemplate
- `customer_name` - Name des Kunden
- `customer_email` - E-Mail des Kunden
- `variables` - JSON-String mit Variablen
- `status` - pending/sent/signed
- `pdf_path` - Pfad zum generierten PDF
- `signed_pdf_path` - Pfad zum unterschriebenen PDF
- `created_at` - Erstellungsdatum
- `signed_at` - Unterschriftsdatum

### Signature
- `id` (Primary Key)
- `contract_id` - Foreign Key zu Contract
- `signature_data` - Base64-kodierte Signatur
- `created_at` - Erstellungsdatum

## 🔌 API Endpoints

### GET /
Das Dashboard-Interface

### API Endpoints

**Templates:**
- `GET /api/templates` - Liste aller Templates
- `POST /api/templates` - Neues Template hochladen

**Contracts:**
- `GET /api/contracts` - Liste aller Verträge
- `POST /api/contracts` - Neuen Vertrag erstellen

**Signatur:**
- `GET /sign/<contract_id>` - Signatur-Page (für Kunde)
- `POST /api/signature` - Signatur speichern
- `GET /api/download/<contract_id>` - PDF herunterladen

## 🎨 Tech Stack

- **Backend**: Flask (Python)
- **Datenbank**: SQLite (SQLAlchemy)
- **PDF-Generierung**: wkhtmltopdf
- **E-Mail**: Flask-Mail
- **Frontend**: Vanilla JavaScript, HTML5, CSS3
- **Signatur**: HTML5 Canvas mit Touch-Support

## 🔒 Sicherheit

- Secret Keys werden automatisch generiert
- Sichere Datei-Uploads mit Werkzeug
- SQL-Injection-Schutz durch SQLAlchemy ORM
- Base64-kodierte Signatur-Daten

## 📊 Status-Bezeichnungen

- **pending**: Vertrag erstellt, noch nicht versendet
- **sent**: E-Mail versendet, wartet auf Signatur
- **signed**: Unterschrieben und gespeichert

