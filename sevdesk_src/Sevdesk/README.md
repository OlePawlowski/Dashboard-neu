# Rechnungsmodul 24-Stunden-Pflege

Rechnungsmodul für Vermittler von 24-Stunden-Pflege. Rechnungen werden an Kooperationspartner gestellt – Provision ca. 11 % des vereinbarten Gesamtbetrags.

## Funktionen

- **Rechnungsliste** mit Filter (Alle, Entwurf, Offen, Fällig, Festgeschrieben)
- **Neue Rechnung erstellen** mit:
  - **Kooperationspartner** (Rechnungsempfänger) – mit Standard-Provisionssatz
  - **Kunde** – für den die Vermittlung erfolgte
  - **Vereinbarter Gesamtbetrag** – Betrag zwischen Partner und Kunde
  - **Provisionssatz** – z.B. 11 % (je nach Partner)
  - Automatische Berechnung: Rechnungsbetrag = Gesamtbetrag × Provisionssatz
- **PDF-Export** – Rechnungen als PDF herunterladen
- **Datenpersistenz** – Speicherung im Browser (localStorage)

## Technologie

- React 19 + TypeScript
- Vite
- Tailwind CSS
- Zustand (State Management)
- jsPDF (PDF-Generierung)
- React Router
- date-fns

## Installation & Start

```bash
npm install
npm run dev
```

Die Anwendung läuft unter http://localhost:5173

## Build

```bash
npm run build
```

## CRM-Integration

Das Rechnungsmodul liegt unter `src/modules/invoice/` und ist als **Plug-in** für ein größeres 24-Stunden-Pflege-CRM gedacht.

**→ Siehe [INTEGRATION.md](./INTEGRATION.md)** für die vollständige Anleitung zur Integration (inkl. Schritte für die Cursor KI).

## Datenstruktur

- **Partner**: Kooperationspartner (Pflegeagentur) mit Adresse und Provisionssatz
- **Customer**: Kunde
- **Invoice**: Rechnung mit partnerId, customerId, agreedTotalAmount, commissionRate, commissionAmount
