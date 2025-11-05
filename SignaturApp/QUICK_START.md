# Quick Start Guide

## ⚡ In 5 Minuten loslegen

### 1. Installation (macOS)

```bash
# Installieren Sie wkhtmltopdf
brew install wkhtmltopdf

# Installieren Sie Python-Abhängigkeiten
pip3 install -r requirements.txt
```

### 2. E-Mail konfigurieren

Erstellen Sie eine `.env` Datei:

```bash
MAIL_USERNAME=ihre-email@gmail.com
MAIL_PASSWORD=ihr-app-passwort
```

**Gmail App-Passwort erstellen:**
1. https://myaccount.google.com/apppasswords öffnen
2. App-Passwort erstellen
3. In `.env` eintragen

### 3. Starten

```bash
python3 app.py
```

Öffnen Sie: http://localhost:5000

## 📝 Erster Vertrag in 3 Schritten

### Schritt 1: Template hochladen

1. Im Dashboard auf "+ Template hochladen" klicken
2. Die Datei `templates/contracts/example.html` hochladen
3. Als Name "Beispiel-Vertrag" eingeben

### Schritt 2: Vertrag erstellen

1. Auf "Verträge" wechseln
2. "+ Neuen Vertrag erstellen" klicken
3. Folgende Daten eingeben:

**Template:** Beispiel-Vertrag

**Kundenname:** Max Mustermann

**Kunden-Email:** ihre-test-email@example.com

**Variablen:**
```json
{
  "vertragsnummer": "VERT-2024-001",
  "datum": "15.12.2024",
  "betrag": "1.500,00 €"
}
```

### Schritt 3: Senden!

Klicken Sie auf "Vertrag erstellen & versenden"

Der Vertrag wird automatisch:
- ✅ Zu PDF konvertiert
- ✅ Per E-Mail versendet
- ✅ Zur Signatur bereitgestellt

## ✍️ Signatur testen

1. Prüfen Sie die E-Mail des Kunden
2. Klicken Sie auf "Jetzt signieren"
3. Scrollen Sie im Vertrag nach unten
4. Klicken Sie auf "Jetzt unterschreiben"
5. Unterschreiben Sie mit der Maus/Touch
6. Klicken Sie auf "Speichern"
7. Laden Sie das unterschriebene PDF herunter

## 🎉 Fertig!

Ihr erstes digitales Dokument ist signiert und gespeichert!

---

**Tipp:** Öffnen Sie die Datenbank (`signaturapp.db`) um alle Verträge zu sehen:
```bash
sqlite3 signaturapp.db
SELECT * FROM contract;
```

