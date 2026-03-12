import { jsPDF } from 'jspdf';
import autoTable from 'jspdf-autotable';
import { parseISO } from 'date-fns';
import type { Invoice, Partner, Customer } from '../types';
import { formatCurrency } from './invoiceCalculations';
import { COMPANY } from '../config';

function formatDateDe(dateStr: string): string {
  try {
    const d = parseISO(dateStr);
    return `${d.getDate()}.${d.getMonth() + 1}.${d.getFullYear()}`;
  } catch {
    return dateStr;
  }
}

// Entfernt unsichtbare Sonderzeichen, exotische Spaces und Steuerzeichen aus Text,
// damit jsPDF keine „gesperrte“ Darstellung erzeugt.
function cleanTextForPdf(text: string): string {
  return text
    .normalize('NFKC')
    // geschützte und typografische Leerzeichen vereinheitlichen / entfernen
    .replace(/\u00A0/g, ' ')
    .replace(/[\u2000-\u200B\u202F\u205F\u3000]/g, '')
    // Steuerzeichen entfernen
    .replace(/[\u0000-\u001F\u007F]/g, '')
    // Mehrfach-Leerzeichen zu einem machen
    .replace(/[ \t]+/g, ' ')
    .trim();
}

// Korrigiert Adressen, bei denen jedes Zeichen als eigenes „Wort“ mit Space importiert wurde
// (z.B. \"D r o g a   D  b i D s k a  3 A\") und baut daraus wieder normale Wörter.
function normalizeWordSpacing(text: string): string {
  const cleaned = cleanTextForPdf(text);
  if (!cleaned) return '';

  const tokens = cleaned.split(' ').filter(Boolean);
  if (tokens.length <= 4) return cleaned;

  const shortCount = tokens.filter((t) => t.length === 1).length;
  // Nur eingreifen, wenn überwiegend 1-Zeichen-„Wörter“ vorkommen
  if (shortCount / tokens.length < 0.5) return cleaned;

  const result: string[] = [];
  let buffer = '';

  const isSingleWordChar = (ch: string) => /^[A-Za-zÄÖÜäöüß0-9-]$/.test(ch);

  for (const token of tokens) {
    if (token.length === 1 && isSingleWordChar(token)) {
      buffer += token;
    } else {
      if (buffer) {
        result.push(buffer);
        buffer = '';
      }
      result.push(token);
    }
  }
  if (buffer) result.push(buffer);

  return result.join(' ');
}

async function loadLogoAsBase64(
  urls: string[]
): Promise<{ data: string; aspectRatio: number } | null> {
  for (const url of urls) {
    try {
      const img = new Image();
      if (url.startsWith('http')) img.crossOrigin = 'anonymous';
      await new Promise<void>((resolve, reject) => {
        img.onload = () => resolve();
        img.onerror = reject;
        img.src = url;
      });
      const canvas = document.createElement('canvas');
      canvas.width = img.naturalWidth;
      canvas.height = img.naturalHeight;
      const ctx = canvas.getContext('2d');
      if (!ctx) continue;
      ctx.fillStyle = '#ffffff';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(img, 0, 0);
      return {
        data: canvas.toDataURL('image/png'),
        aspectRatio: img.naturalHeight / img.naturalWidth,
      };
    } catch {
      continue;
    }
  }
  return null;
}

