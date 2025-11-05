# 📋 Dienstleistungsvertrag-System

## 🎯 Übersicht

Das Dienstleistungsvertrag-System ermöglicht es, automatisch gefüllte Dienstleistungsverträge zu erstellen, als PDF zu generieren und zur digitalen Signatur über Zoho Sign zu versenden.

## 🏗️ Architektur

### Datenbankmodelle

#### Customer (erweitert)
```python
# Neue Felder für Verträge:
street_address     # Straße und Hausnummer
postal_code        # PLZ
city              # Ort
contract_number   # Vertragsnummer
monthly_rate      # Monatstarif
daily_rate        # Tagessatz
contract_data_json # Flexible Vertragsdaten (JSON)
```

#### Kooperationspartner (erweitert)
```python
# Vertragsspezifische Felder:
company_name         # Firmenname
street_address       # Vollständige Adresse
phone               # Telefonnummer
identification_number # Identifikationsnummer
commercial_register  # Handelsregisternummer
vat_id              # USt-IdNr.
managing_director   # Name Geschäftsführer
emergency_phone     # Notfalltelefon (24h)
partner_company     # Partnerfirma für Bedarfsermittlung
contract_data_json  # Zusätzliche Daten (JSON)
```

#### Dienstleistungsvertrag (neu)
```python
id                    # Eindeutige ID
customer_id           # Verknüpfung zum Kunden
kooperationspartner_id # Verknüpfung zum Kooperationspartner
contract_number       # Vertragsnummer
contract_date         # Vertragsdatum
monthly_rate          # Monatstarif
daily_rate           # Tagessatz
contract_location     # Ort der Unterschrift
status               # draft, sent, signed, completed, expired, declined
zoho_request_id      # Zoho Sign Request ID
pdf_filename         # Generierte PDF-Datei
signed_pdf_filename  # Signierte PDF-Datei
contract_data_json   # Zusätzliche Daten (JSON)
created_at           # Erstellungsdatum
updated_at           # Letzte Aktualisierung
```

## 🔌 API-Endpunkte

### Dienstleistungsverträge

#### Liste abrufen/erstellen
```http
GET /api/dienstleistungsvertraege
POST /api/dienstleistungsvertraege
```

#### Einzelne Verträge verwalten
```http
GET /api/dienstleistungsvertraege/<id>
PUT /api/dienstleistungsvertraege/<id>
DELETE /api/dienstleistungsvertraege/<id>
```

#### PDF generieren
```http
POST /api/dienstleistungsvertraege/<id>/generate-pdf
```

**Response:**
```json
{
  "success": true,
  "pdf_base64": "data:application/pdf;base64,...",
  "filename": "dienstleistungsvertrag_12345_20241025_123456.pdf"
}
```

#### Zur Signatur senden
```http
POST /api/dienstleistungsvertraege/<id>/send-for-signature
```

**Response:**
```json
{
  "success": true,
  "zoho_request_id": "abc123def456",
  "response": {...},
  "contract": {...}
}
```

### Zoho Sign Webhook
```http
POST /webhook/zoho-sign
```

Verarbeitet Status-Updates von Zoho Sign und aktualisiert automatisch den Vertragsstatus.

## 🔄 Workflow

### 1. Kunde anlegen
```json
POST /api/customers
{
  "name": "Max Mustermann",
  "email": "max@example.com",
  "phone": "+49 123 456789",
  "street_address": "Musterstraße 123",
  "postal_code": "12345",
  "city": "Musterstadt"
}
```

### 2. Kooperationspartner erstellen
```json
POST /api/kooperationspartner
{
  "name": "HelpCare GmbH",
  "email": "info@helpcare.de",
  "company_name": "HelpCare GmbH",
  "street_address": "Hauptstraße 1, 12345 Berlin",
  "phone": "+49 30 12345678",
  "identification_number": "DE123456789",
  "commercial_register": "HRB 12345",
  "vat_id": "DE123456789",
  "managing_director": "Dr. Max Mustermann",
  "emergency_phone": "+49 30 87654321",
  "partner_company": "HelpCare Partner GmbH"
}
```

### 3. Dienstleistungsvertrag erstellen
```json
POST /api/dienstleistungsvertraege
{
  "customer_id": 1,
  "kooperationspartner_id": 1,
  "contract_number": "DLV-2024-001",
  "monthly_rate": 2500.00,
  "daily_rate": 83.33,
  "contract_location": "Berlin"
}
```

### 4. PDF generieren
```http
POST /api/dienstleistungsvertraege/1/generate-pdf
```

### 5. Zur Signatur senden
```http
POST /api/dienstleistungsvertraege/1/send-for-signature
```

## 📄 Template-Variablen

Das HTML-Template `templates/dienstleistungsvertrag.html` wird automatisch mit folgenden Variablen befüllt:

