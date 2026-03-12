# Rechnungsmodul – Integration ins 24-Stunden-Pflege-CRM

Dieses Rechnungsmodul ist als **Plug-in** für ein größeres CRM-System gedacht. Die Cursor KI kann den Ordner `src/modules/invoice/` in ein bestehendes Projekt integrieren.

---

## 1. Ordnerstruktur (selbstständig)

```
src/modules/invoice/
├── index.ts              # Öffentliche API – hier importieren
├── types.ts               # Invoice, Partner, Customer, etc.
├── config.ts              # Firmendaten (anpassen!)
├── components/
│   └── StatusBadge.tsx
├── pages/
│   ├── InvoiceList.tsx    # Rechnungsübersicht
│   └── NewInvoice.tsx     # Neue Rechnung / Bearbeiten
├── store/
│   └── invoiceStore.ts    # Zustand-Store (lokal)
└── utils/
    ├── pdfExport.ts       # PDF-Generierung
    └── invoiceCalculations.ts
```

---

## 2. Integration – Schritte für die Cursor KI

### Schritt 1: Modul kopieren

Den gesamten Ordner `src/modules/invoice/` in das Zielprojekt kopieren (z.B. unter `src/modules/invoice/` oder `src/features/invoice/`).

### Schritt 2: Abhängigkeiten prüfen

Das Modul benötigt:

- `react`, `react-dom`, `react-router-dom`
- `zustand` (mit `persist` Middleware)
- `jspdf`, `jspdf-autotable`
- `date-fns`
- `lucide-react`
- Tailwind CSS (Klassen wie `bg-primary`, `text-primary`, etc.)

Falls das CRM andere UI-Bibliotheken nutzt: Tailwind-Klassen ggf. anpassen. `primary` ist als CSS-Variable definiert (z.B. in `index.css`).

### Schritt 3: Routes einbinden

```tsx
import { InvoiceList, NewInvoice } from './modules/invoice';

// In den Routes:
<Route path="rechnungen" element={<InvoiceList />} />
<Route path="rechnungen/neu" element={<NewInvoice />} />
<Route path="rechnungen/:id" element={<NewInvoice />} />
```

Die Pfade (`/rechnungen`, `/rechnungen/neu`, `/rechnungen/:id`) können an die CRM-Navigation angepasst werden.

### Schritt 4: Navigation (Sidebar/Menü)

Ein Nav-Item hinzufügen:

```tsx
<NavLink to="/rechnungen">
  <FileText className="w-5 h-5" />
  Rechnungen
</NavLink>
```

### Schritt 5: Firmenkonfiguration anpassen

Datei `src/modules/invoice/config.ts` mit den echten Firmendaten des CRM-Betreibers füllen:

- `name`, `address`, `postalCode`, `city`, `country`
- `logoUrl` oder `logoLocalPath`
- `primaryColor`, `primaryColorRgb`
- `phone`, `email`
- `bank`: `iban`, `bic`, `taxId`, `vatId`

---

## 3. Optionale Anpassungen

### Store durch API ersetzen

Aktuell speichert `invoiceStore` Daten in `localStorage`. Für CRM-Integration:

1. `invoiceStore.ts` so anpassen, dass statt `set()` API-Calls ausgeführt werden.
2. Oder: Neuen Store schreiben, der die gleiche Schnittstelle (`getFilteredInvoices`, `getPartner`, `addInvoice`, etc.) bereitstellt, aber mit Backend-API arbeitet.

### Partner & Kunden aus CRM laden

Die Listen `partners` und `customers` kommen derzeit aus dem lokalen Store. Im CRM:

- Partner und Kunden aus der CRM-Datenbank laden
- `useInvoiceStore` erweitern oder ersetzen, sodass diese Daten aus dem CRM kommen

### Layout anpassen

Die Seiten `InvoiceList` und `NewInvoice` rendern nur den Inhalt. Sie erwarten ein übergeordnetes Layout mit `<Outlet />`. Das CRM-Layout kann unverändert genutzt werden.

---

## 4. Öffentliche API (index.ts)

```ts
// Seiten
export { InvoiceList, NewInvoice } from './modules/invoice';

// Store
export { useInvoiceStore } from './modules/invoice';

// PDF
export { generateInvoicePDF, previewInvoicePDF } from './modules/invoice';

// Typen
export type { Invoice, Partner, Customer, InvoiceStatus, InvoiceFilter } from './modules/invoice';

// Konfiguration
export { COMPANY } from './modules/invoice';
```

---

## 5. CSS-Variablen (Tailwind)

Das Modul nutzt `primary` als Hauptfarbe. In `index.css` oder der Tailwind-Config:

```css
:root {
  --color-primary: 245 128 96;  /* RGB für HelpCare-Orange */
  --color-primary-hover: 230 110 80;
}
```

```js
// tailwind.config.js
theme: {
  extend: {
    colors: {
      primary: 'rgb(var(--color-primary) / <alpha-value>)',
      'primary-hover': 'rgb(var(--color-primary-hover) / <alpha-value>)',
      'primary-light': 'rgb(245 128 96 / 0.1)',
      'primary-border': 'rgb(245 128 96 / 0.3)',
    },
  },
},
```

---

## 6. Kurz-Checkliste für die Cursor KI

- [ ] Ordner `src/modules/invoice/` ins CRM-Projekt kopiert
- [ ] `package.json`: Abhängigkeiten (`jspdf`, `jspdf-autotable`, `zustand`, `date-fns`, `lucide-react`) vorhanden
- [ ] Routes für `/rechnungen`, `/rechnungen/neu`, `/rechnungen/:id` eingetragen
- [ ] Nav-Item „Rechnungen“ in Sidebar/Menü ergänzt
- [ ] `config.ts` mit Firmendaten angepasst
- [ ] Tailwind `primary`-Farben konfiguriert
- [ ] (Optional) Store auf CRM-API umgestellt
