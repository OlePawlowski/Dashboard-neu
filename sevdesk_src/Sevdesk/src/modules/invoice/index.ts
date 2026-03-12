/**
 * Rechnungsmodul für 24-Stunden-Pflege – öffentliche API
 *
 * Integration ins CRM: Importiere diese Exports und füge Routes + Nav-Item hinzu.
 * Siehe INTEGRATION.md für die vollständige Anleitung.
 */

// Seiten (für Routes)
export { InvoiceList } from './pages/InvoiceList';
export { NewInvoice } from './pages/NewInvoice';

// Store
export { useInvoiceStore } from './store/invoiceStore';

// PDF-Export
export { generateInvoicePDF, previewInvoicePDF } from './utils/pdfExport';

// Typen
export type {
  Invoice,
  Partner,
  Customer,
  InvoiceStatus,
  InvoiceFilter,
  InvoicePosition,
} from './types';

// Konfiguration (im CRM anpassen)
export { COMPANY } from './config';