async function createInvoiceDoc(
  invoice: Invoice,
  partner: Partner | undefined,
  customer: Customer | undefined
): Promise<jsPDF> {
  const doc = new jsPDF();
  const pageWidth = doc.internal.pageSize.getWidth();
  const pageHeight = doc.internal.pageSize.getHeight();
  const margin = 18;
  const contentWidth = pageWidth - 2 * margin;
  let y = margin;

  const [r, g, b] = COMPANY.primaryColorRgb;

  // === HEADER: Logo + Company (kompakt) ===
  const logoResult = await loadLogoAsBase64([
    window.location.origin + COMPANY.logoLocalPath,
    COMPANY.logoUrl,
  ]);
  if (logoResult) {
    const logoWidth = 52;
    const logoHeight = logoWidth * logoResult.aspectRatio;
    doc.addImage(logoResult.data, 'PNG', margin, y, logoWidth, logoHeight);
  } else {
    doc.setFontSize(12);
    doc.setFont('helvetica', 'bold');
    doc.setTextColor(r, g, b);
    doc.text('HelpCare', margin, y + 8);
    doc.setTextColor(0, 0, 0);
  }

  doc.setFontSize(8);
  doc.setFont('helvetica', 'normal');
  doc.setTextColor(80, 80, 80);
  doc.text(COMPANY.name, pageWidth - margin, y + 4, { align: 'right' });
  doc.text(`${COMPANY.address}, ${COMPANY.postalCode} ${COMPANY.city}`, pageWidth - margin, y + 9, { align: 'right' });
  doc.text(COMPANY.country, pageWidth - margin, y + 14, { align: 'right' });
  doc.setTextColor(0, 0, 0);
  y += 24;

  // === RECHNUNG Titel ===
  doc.setDrawColor(r, g, b);
  doc.setLineWidth(0.4);
  doc.line(margin, y, pageWidth - margin, y);
  y += 8;

  doc.setFontSize(18);
  doc.setFont('helvetica', 'bold');
  doc.setTextColor(r, g, b);
  doc.text(`Rechnung Nr. ${invoice.invoiceNumber}`, margin, y);
  doc.setTextColor(0, 0, 0);
  y += 12;

  // === Zwei Spalten: Rechnungsempfänger | Rechnungsdetails ===
  const colWidth = contentWidth / 2;
  const leftCol = margin;
  const rightCol = margin + colWidth + 10;

  const blockStartY = y;
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(8);
  doc.setTextColor(100, 100, 100);
  doc.text('RECHNUNGSEMPFÄNGER', leftCol, y);
  doc.text('RECHNUNGSDETAILS', rightCol, y);
  y += 5;

  // Max. Breite für Rechnungsempfänger (in mm) – lange Adressen brechen um, aber mit genug Platz
  const recipientMaxWidth = Math.min(colWidth - 2, 70);
  const lineHeight = 5;

  doc.setFont('helvetica', 'normal');
  doc.setFontSize(9);
  doc.setTextColor(0, 0, 0);
  if (partner) {
    const lines: string[] = [];

    const safeName = cleanTextForPdf(partner.name || '');
    if (safeName) {
      lines.push(safeName);
    }

    // Adresse aus dem CRM aufräumen, „gesperrte“ Schreibweisen korrigieren, dann an Kommas trennen
    const rawAddress = normalizeWordSpacing(partner.address || '');
    if (rawAddress) {
      const parts = rawAddress.split(',').map((p) => p.trim()).filter(Boolean);
      if (parts.length === 1) {
        lines.push(parts[0]);
      } else if (parts.length > 1) {
        lines.push(parts[0]); // Straße, Hausnummer
        lines.push(parts.slice(1).join(', ')); // Rest (z.B. Zusatz, Region)
      }
    }

    const plz = normalizeWordSpacing(partner.postalCode || '');
    const city = normalizeWordSpacing(partner.city || '');
    const plzCity = `${plz} ${city}`.trim();
    if (plzCity) {
      lines.push(plzCity);
    }

    const country = cleanTextForPdf(partner.country || '');
    if (country) {
      lines.push(country);
    }

    for (const line of lines) {
      const wrapped = doc.splitTextToSize(line, recipientMaxWidth).filter((s: string) => s.trim() !== '');
      if (wrapped.length) {
        doc.text(wrapped, leftCol, y);
        y += wrapped.length * lineHeight;
      }
    }

    y += 3;
  }

  const rightColEnd = pageWidth - margin;
  let detailY = blockStartY + 5;
  doc.text('Rechnungsnummer:', rightCol, detailY);
  doc.text(invoice.invoiceNumber, rightColEnd, detailY, { align: 'right' });
  detailY += 5;
  doc.text('Rechnungsdatum:', rightCol, detailY);
  doc.text(invoice.invoiceDate, rightColEnd, detailY, { align: 'right' });
  detailY += 5;
  const inv = invoice as { performancePeriodFrom?: string; performancePeriodTo?: string };
  if (inv.performancePeriodFrom && inv.performancePeriodTo) {
    doc.text('Leistungszeitraum:', rightCol, detailY);
    doc.text(
      `${formatDateDe(inv.performancePeriodFrom)} - ${formatDateDe(inv.performancePeriodTo)}`,
      rightColEnd,
      detailY,
      { align: 'right' }
    );
    detailY += 5;
  }
  if (invoice.referenceNumber) {
    doc.text('Referenz:', rightCol, detailY);
    doc.text(invoice.referenceNumber, rightColEnd, detailY, { align: 'right' });
    detailY += 5;
  }
  const detailsBottom = detailY;

  y = Math.max(y, detailsBottom) + 3;

  doc.setFont('helvetica', 'bold');
  doc.setFontSize(8);
  doc.setTextColor(100, 100, 100);
  doc.text('KUNDE', leftCol, y);
  y += 4;
  doc.setFont('helvetica', 'normal');
  doc.setTextColor(0, 0, 0);
  const customerNameLines = doc
    .splitTextToSize(cleanTextForPdf(customer?.name || '-'), recipientMaxWidth)
    .filter((s: string) => s.trim() !== '');
  if (customerNameLines.length) {
    doc.text(customerNameLines, leftCol, y);
    y += customerNameLines.length * lineHeight;
  }
  y += 6;

  // === Betreff ===
  if (invoice.subject) {
    doc.setFont('helvetica', 'bold');
    doc.setFontSize(9);
    doc.text(invoice.subject, margin, y);
    y += 6;
  }

  // === Einleitungstext ===
  if (invoice.headerText) {
    doc.setFont('helvetica', 'normal');
    doc.setFontSize(9);
    doc.setTextColor(60, 60, 60);
    const lines = doc.splitTextToSize(invoice.headerText, contentWidth).filter((s: string) => s.trim() !== '');
    if (lines.length) {
      doc.text(lines, margin, y);
      y += lines.length * 4.5 + 2;
    }
    doc.setTextColor(0, 0, 0);
  }

  // === Positions-Tabelle inkl. Netto/USt/Gesamt (einheitliches Design) ===
  const vatPercent = invoice.reverseCharge ? 0 : 0;
  const vatAmount = invoice.reverseCharge ? 0 : 0;
  const isFixed = invoice.commissionMode === 'fixed';
  const tableData: [string, string][] = [];

  if (!isFixed) {
    tableData.push([
      'Rechnungsbetrag (Partner – Kunde)',
      formatCurrency(invoice.agreedTotalAmount),
    ]);
  }

  tableData.push(
    isFixed
      ? ['Provisionsart', 'Pauschale']
      : ['Provisionssatz', `${invoice.commissionRate} %`]
  );

  tableData.push([
    isFixed
      ? 'Vermittlungsprovision (Pauschale)'
      : 'Vermittlungsprovision (Rechnungsbetrag)',
    formatCurrency(invoice.commissionAmount),
  ]);

  tableData.push(['Gesamtbetrag netto', formatCurrency(invoice.commissionAmount)]);
  tableData.push([`Umsatzsteuer (${vatPercent}%)`, formatCurrency(vatAmount)]);

  autoTable(doc, {
    startY: y,
    head: [['Position', 'Betrag']],
    body: tableData,
    theme: 'plain',
    headStyles: {
      fillColor: [r, g, b],
      textColor: [255, 255, 255],
      fontStyle: 'bold',
      fontSize: 9,
    },
    didParseCell: (data) => {
      if (data.section === 'head' && data.column.index === 1) {
        data.cell.styles.halign = 'right';
      }
    },
    bodyStyles: {
      fontSize: 9,
    },
    alternateRowStyles: {
      fillColor: [248, 248, 248],
    },
    margin: { left: margin, right: margin },
    columnStyles: {
      0: { cellWidth: contentWidth * 0.7 },
      1: { cellWidth: contentWidth * 0.3, halign: 'right', fontStyle: 'bold' },
    },
    tableLineColor: [220, 220, 220],
    tableLineWidth: 0.2,
    styles: { cellPadding: 2 },
  });

  const lastTable = (doc as jsPDF & { lastAutoTable?: { finalY: number } }).lastAutoTable;
  y = (lastTable?.finalY ?? y) + 10;

  // === Rechnungsbetrag (Gesamt) – hervorgehobene Bar ===
  doc.setFillColor(r, g, b);
  doc.rect(margin, y - 3, contentWidth, 11, 'F');
  doc.setTextColor(255, 255, 255);
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(10);
  doc.text('Rechnungsbetrag (Gesamt)', margin + 6, y + 5);
  doc.text(formatCurrency(invoice.commissionAmount), pageWidth - margin - 6, y + 5, {
    align: 'right',
  });
  doc.setTextColor(0, 0, 0);
  y += 14;

  // === Reverse Charge Hinweis ===
  if (invoice.reverseCharge) {
    doc.setFont('helvetica', 'italic');
    doc.setFontSize(8);
    doc.setTextColor(80, 80, 80);
    doc.text(
      'Reverse charge, Steuerschuldnerschaft des Leistungsempfängers § 13b UStG.',
      margin,
      y
    );
    doc.setTextColor(0, 0, 0);
    y += 8;
  }

  // === Zahlungsinformationen (Hinweis über Bankdaten im Footer) ===
  const footerTop = pageHeight - 32;
  if (y + 40 < footerTop) {
    doc.setDrawColor(230, 230, 230);
    doc.setLineWidth(0.3);
    doc.line(margin, y, pageWidth - margin, y);
    y += 6;

    doc.setFont('helvetica', 'bold');
    doc.setFontSize(8);
    doc.setTextColor(80, 80, 80);
    doc.text('ZAHLUNGSINFORMATIONEN', margin, y);
    y += 5;

    doc.setFont('helvetica', 'normal');
    doc.setFontSize(8);
    doc.text(
      'Bitte überweisen Sie den Rechnungsbetrag innerhalb von 14 Tagen unter Angabe der Rechnungsnummer auf das unten angegebene Konto.',
      margin,
      y,
      { maxWidth: contentWidth }
    );
    y += 10;
  }

  // === Footer – 4 Spalten ===
  const footerContentTop = footerTop + 8;

  // Nur dezente Linie, kein grauer Hintergrund
  doc.setDrawColor(200, 200, 205);
  doc.setLineWidth(0.4);
  doc.line(margin, footerTop, pageWidth - margin, footerTop);

  const footerColWidth = contentWidth / 4;
  const col1 = margin;
  const col2 = margin + footerColWidth;
  const col3 = margin + footerColWidth * 2;
  const col4 = margin + footerColWidth * 3;

  doc.setFont('helvetica', 'bold');
  doc.setFontSize(9);
  doc.setTextColor(50, 50, 50);
  doc.text(COMPANY.name, col1, footerContentTop - 2);

  doc.setFont('helvetica', 'normal');
  doc.setFontSize(8);
  doc.setTextColor(60, 60, 60);
  let row = footerContentTop + 4;
  doc.text(COMPANY.address, col1, row);
  row += 4;
  doc.text(`${COMPANY.postalCode} ${COMPANY.city}`, col1, row);
  row += 4;
  doc.text(COMPANY.country, col1, row);

  row = footerContentTop + 4;
  if (COMPANY.phone) {
    doc.text(`Tel. ${COMPANY.phone}`, col2, row);
    row += 4;
  }
  if (COMPANY.email) {
    doc.text(`E-Mail ${COMPANY.email}`, col2, row);
    row += 4;
  }

  row = footerContentTop + 4;
  // Steuer- und Umsatzsteuer-Identifikationsnummer im Footer
  doc.text('Steuer-Nr. 27/339/00063', col3, row);
  row += 4;
  doc.text('USt-IdNr.: DE460444435', col3, row);

  row = footerContentTop + 4;
  doc.text(`Bank ${COMPANY.bank.name}`, col4, row);
  row += 4;
  doc.text(`IBAN ${COMPANY.bank.iban}`, col4, row);
  row += 4;
  doc.text(`BIC ${COMPANY.bank.bic}`, col4, row);

  doc.setFont('helvetica', 'italic');
  doc.setFontSize(7);
  doc.setTextColor(100, 100, 100);
  doc.text(
    'Vielen Dank für Ihr Vertrauen. Bei Fragen stehen wir Ihnen gerne zur Verfügung.',
    margin,
    footerTop + (pageHeight - footerTop) - 5
  );

  return doc;
}