| Platzhalter | Datenquelle | Beschreibung |
|-------------|-------------|--------------|
| `[Auftragsnummer]` | `contract.contract_number` | Vertragsnummer |
| `[Datum]` | `contract.contract_date` | Vertragsdatum |
| `[Vorname Name]` | `customer.name` | Kundenname |
| `[Straße Hausnummer]` | `customer.street_address` | Kundenadresse |
| `[PLZ Ort]` | `customer.postal_code + city` | PLZ und Ort |
| `[Telefon]` | `customer.phone` | Kundentelefon |
| `[E-Mail]` | `customer.email` | Kunden-E-Mail |
| `[Firmenname]` | `partner.company_name` | Firmenname |
| `[Adresse]` | `partner.street_address` | Partneradresse |
| `[Telefon]` | `partner.phone` | Partnertelefon |
| `[E-Mail]` | `partner.email` | Partner-E-Mail |
| `[Identifikationsnummer]` | `partner.identification_number` | Identifikationsnummer |
| `[Handelsregisternummer]` | `partner.commercial_register` | Handelsregister |
| `[Umsatzsteuer-Identifikationsnummer]` | `partner.vat_id` | USt-IdNr. |
| `[Name Geschäftsführer]` | `partner.managing_director` | Geschäftsführer |
| `[Notfalltelefon]` | `partner.emergency_phone` | Notfalltelefon |
| `[Betrag]` | `contract.monthly_rate` | Monatstarif |
| `[Tagessatz]` | `contract.daily_rate` | Tagessatz |
| `[Ort]` | `contract.contract_location` | Unterschriftsort |
| `[Partnerfirma]` | `partner.partner_company` | Partnerfirma |

## 🔧 Konfiguration

### Umgebungsvariablen

```bash
# Zoho Sign Integration
ZOHO_CLIENT_ID=1000.VHXZNY0MN8Z6X8AJNMWEFNBUUMVRDI
ZOHO_CLIENT_SECRET=b0f53375b7656f069f767718d3471900244f7a7aa7
ZOHO_SIGN_REFRESH_TOKEN=1000.5ebd72742f4979083e55e72890aae845.045354dd1433db17f4d246b3608103e6
```

### Docker-Abhängigkeiten

Das System benötigt folgende System-Bibliotheken für WeasyPrint:
- `libpango-1.0-0`
- `libpangoft2-1.0-0`
- `libgobject-2.0-0`
- `libglib2.0-0`
- `libcairo2`
- `libgdk-pixbuf-2.0-0`
- `libffi-dev`
- `shared-mime-info`

## 🚀 Deployment

### Docker-Compose
```bash
docker-compose down && docker-compose up --build -d
```

### System-Status prüfen
```bash
# Container-Status
docker ps

# WeasyPrint-Test
docker exec helpcare-dashboard python -c "import weasyprint; print('✅ WeasyPrint OK')"

# API-Test
curl http://localhost:8000/api/me
```

## 📊 Status-Tracking

### Vertragsstatus
- `draft` - Entwurf
- `sent` - Zur Signatur gesendet
- `signed` - Unterschrieben
- `completed` - Abgeschlossen
- `expired` - Abgelaufen
- `declined` - Abgelehnt

### Automatische Updates
Der Status wird automatisch über den Zoho Sign Webhook aktualisiert:
- Bei Signatur-Abschluss: `signed`
- Bei Ablauf: `expired`
- Bei Ablehnung: `declined`

## 🔍 Troubleshooting

### WeasyPrint-Probleme
```bash
# System-Bibliotheken prüfen
docker exec helpcare-dashboard ldd /usr/local/lib/python3.11/site-packages/weasyprint/text/ffi.py

# WeasyPrint-Test
docker exec helpcare-dashboard python -c "from weasyprint import HTML; print('OK')"
```

### Zoho Sign-Probleme
```bash
# Token-Status prüfen
curl http://localhost:8000/api/debug/zoho-token
```

### Logs prüfen
```bash
docker logs helpcare-dashboard --tail 50
```

## 📝 Beispiel-Frontend-Integration

```javascript
// Dienstleistungsvertrag erstellen
async function createContract(customerId, partnerId, contractData) {
  const response = await fetch('/api/dienstleistungsvertraege', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      customer_id: customerId,
      kooperationspartner_id: partnerId,
      ...contractData
    })
  });
  return await response.json();
}

// PDF generieren
async function generatePDF(contractId) {
  const response = await fetch(`/api/dienstleistungsvertraege/${contractId}/generate-pdf`, {
    method: 'POST'
  });
  const data = await response.json();
  
  if (data.success) {
    // PDF in neuem Tab öffnen
    const blob = await fetch(data.pdf_base64).then(r => r.blob());
    const url = URL.createObjectURL(blob);
    window.open(url, '_blank');
  }
}

// Zur Signatur senden
async function sendForSignature(contractId) {
  const response = await fetch(`/api/dienstleistungsvertraege/${contractId}/send-for-signature`, {
    method: 'POST'
  });
  return await response.json();
}
```

## ✅ System-Status

- ✅ Datenbankmodelle implementiert
- ✅ API-Endpunkte funktionsfähig
- ✅ PDF-Generierung mit WeasyPrint
- ✅ Zoho Sign Integration
- ✅ Webhook-System für Status-Updates
- ✅ Docker-Container läuft stabil
- ✅ Alle Abhängigkeiten installiert

Das System ist produktionsbereit! 🎉

