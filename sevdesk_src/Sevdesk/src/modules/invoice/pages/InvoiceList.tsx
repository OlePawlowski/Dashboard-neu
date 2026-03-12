import { Link } from 'react-router-dom';
import { format, parseISO, isToday, isPast, differenceInDays } from 'date-fns';
import { de } from 'date-fns/locale';
import { useState, useRef, useEffect } from 'react';
import { createPortal } from 'react-dom';
import {
  Download,
  Lock,
  MoreVertical,
  Plus,
  Trash2,
} from 'lucide-react';
import { useInvoiceStore } from '../store/invoiceStore';
import { generateInvoicePDF } from '../utils/pdfExport';
import { formatCurrency } from '../utils/invoiceCalculations';
import type { InvoiceFilter, InvoiceStatus } from '../types';

const filterTabs: { key: InvoiceFilter; label: string }[] = [
  { key: 'alle', label: 'Alle' },
  { key: 'entwurf', label: 'Entwurf' },
  { key: 'offen', label: 'Offen' },
  { key: 'faellig', label: 'Fällig' },
  { key: 'festgeschrieben', label: 'Festgeschrieben' },
];

function formatDueDate(dueDate: string): string {
  if (!dueDate) return '-';
  try {
    const date = parseISO(dueDate);
    if (isToday(date)) return 'Heute';
    if (isPast(date)) return format(date, 'dd.MM.yyyy', { locale: de });
    const days = differenceInDays(date, new Date());
    if (days === 1) return 'Morgen';
    return `In ${days} Tagen`;
  } catch {
    return '-';
  }
}