async function generateInvoicePDFInternal(
  invoice: Invoice,
  partner: Partner | undefined,
  customer: Customer | undefined,
  preview: boolean
): Promise<void> {
  const doc = await createInvoiceDoc(invoice, partner, customer);

  if (preview) {
    const blob = doc.output('blob');
    const url = URL.createObjectURL(blob);
    window.open(url, '_blank');
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  } else {
    doc.save(`Rechnung-${invoice.invoiceNumber}.pdf`);
  }
}

export async function generateInvoicePDF(
  invoice: Invoice,
  partner: Partner | undefined,
  customer: Customer | undefined
): Promise<void> {
  return generateInvoicePDFInternal(invoice, partner, customer, false);
}

export async function previewInvoicePDF(
  invoice: Invoice,
  partner: Partner | undefined,
  customer: Customer | undefined
): Promise<void> {
  return generateInvoicePDFInternal(invoice, partner, customer, true);
}

/**
 * Erzeugt das Rechnungs-PDF und gibt es als Data-URL (Base64) zurück,
 * damit es z.B. per E-Mail an das Backend gesendet werden kann.
 */
export async function generateInvoicePDFDataUrl(
  invoice: Invoice,
  partner: Partner | undefined,
  customer: Customer | undefined
): Promise<string> {
  const doc = await createInvoiceDoc(invoice, partner, customer);
  const blob = doc.output('blob');
  const arrayBuffer = await blob.arrayBuffer();
  const bytes = new Uint8Array(arrayBuffer);
  let binary = '';
  for (let i = 0; i < bytes.byteLength; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  const base64 = btoa(binary);
  return `data:application/pdf;base64,${base64}`;
}
