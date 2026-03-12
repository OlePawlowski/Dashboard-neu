import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { Invoice, Partner, Customer, InvoiceFilter } from '../types';
import { format } from 'date-fns';

const STORAGE_KEY = 'rechnungs-24h-pflege-v2';

const generateId = () => Math.random().toString(36).slice(2, 11);

/**
 * Provision-String aus dem Dashboard (z. B. "11%", "10,5 %") in eine Zahl umwandeln.
 */
const parseProvisionToRate = (value: unknown, fallback = 11): number => {
  if (typeof value !== 'string' || !value.trim()) return fallback;
  const cleaned = value.replace('%', '').replace(',', '.').trim();
  const num = Number.parseFloat(cleaned);
  return Number.isFinite(num) ? num : fallback;
};

/**
 * Versucht aus einer freien Adresszeile eine PLZ und einen Ort zu extrahieren.
 * Beispiel: "Musterstraße 1, 12345 Musterstadt" → { postalCode: "12345", city: "Musterstadt" }.
 */
const extractPostalAndCity = (street: string | undefined | null): { postalCode: string; city: string } => {
  if (!street) return { postalCode: '', city: '' };
  const text = String(street);
  // Suche nach Muster "12345 Stadt"
  const match = text.match(/(\d{5})\s+([A-Za-zÄÖÜäöüß .-]+)/);
  if (match) {
    return {
      postalCode: match[1],
      city: match[2].trim(),
    };
  }
  return { postalCode: '', city: '' };
};

/**
 * Kooperationspartner-Objekte aus dem Dashboard auf das Rechnungsmodul abbilden.
 */
const mapPartnerFromCRM = (raw: any): Partner => {
  const street = raw.street_address || '';
  const { postalCode, city } = extractPostalAndCity(street);
  return {
    id: String(raw.id),
    // Im Rechnungsmodul soll standardmäßig der Firmenname erscheinen,
    // nicht der Name des Ansprechpartners.
    name: raw.company_name || raw.name || 'Unbekannter Partner',
    address: street,
    postalCode,
    city,
    country: '',
    email: raw.email || undefined,
    phone: raw.phone || raw.emergency_phone || undefined,
    commissionRate: parseProvisionToRate(raw.provision, 11),
  };
};

/**
 * Kunden-Objekte aus dem Dashboard auf das Rechnungsmodul abbilden.
 */
const mapCustomerFromCRM = (raw: any): Customer => {
  return {
    id: String(raw.id),
    name: raw.name || 'Unbekannter Kunde',
    address: raw.street_address || '',
    postalCode: raw.postal_code || '',
    city: raw.city || '',
    country: 'Deutschland',
    email: raw.email || undefined,
    phone: raw.mobile_phone || raw.phone || undefined,
  };
};

// Beispielrechnungen und lokale Nummernlogik werden nicht mehr benötigt,
// da alle Rechnungen zentral über das Backend synchronisiert werden.

interface InvoiceStore {
  invoices: Invoice[];
  partners: Partner[];
  customers: Customer[];
  /** Merkt, ob gerade CRM-Daten geladen werden (zur Sicherheit gegen doppelte Loads). */
  isLoadingCRM: boolean;
  filter: InvoiceFilter;
  setFilter: (filter: InvoiceFilter) => void;
  getFilteredInvoices: () => Invoice[];
  getPartner: (id: string) => Partner | undefined;
  getCustomer: (id: string) => Customer | undefined;
  addPartner: (partner: Omit<Partner, 'id'>) => Partner;
  addCustomer: (customer: Omit<Customer, 'id'>) => Customer;
  updatePartner: (id: string, partner: Partial<Partner>) => void;
  updateCustomer: (id: string, customer: Partial<Customer>) => void;
  addInvoice: (invoice: Omit<Invoice, 'id' | 'createdAt' | 'updatedAt'>) => Promise<Invoice>;
  updateInvoice: (id: string, invoice: Partial<Invoice>) => Promise<Invoice | null>;
  deleteInvoice: (id: string) => Promise<void>;
  getInvoice: (id: string) => Invoice | undefined;
  /** Lädt Partner & Kunden aus dem Dashboard (/api/kooperationspartner, /api/customers). */
  loadFromCRM: () => Promise<void>;
  loadInvoices: () => Promise<void>;
}