export function InvoiceList() {
  const {
    filter,
    setFilter,
    getFilteredInvoices,
    getPartner,
    getCustomer,
    getInvoice,
    updateInvoice,
    deleteInvoice,
    loadFromCRM,
    loadInvoices,
  } = useInvoiceStore();

  const [openMenuId, setOpenMenuId] = useState<string | null>(null);
  const [menuPosition, setMenuPosition] = useState({ top: 0, left: 0 });
  const buttonRefs = useRef<Record<string, HTMLButtonElement | null>>({});

  // Beim ersten Render Partner & Kunden sowie Rechnungen aus dem Dashboard laden
  useEffect(() => {
    void loadFromCRM();
    void loadInvoices();
  }, [loadFromCRM, loadInvoices]);

  const invoices = getFilteredInvoices();

  useEffect(() => {
    if (openMenuId && buttonRefs.current[openMenuId]) {
      const rect = buttonRefs.current[openMenuId]!.getBoundingClientRect();
      setMenuPosition({
        top: rect.bottom + 4,
        left: rect.right - 176,
      });
    }
  }, [openMenuId]);

  const handleDelete = (invoice: { id: string; invoiceNumber: string }) => {
    if (window.confirm(`Rechnung ${invoice.invoiceNumber} wirklich löschen?`)) {
      void deleteInvoice(invoice.id);
      setOpenMenuId(null);
    }
  };

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Rechnungen</h1>
        <Link
          to="/rechnungen/neu"
          className="inline-flex items-center gap-2 px-4 py-2 bg-primary text-white rounded-lg font-medium hover:bg-primary-hover transition-colors"
        >
          <Plus className="w-4 h-4" />
          Neue Rechnung
        </Link>
      </div>

      <div className="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
          <div className="flex gap-1">
            {filterTabs.map(({ key, label }) => (
              <button
                key={key}
                onClick={() => setFilter(key)}
                className={`px-4 py-2 text-sm font-medium rounded-lg transition-colors ${
                  filter === key
                    ? 'text-primary border-b-2 border-primary'
                    : 'text-gray-600 hover:text-gray-900'
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="bg-gray-50/80">
                <th className="text-left py-3 px-6 text-xs font-semibold text-gray-500 uppercase tracking-wider">
                  Status
                </th>
                <th className="text-left py-3 px-6 text-xs font-semibold text-gray-500 uppercase tracking-wider">
                  Fälligkeit
                </th>
                <th className="text-left py-3 px-6 text-xs font-semibold text-gray-500 uppercase tracking-wider">
                  Rechnungsnr.
                </th>
                <th className="text-left py-3 px-6 text-xs font-semibold text-gray-500 uppercase tracking-wider">
                  Kooperationspartner
                </th>
                <th className="text-left py-3 px-6 text-xs font-semibold text-gray-500 uppercase tracking-wider">
                  Kunde
                </th>
                <th className="text-left py-3 px-6 text-xs font-semibold text-gray-500 uppercase tracking-wider">
                  Datum
                </th>
                <th className="text-right py-3 px-6 text-xs font-semibold text-gray-500 uppercase tracking-wider">
                  Provision (brutto)
                </th>
                <th className="text-right py-3 px-6 text-xs font-semibold text-gray-500 uppercase tracking-wider">
                  Offen (brutto)
                </th>
                <th className="w-24 py-3 px-6"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {invoices.map((invoice) => {
                const partner = getPartner(invoice.partnerId);
                const customer = getCustomer(invoice.customerId);
                const totalGross = invoice.commissionAmount;
                const openAmount =
                  invoice.status === 'bezahlt'
                    ? 0
                    : totalGross - (invoice.paidAmount || 0);

                return (
                  <tr
                    key={invoice.id}
                    className="hover:bg-gray-50/50 transition-colors"
                  >
                    <td className="py-4 px-6">
                      <select
                        value={invoice.status}
                        onChange={(e) =>
                          updateInvoice(invoice.id, {
                            status: e.target.value as InvoiceStatus,
                            isLocked: e.target.value !== 'entwurf',
                          })
                        }
                        className="text-sm font-medium rounded-lg px-2.5 py-1 border-0 cursor-pointer focus:ring-2 focus:ring-primary/30"
                        style={{
                          backgroundColor:
                            invoice.status === 'entwurf' ? 'rgb(237 233 254)' :
                            invoice.status === 'offen' ? 'rgb(254 243 199)' :
                            invoice.status === 'faellig' ? 'rgb(254 226 226)' :
                            invoice.status === 'bezahlt' ? 'rgb(209 250 229)' :
                            'rgb(241 245 249)',
                          color:
                            invoice.status === 'entwurf' ? 'rgb(126 34 206)' :
                            invoice.status === 'offen' ? 'rgb(180 83 9)' :
                            invoice.status === 'faellig' ? 'rgb(185 28 28)' :
                            invoice.status === 'bezahlt' ? 'rgb(4 120 87)' :
                            'rgb(51 65 85)',
                        }}
                      >
                        <option value="entwurf">Entwurf</option>
                        <option value="offen">Offen</option>
                        <option value="faellig">Fällig</option>
                        <option value="bezahlt">Bezahlt</option>
                        <option value="festgeschrieben">Festgeschrieben</option>
                      </select>
                    </td>
                    <td className="py-4 px-6 text-sm text-gray-600">
                      {formatDueDate(invoice.dueDate)}
                    </td>
                    <td className="py-4 px-6">
                      <div className="flex items-center gap-2">
                        {invoice.isLocked && (
                          <Lock className="w-4 h-4 text-gray-400 shrink-0" />
                        )}
                        <span className="text-sm font-medium text-gray-900">
                          {invoice.status === 'entwurf' ? '-' : invoice.invoiceNumber}
                        </span>
                      </div>
                    </td>
                    <td className="py-4 px-6">
                      <div>
                        <p className="text-sm font-medium text-gray-900">
                          {partner?.name || '-'}
                        </p>
                        <p className="text-xs text-gray-500">
                          Rechnung Nr. {invoice.invoiceNumber}
                        </p>
                      </div>
                    </td>
                    <td className="py-4 px-6">
                      <p className="text-sm text-gray-900">
                        {customer?.name || '-'}
                      </p>
                    </td>
                    <td className="py-4 px-6 text-sm text-gray-600">
                      {invoice.invoiceDate
                        ? format(parseISO(invoice.invoiceDate), 'dd.MM.yy', {
                            locale: de,
                          })
                        : '-'}
                    </td>
                    <td className="py-4 px-6 text-sm text-right text-gray-900">
                      {formatCurrency(totalGross)}
                    </td>
                    <td className="py-4 px-6 text-sm text-right text-gray-900">
                      {formatCurrency(openAmount)}
                    </td>
                    <td className="py-4 px-6">
                      <div className="flex items-center gap-1">
                        <button
                          onClick={async () => {
                            const inv = getInvoice(invoice.id);
                            if (inv) {
                              await generateInvoicePDF(
                                inv,
                                getPartner(invoice.partnerId),
                                getCustomer(invoice.customerId)
                              );
                            }
                          }}
                          className="p-2 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg"
                          title="Herunterladen"
                        >
                          <Download className="w-4 h-4" />
                        </button>
                        <button
                          ref={(el) => { buttonRefs.current[invoice.id] = el; }}
                          onClick={() =>
                            setOpenMenuId(openMenuId === invoice.id ? null : invoice.id)
                          }
                          className="p-2 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg"
                          title="Weitere Optionen"
                        >
                          <MoreVertical className="w-4 h-4" />
                        </button>
                        {openMenuId === invoice.id &&
                          createPortal(
                            <>
                              <div
                                className="fixed inset-0 z-40"
                                onClick={() => setOpenMenuId(null)}
                              />
                              <div
                                className="fixed z-50 py-1 w-44 bg-white rounded-lg shadow-lg border border-gray-200"
                                style={{
                                  top: menuPosition.top,
                                  left: menuPosition.left,
                                }}
                              >
                                <button
                                  onClick={() => handleDelete(invoice)}
                                  className="w-full flex items-center gap-2 px-4 py-2 text-sm text-red-600 hover:bg-red-50 rounded-lg text-left"
                                >
                                  <Trash2 className="w-4 h-4 shrink-0" />
                                  Löschen
                                </button>
                              </div>
                            </>,
                            document.body
                          )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {invoices.length === 0 && (
          <div className="py-16 text-center text-gray-500">
            <p className="text-lg font-medium">Keine Rechnungen gefunden</p>
            <p className="text-sm mt-1">
              Erstellen Sie eine neue Rechnung oder ändern Sie den Filter.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
