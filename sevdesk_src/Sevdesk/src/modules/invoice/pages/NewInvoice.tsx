import { useState, useEffect, useRef } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { format, addDays } from 'date-fns';
import { createPortal } from 'react-dom';
import { Save, Send, Download, ChevronDown, Plus, Settings } from 'lucide-react';
import { useInvoiceStore } from '../store/invoiceStore';
import { formatCurrency } from '../utils/invoiceCalculations';
import { generateInvoicePDF, generateInvoicePDFDataUrl } from '../utils/pdfExport';

const defaultHeaderText = `Sehr geehrte Damen und Herren,

hiermit stellen wir Ihnen folgende Leistungen in Rechnung.`;

export function NewInvoice() {
  const navigate = useNavigate();
  const { id } = useParams();
  const isEdit = Boolean(id);

  const {
    partners,
    customers,
    getInvoice,
    getPartner,
    getCustomer,
    getFilteredInvoices,
    addInvoice,
    updateInvoice,
    updatePartner,
    loadFromCRM,
    loadInvoices,
  } = useInvoiceStore();

  // Beim ersten Render CRM-Daten (Partner & Kunden) aus dem Dashboard laden
  useEffect(() => {
    void loadFromCRM();
    void loadInvoices();
  }, [loadFromCRM, loadInvoices]);

  const existingInvoice = id ? getInvoice(id) : null;

  const [partnerId, setPartnerId] = useState(existingInvoice?.partnerId || '');
  const [customerId, setCustomerId] = useState(existingInvoice?.customerId || '');
  const [agreedTotalAmount, setAgreedTotalAmount] = useState(
    existingInvoice?.agreedTotalAmount ?? 0
  );
  const [commissionRate, setCommissionRate] = useState(
    existingInvoice?.commissionRate ?? 11
  );
  const [commissionMode, setCommissionMode] = useState<'percent' | 'fixed'>(
    existingInvoice?.commissionMode ?? 'percent'
  );
  const [commissionFixedAmount, setCommissionFixedAmount] = useState(
    existingInvoice?.commissionFixedAmount ?? existingInvoice?.commissionAmount ?? 0
  );
  const [invoiceDate, setInvoiceDate] = useState(
    existingInvoice?.invoiceDate || format(new Date(), 'yyyy-MM-dd')
  );
  const [performancePeriodFrom, setPerformancePeriodFrom] = useState(
    (existingInvoice as { performancePeriodFrom?: string; deliveryDate?: string })?.performancePeriodFrom ||
    (existingInvoice as { deliveryDate?: string })?.deliveryDate ||
    format(new Date(), 'yyyy-MM-dd')
  );
  const [performancePeriodTo, setPerformancePeriodTo] = useState(
    (existingInvoice as { performancePeriodTo?: string; deliveryDate?: string })?.performancePeriodTo ||
    (existingInvoice as { deliveryDate?: string })?.deliveryDate ||
    format(new Date(), 'yyyy-MM-dd')
  );
  const [invoiceNumber, setInvoiceNumber] = useState(
    existingInvoice?.invoiceNumber || ''
  );
  const [referenceNumber, setReferenceNumber] = useState(
    existingInvoice?.referenceNumber || ''
  );
  const [paymentTermsDays, setPaymentTermsDays] = useState(
    existingInvoice?.paymentTermsDays ?? 14
  );
  const [reverseCharge, setReverseCharge] = useState(
    existingInvoice?.reverseCharge ?? false
  );
  const [subject, setSubject] = useState(existingInvoice?.subject || '');
  const [headerText, setHeaderText] = useState(
    existingInvoice?.headerText || defaultHeaderText
  );
  const partner = partnerId ? getPartner(partnerId) : null;
  const customer = customerId ? getCustomer(customerId) : null;
  const invoices = getFilteredInvoices();
  const [eligibleCustomerIds, setEligibleCustomerIds] = useState<string[] | null>(null);
  const [actionsMenuOpen, setActionsMenuOpen] = useState(false);
  const actionsButtonRef = useRef<HTMLDivElement>(null);
  const [actionsMenuPosition, setActionsMenuPosition] = useState({ top: 0, left: 0 });
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [pendingInvoiceId, setPendingInvoiceId] = useState<string | null>(null);
  const [isSending, setIsSending] = useState(false);

  useEffect(() => {
    if (actionsMenuOpen && actionsButtonRef.current) {
      const rect = actionsButtonRef.current.getBoundingClientRect();
      setActionsMenuPosition({ top: rect.bottom + 4, left: rect.right - 192 });
    }
  }, [actionsMenuOpen]);

  // Kundenliste auf diejenigen einschränken, die einen Dienstleistungsvertrag
  // mit dem ausgewählten Kooperationspartner haben.
  useEffect(() => {
    if (!partnerId) {
      setEligibleCustomerIds(null);
      return;
    }

    const controller = new AbortController();

    (async () => {
      try {
        const res = await fetch('/api/dienstleistungsvertraege?per_page=2000', {
          headers: { Accept: 'application/json' },
          signal: controller.signal,
        });
        if (!res.ok) return;
        const data = await res.json();
        const items = Array.isArray(data) ? data : data.items || [];

        const ids = new Set<string>();
        (items as any[]).forEach((contract) => {
          if (
            contract &&
            contract.kooperationspartner_id != null &&
            String(contract.kooperationspartner_id) === String(partnerId) &&
            contract.customer_id != null
          ) {
            ids.add(String(contract.customer_id));
          }
        });

        const list = Array.from(ids);
        setEligibleCustomerIds(list.length ? list : []);

        // Falls aktuell gewählter Kunde nicht (mehr) passt, Auswahl leeren
        if (customerId && !list.includes(String(customerId))) {
          setCustomerId('');
        }
      } catch {
        // still und leise scheitern – das Formular bleibt nutzbar
      }
    })();

    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [partnerId]);

  const filteredCustomers =
    eligibleCustomerIds && eligibleCustomerIds.length
      ? customers.filter((c) => eligibleCustomerIds.includes(c.id))
      : customers;

  const commissionAmount =
    commissionMode === 'percent'
      ? Math.round(agreedTotalAmount * (commissionRate / 100) * 100) / 100
      : commissionFixedAmount || 0;

  useEffect(() => {
    if (!isEdit && !invoiceNumber) {
      const numbers = invoices
        .filter((i) => i.invoiceNumber.startsWith('RE-'))
        .map((i) => parseInt(i.invoiceNumber.replace('RE-', ''), 10))
        .filter((n) => !isNaN(n));
      const max = numbers.length ? Math.max(...numbers) : 1335;
      setInvoiceNumber(`RE-${max + 1}`);
    }
  }, [isEdit, invoiceNumber, invoices]);

  useEffect(() => {
    if (invoiceNumber && !subject) {
      setSubject(`Rechnung Nr. ${invoiceNumber} – Vermittlungsprovision`);
    }
  }, [invoiceNumber, subject]);

  useEffect(() => {
    const p = partnerId ? getPartner(partnerId) : null;
    if (p) {
      setCommissionRate(p.commissionRate);
      if (!isEdit) {
        // Standardmäßig Prozentmodus, wenn ein Partner gewählt wird
        setCommissionMode('percent');
      }
    }
  }, [partnerId]);

  const dueDate = addDays(new Date(invoiceDate), paymentTermsDays);

  const handleSave = async (status: 'entwurf' | 'offen' = 'entwurf', redirect = true): Promise<string> => {
    const invoiceData = {
      invoiceNumber,
      status,
      partnerId,
      customerId,
      agreedTotalAmount,
      commissionRate,
      commissionMode,
      commissionFixedAmount: commissionMode === 'fixed' ? commissionAmount : undefined,
      commissionAmount,
      invoiceDate,
      performancePeriodFrom,
      performancePeriodTo,
      dueDate: format(dueDate, 'yyyy-MM-dd'),
      referenceNumber: referenceNumber || undefined,
      subject: subject || `Rechnung Nr. ${invoiceNumber} – Vermittlungsprovision`,
      headerText,
      positions: [],
      paymentTermsDays,
      reverseCharge,
      isLocked: status !== 'entwurf',
      paidAmount: 0,
    };

    if (isEdit && id) {
      await updateInvoice(id, invoiceData);
      if (redirect) navigate('/rechnungen');
      return id;
    }
    const newInv = await addInvoice(invoiceData);
    if (redirect) navigate('/rechnungen');
    return newInv.id;
  };

  const handleDownload = async () => {
    const savedId = await handleSave('offen', false);
    const inv = getInvoice(savedId);
    if (inv) {
      await generateInvoicePDF(
        inv,
        getPartner(inv.partnerId),
        getCustomer(inv.customerId)
      );
    }
  };

  const handleSend = async () => {
    const savedId = await handleSave('offen', false);
    const inv = getInvoice(savedId);
    if (!inv) return;

    const partner = getPartner(inv.partnerId);
    const customer = getCustomer(inv.customerId);

    const to = (partner?.email || '').trim();
    if (!to) {
      window.alert('Bitte hinterlegen Sie eine E-Mail-Adresse beim Kooperationspartner (Rechnungsempfänger).');
      return;
    }

    try {
      const pdfDataUrl = await generateInvoicePDFDataUrl(inv, partner, customer);
      setPreviewUrl(pdfDataUrl);
      setPendingInvoiceId(savedId);
      setActionsMenuOpen(false);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      window.alert('❌ Vorschau der Rechnung fehlgeschlagen: ' + msg);
    }
  };

  const handleConfirmSend = async () => {
    if (!pendingInvoiceId) return;
    const inv = getInvoice(pendingInvoiceId);
    if (!inv) return;

    const partner = getPartner(inv.partnerId);
    const customer = getCustomer(inv.customerId);

    const to = (partner?.email || '').trim();
    if (!to) {
      window.alert('Bitte hinterlegen Sie eine E-Mail-Adresse beim Kooperationspartner (Rechnungsempfänger).');
      return;
    }

    try {
      setIsSending(true);
      const pdfDataUrl =
        previewUrl && previewUrl.startsWith('data:') ?
          previewUrl :
          await generateInvoicePDFDataUrl(inv, partner, customer);

      const payload = {
        to,
        invoiceNumber: inv.invoiceNumber,
        pdf_base64: pdfDataUrl,
        partnerName: partner?.name ?? '',
        customerName: customer?.name ?? '',
      };

      const res = await fetch('/api/invoices/send-email', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error((data as { error?: string }).error || 'Unbekannter Fehler beim Versand der Rechnung.');
      }

      window.alert('✔️ Die Rechnung wurde per E-Mail versendet.');
      setPreviewUrl(null);
      setPendingInvoiceId(null);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      window.alert('❌ Versand der Rechnung fehlgeschlagen: ' + msg);
    } finally {
      setIsSending(false);
    }
  };

  const updateHeaderFromSelection = () => {
    if (customer && agreedTotalAmount > 0) {
      const detailsText =
        commissionMode === 'percent'
          ? `${formatCurrency(agreedTotalAmount)} × ${commissionRate} % = ${formatCurrency(
              commissionAmount
            )}.`
          : `Pauschale Vermittlungsprovision: ${formatCurrency(commissionAmount)}.`;

      setHeaderText(`Sehr geehrte Damen und Herren,

hiermit stellen wir Ihnen folgende Leistungen in Rechnung.

Vermittlungsprovision für 24-Stunden-Pflege von ${customer.name}: ${detailsText}`);
    }
  };

  return (
    <div className="p-6 max-w-4xl mx-auto">
      {previewUrl && (
        <div className="mb-6 border border-gray-200 rounded-xl overflow-hidden bg-white shadow-sm">
          <div className="flex items-center justify-between px-4 py-2 border-b border-gray-200 bg-gray-50">
            <span className="text-sm font-medium text-gray-700">
              Rechnungsvorschau
            </span>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => {
                  setPreviewUrl(null);
                  setPendingInvoiceId(null);
                }}
                className="px-3 py-1.5 text-sm text-gray-600 hover:text-gray-900 hover:bg-gray-100 rounded-lg transition-colors"
              >
                Abbrechen
              </button>
              <button
                type="button"
                onClick={handleConfirmSend}
                disabled={isSending}
                className="px-4 py-1.5 text-sm font-medium rounded-lg text-white bg-primary hover:bg-primary-hover disabled:opacity-60 disabled:cursor-not-allowed transition-colors"
              >
                {isSending ? 'Senden…' : 'Endgültig versenden'}
              </button>
            </div>
          </div>
          <iframe
            src={previewUrl}
            title="Rechnungsvorschau"
            className="w-full h-[600px] border-0 bg-white"
          />
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-4 mb-6 pb-6 border-b border-gray-200">
        <h1 className="text-2xl font-bold text-gray-900">
          {isEdit ? 'Rechnung bearbeiten' : 'Neue Rechnung'}
        </h1>
        <div className="flex items-center gap-2 flex-wrap">
          <button
            onClick={handleDownload}
            className="flex items-center gap-2 px-3 py-2.5 text-gray-600 hover:text-gray-900 hover:bg-gray-100 rounded-lg transition-colors text-sm font-medium"
          >
            <Download className="w-4 h-4 shrink-0" />
            Herunterladen
          </button>
          <button
            onClick={() => handleSave('entwurf', true)}
            className="flex items-center gap-2 px-4 py-2.5 text-gray-700 bg-gray-100 hover:bg-gray-200 rounded-lg font-medium text-sm transition-colors"
          >
            <Save className="w-4 h-4 shrink-0" />
            Speichern
          </button>
          <div ref={actionsButtonRef} className="relative flex rounded-lg overflow-hidden shadow-sm">
            <button
              onClick={handleSend}
              className="flex items-center gap-2 px-5 py-2.5 bg-primary text-white font-medium text-sm hover:bg-primary-hover transition-colors whitespace-nowrap"
            >
              <Send className="w-4 h-4 shrink-0" />
              Versenden
            </button>
            <button
              onClick={() => setActionsMenuOpen((o) => !o)}
              className="px-2.5 py-2.5 bg-primary hover:bg-primary-hover text-white border-l border-white/20 transition-colors"
              aria-label="Weitere Optionen"
            >
              <ChevronDown className="w-4 h-4" />
            </button>
            {actionsMenuOpen &&
              createPortal(
                <>
                  <div
                    className="fixed inset-0 z-40"
                    onClick={() => setActionsMenuOpen(false)}
                  />
                  <div
                    className="fixed z-50 py-1 w-48 bg-white rounded-lg shadow-lg border border-gray-200"
                    style={{ top: actionsMenuPosition.top, left: actionsMenuPosition.left }}
                  >
                    <button
                      onClick={() => {
                        setActionsMenuOpen(false);
                        handleSend();
                      }}
                      className="w-full flex items-center gap-2 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 rounded-lg text-left"
                    >
                      <Send className="w-4 h-4 shrink-0" />
                      Versenden
                    </button>
                    <button
                      onClick={() => {
                        setActionsMenuOpen(false);
                        handleDownload();
                      }}
                      className="w-full flex items-center gap-2 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 rounded-lg text-left"
                    >
                      <Download className="w-4 h-4 shrink-0" />
                      Herunterladen
                    </button>
                  </div>
                </>,
                document.body
              )}
          </div>
          <button className="p-2.5 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded-lg transition-colors">
            <span className="sr-only">Mehr Optionen</span>
            <span className="text-lg font-medium leading-none">⋯</span>
          </button>
        </div>
      </div>

      <div className="space-y-6">
        {/* Kooperationspartner & Kunde */}
        <section className="bg-white rounded-xl border border-gray-200 p-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-4">
            Vermittlung 24-Stunden-Pflege
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Kooperationspartner (Rechnungsempfänger) *
              </label>
              <div className="flex gap-2 items-center">
                <div className="relative flex-1 min-w-0">
                  <select
                    value={partnerId}
                    onChange={(e) => setPartnerId(e.target.value)}
                    className="w-full px-3 py-2.5 pr-10 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary bg-white"
                  >
                    <option value="">Partner auswählen</option>
                    {partners.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name} ({p.commissionRate}%)
                      </option>
                    ))}
                  </select>
                </div>
                <button type="button" className="shrink-0 p-2.5 border border-gray-300 rounded-lg hover:bg-gray-50">
                  <Plus className="w-4 h-4" />
                </button>
                <button type="button" className="shrink-0 p-2.5 border border-gray-300 rounded-lg hover:bg-gray-50">
                  <Settings className="w-4 h-4" />
                </button>
              </div>
              {partner && (
                <p className="mt-2 text-xs text-gray-500">
                  Standard-Provisionssatz: {partner.commissionRate} %
                </p>
              )}
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Kunde *
              </label>
              <div className="flex gap-2 items-center">
                <div className="relative flex-1 min-w-0">
                  <select
                    value={customerId}
                    onChange={(e) => setCustomerId(e.target.value)}
                    className="w-full px-3 py-2.5 pr-10 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary bg-white"
                  >
                    <option value="">Kunde auswählen</option>
                  {filteredCustomers.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                  </select>
                </div>
                <button type="button" className="shrink-0 p-2.5 border border-gray-300 rounded-lg hover:bg-gray-50">
                  <Plus className="w-4 h-4" />
                </button>
              </div>
            </div>
          </div>

          {partner && (
            <div className="mt-4 space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Anschrift *
                </label>
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={partner.address}
                    onChange={(e) =>
                      updatePartner(partnerId, { address: e.target.value })
                    }
                    className="flex-1 px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary"
                    placeholder="Straße, Hausnummer"
                  />
                  <button className="text-sm text-primary hover:underline self-center shrink-0">
                    Adresszusatz +
                  </button>
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  E-Mail
                </label>
                <input
                  type="email"
                  value={partner.email || ''}
                  onChange={(e) =>
                    updatePartner(partnerId, { email: e.target.value })
                  }
                  className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-primary"
                  placeholder="info@beispiel.de"
                />
              </div>
              <button className="text-sm text-primary hover:underline flex items-center gap-1">
                Kontaktdetails anzeigen
                <ChevronDown className="w-4 h-4" />
              </button>
            </div>
          )}
        </section>

        {/* Provisionsberechnung */}
        <section className="bg-white rounded-xl border border-gray-200 p-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-4">
            Provisionsberechnung
          </h2>
          <div className="flex flex-wrap gap-4 mb-4 text-sm">
            <label className="inline-flex items-center gap-2">
              <input
                type="radio"
                className="text-primary focus:ring-primary"
                checked={commissionMode === 'percent'}
                onChange={() => setCommissionMode('percent')}
              />
              <span>Prozentuale Provision</span>
            </label>
            <label className="inline-flex items-center gap-2">
              <input
                type="radio"
                className="text-primary focus:ring-primary"
                checked={commissionMode === 'fixed'}
                onChange={() => setCommissionMode('fixed')}
              />
              <span>Pauschalbetrag</span>
            </label>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {commissionMode === 'percent' && (
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Rechnungsbetrag *
                </label>
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  value={agreedTotalAmount || ''}
                  onChange={(e) =>
                    setAgreedTotalAmount(parseFloat(e.target.value) || 0)
                  }
                  placeholder="z.B. 3890"
                  className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary"
                />
                <p className="mt-1 text-xs text-gray-500">
                  Der Betrag, der zwischen Kooperationspartner und Kunde vereinbart wurde
                </p>
              </div>
            )}
            {commissionMode === 'percent' ? (
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Provisionssatz (%)
                </label>
                <input
                  type="number"
                  min="0"
                  max="100"
                  step="0.5"
                  value={commissionRate || ''}
                  onChange={(e) =>
                    setCommissionRate(parseFloat(e.target.value) || 0)
                  }
                  className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary"
                />
                <p className="mt-1 text-xs text-gray-500">
                  Ca. 11 % je nach Kooperationspartner
                </p>
              </div>
            ) : (
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Pauschale Vermittlungsprovision (€)
                </label>
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  value={commissionFixedAmount || ''}
                  onChange={(e) =>
                    setCommissionFixedAmount(parseFloat(e.target.value) || 0)
                  }
                  className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary"
                />
                <p className="mt-1 text-xs text-gray-500">
                  Z.&nbsp;B. 300&nbsp;€ als fester Betrag, unabhängig vom Gesamtbetrag
                </p>
              </div>
            )}
          </div>
            <div className="mt-6 p-5 rounded-xl bg-primary-light border border-primary-border shadow-sm">
            <div className="flex justify-between items-baseline gap-4">
              <span className="font-semibold text-gray-800">
                {commissionMode === 'fixed'
                  ? 'Vermittlungsprovision (Pauschale)'
                  : 'Vermittlungsprovision (Rechnungsbetrag)'}
              </span>
              <span className="text-2xl font-bold text-primary tabular-nums">
                {formatCurrency(commissionAmount)}
              </span>
            </div>
            {agreedTotalAmount > 0 && commissionMode === 'percent' && (
              <p className="mt-2 text-sm text-gray-600">
                {formatCurrency(agreedTotalAmount)} × {commissionRate} % ={' '}
                {formatCurrency(commissionAmount)}
              </p>
            )}
            {commissionMode === 'fixed' && commissionAmount > 0 && (
              <p className="mt-2 text-sm text-gray-600">
                Pauschale Vermittlungsprovision: {formatCurrency(commissionAmount)}
              </p>
            )}
          </div>
          <button
            type="button"
            onClick={updateHeaderFromSelection}
            className="mt-3 text-sm text-primary hover:underline"
          >
            Kopftext mit Details aktualisieren
          </button>
        </section>

        {/* Rechnungsinformationen */}
        <section className="bg-white rounded-xl border border-gray-200 p-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-4">
            Rechnungsinformationen
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Rechnungsdatum *
              </label>
              <input
                type="date"
                value={invoiceDate}
                onChange={(e) => setInvoiceDate(e.target.value)}
                className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Leistungsraum von *
              </label>
              <input
                type="date"
                value={performancePeriodFrom}
                onChange={(e) => setPerformancePeriodFrom(e.target.value)}
                className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Leistungsraum bis *
              </label>
              <input
                type="date"
                value={performancePeriodTo}
                onChange={(e) => setPerformancePeriodTo(e.target.value)}
                className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Rechnungsnummer *
              </label>
              <div className="flex gap-2">
                <input
                  type="text"
                  value={invoiceNumber}
                  onChange={(e) => setInvoiceNumber(e.target.value)}
                  className="flex-1 px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary"
                />
                <button className="p-2.5 border border-gray-300 rounded-lg hover:bg-gray-50">
                  <Settings className="w-4 h-4" />
                </button>
              </div>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Referenznummer
              </label>
              <input
                type="text"
                value={referenceNumber}
                onChange={(e) => setReferenceNumber(e.target.value)}
                placeholder="Optional"
                className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary"
              />
            </div>
            <div className="min-w-0">
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Zahlungsziel
              </label>
              <div className="flex items-center gap-2 min-w-0 flex-wrap">
                <input
                  type="date"
                  value={format(dueDate, 'yyyy-MM-dd')}
                  readOnly
                  className="min-w-0 flex-1 px-3 py-2.5 border border-gray-300 rounded-lg bg-gray-50"
                />
                <span className="text-sm text-gray-500 shrink-0">in</span>
                <input
                  type="number"
                  value={paymentTermsDays}
                  onChange={(e) =>
                    setPaymentTermsDays(parseInt(e.target.value) || 14)
                  }
                  className="w-16 shrink-0 px-2 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary"
                />
                <span className="text-sm text-gray-500 shrink-0">Tagen</span>
              </div>
            </div>
            <div className="flex items-center">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={reverseCharge}
                  onChange={(e) => setReverseCharge(e.target.checked)}
                  className="w-4 h-4 rounded border-gray-300 text-primary focus:ring-primary"
                />
                <span className="text-sm font-medium text-gray-700">
                  Reverse Charge (Steuerumkehr §13b UStG)
                </span>
              </label>
            </div>
          </div>
        </section>

        {/* Kopftext */}
        <section className="bg-white rounded-xl border border-gray-200 p-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-4">Kopftext</h2>
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Betreff
              </label>
              <input
                type="text"
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
                className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Text
              </label>
              <textarea
                value={headerText}
                onChange={(e) => setHeaderText(e.target.value)}
                rows={6}
                className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary resize-y"
              />
            </div>
          </div>
        </section>

        {/* Zusammenfassung */}
        <section className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm">
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wider mb-4">
            Zusammenfassung
          </h2>
          <div className="max-w-sm ml-auto space-y-3">
            {commissionMode === 'percent' && (
              <>
                <div className="flex justify-between items-center py-2">
                  <span className="text-gray-600">Rechnungsbetrag</span>
                  <span className="font-medium text-gray-900 tabular-nums">
                    {formatCurrency(agreedTotalAmount)}
                  </span>
                </div>
                <div className="flex justify-between items-center py-2">
                  <span className="text-gray-600">Provisionssatz</span>
                  <span className="font-medium text-gray-900 tabular-nums">
                    {commissionRate} %
                  </span>
                </div>
              </>
            )}
            <div className="flex justify-between items-center pt-4 mt-4 border-t-2 border-gray-200 bg-gray-50/50 -mx-4 px-4 py-4 rounded-lg">
              <span className="text-base font-semibold text-gray-900">
                {commissionMode === 'fixed'
                  ? 'Vermittlungsprovision (Pauschale)'
                  : 'Rechnungsbetrag (Provision)'}
              </span>
              <span className="text-2xl font-bold text-primary tabular-nums">
                {formatCurrency(commissionAmount)}
              </span>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