export const useInvoiceStore = create<InvoiceStore>()(
  persist(
    (set, get) => ({
      invoices: [],
      partners: [],
      customers: [],
      isLoadingCRM: false,
      filter: 'alle',

      setFilter: (filter) => set({ filter }),

      getFilteredInvoices: () => {
        const { invoices, filter } = get();
        if (filter === 'alle') return invoices;
        return invoices.filter((i) => i.status === filter);
      },

      getPartner: (id) => get().partners.find((p) => p.id === id),
      getCustomer: (id) => get().customers.find((c) => c.id === id),

      addPartner: (partner) => {
        const newPartner: Partner = {
          ...partner,
          id: generateId(),
        };
        set((state) => ({
          partners: [...state.partners, newPartner],
        }));
        return newPartner;
      },

      addCustomer: (customer) => {
        const newCustomer: Customer = {
          ...customer,
          id: generateId(),
        };
        set((state) => ({
          customers: [...state.customers, newCustomer],
        }));
        return newCustomer;
      },

      updatePartner: (id, partner) => {
        set((state) => ({
          partners: state.partners.map((p) =>
            p.id === id ? { ...p, ...partner } : p
          ),
        }));
      },

      updateCustomer: (id, customer) => {
        set((state) => ({
          customers: state.customers.map((c) =>
            c.id === id ? { ...c, ...customer } : c
          ),
        }));
      },

      addInvoice: async (invoice) => {
        const now = format(new Date(), 'yyyy-MM-dd');
        const payload = {
          ...invoice,
          createdAt: now,
          updatedAt: now,
        };
        const res = await fetch('/api/invoices', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        if (!res.ok) {
          const error = await res.json().catch(() => ({}));
          throw new Error((error as { error?: string }).error || 'Fehler beim Anlegen der Rechnung');
        }
        const created = (await res.json()) as Invoice;
        set((state) => ({
          invoices: [...state.invoices, created],
        }));
        return created;
      },

      updateInvoice: async (id, invoice) => {
        const res = await fetch(`/api/invoices/${id}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(invoice),
        });
        if (!res.ok) {
          console.error('Fehler beim Aktualisieren der Rechnung', await res.text());
          return null;
        }
        const updated = (await res.json()) as Invoice;
        set((state) => ({
          invoices: state.invoices.map((i) => (i.id === id ? updated : i)),
        }));
        return updated;
      },

      deleteInvoice: async (id) => {
        const res = await fetch(`/api/invoices/${id}`, { method: 'DELETE' });
        if (!res.ok) {
          console.error('Fehler beim Löschen der Rechnung', await res.text());
          return;
        }
        set((state) => ({
          invoices: state.invoices.filter((i) => i.id !== id),
        }));
      },

      getInvoice: (id) => get().invoices.find((i) => i.id === id),
      loadFromCRM: async () => {
        const { isLoadingCRM, partners, customers } = get();
        // Mehrfachaufrufe vermeiden und vorhandene Daten respektieren
        if (isLoadingCRM) return;
        set({ isLoadingCRM: true });

        try {
          // Kooperationspartner laden
          const partnersRes = await fetch('/api/kooperationspartner', {
            headers: { Accept: 'application/json' },
          });
          if (partnersRes.ok) {
            const raw = await partnersRes.json();
            const list = Array.isArray(raw) ? raw : raw.items || [];
            const mapped = (list as any[]).map(mapPartnerFromCRM);
            // Existierende Partner (z. B. lokal angelegte) beibehalten
            set({
              partners: partners.length ? partners : mapped,
            });
          }

          // Kunden laden
          const customersRes = await fetch('/api/customers', {
            headers: { Accept: 'application/json' },
          });
          if (customersRes.ok) {
            const rawC = await customersRes.json();
            const listC = Array.isArray(rawC) ? rawC : rawC.items || [];
            const mappedC = (listC as any[]).map(mapCustomerFromCRM);
            set({
              customers: customers.length ? customers : mappedC,
            });
          }
        } catch {
          // Still und leise fallenlassen – das Rechnungsmodul bleibt funktionsfähig
          // und nutzt ggf. lokal angelegte Partner/Kunden.
        } finally {
          set({ isLoadingCRM: false });
        }
      },

      loadInvoices: async () => {
        try {
          const res = await fetch('/api/invoices', { headers: { Accept: 'application/json' } });
          if (!res.ok) return;
          const data = (await res.json()) as Invoice[];
          set({ invoices: data });
        } catch {
          // Bei Fehlern keine Ausnahme werfen – Modul bleibt nutzbar (lokal)
        }
      },
    }),
    {
      name: STORAGE_KEY,
      version: 3,
      migrate: (persistedState: unknown, version: number) => {
        const state = persistedState as { invoices?: Array<Record<string, unknown>> };
        if (!state?.invoices) return persistedState as typeof persistedState;

        if (version < 2) {
          state.invoices = state.invoices.map((inv) => {
            const deliveryDate = inv.deliveryDate as string | undefined;
            if (deliveryDate && !inv.performancePeriodFrom) {
              const { deliveryDate: _, ...rest } = inv;
              return { ...rest, performancePeriodFrom: deliveryDate, performancePeriodTo: deliveryDate };
            }
            return inv;
          });
        }

        const newHeaderDefault = `Sehr geehrte Damen und Herren,

hiermit stellen wir Ihnen folgende Leistungen in Rechnung.`;

        if (version < 3) {
          state.invoices = state.invoices.map((inv) => {
            const header = inv.headerText as string | undefined;
            if (header && header.includes('Details siehe Aufstellung')) {
              return { ...inv, headerText: newHeaderDefault };
            }
            return inv;
          });
        }

        return persistedState as typeof persistedState;
      },
    }
  )
);
