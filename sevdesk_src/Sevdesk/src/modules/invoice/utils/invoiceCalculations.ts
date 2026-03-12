import type { InvoicePosition } from '../types';

export function calculatePositionNet(position: InvoicePosition): number {
  let amount = position.quantity * position.unitPrice;
  if (position.discount > 0) {
    if (position.discountType === 'percent') {
      amount *= 1 - position.discount / 100;
    } else {
      amount -= position.discount;
    }
  }
  return Math.round(amount * 100) / 100;
}

export function calculatePositionTax(position: InvoicePosition): number {
  const net = calculatePositionNet(position);
  return Math.round((net * (position.taxRate / 100)) * 100) / 100;
}

export function calculatePositionGross(position: InvoicePosition): number {
  const net = calculatePositionNet(position);
  const tax = calculatePositionTax(position);
  return Math.round((net + tax) * 100) / 100;
}

export function calculateInvoiceTotals(positions: InvoicePosition[]) {
  let totalNet = 0;
  let totalTax = 0;

  const taxGroups: Record<number, number> = {};

  for (const pos of positions) {
    const net = calculatePositionNet(pos);
    const tax = calculatePositionTax(pos);
    totalNet += net;
    totalTax += tax;
    taxGroups[pos.taxRate] = (taxGroups[pos.taxRate] || 0) + tax;
  }

  const totalGross = Math.round((totalNet + totalTax) * 100) / 100;
  totalNet = Math.round(totalNet * 100) / 100;
  totalTax = Math.round(totalTax * 100) / 100;

  return { totalNet, totalTax, totalGross, taxGroups };
}

export function formatCurrency(amount: number): string {
  return new Intl.NumberFormat('de-DE', {
    style: 'currency',
    currency: 'EUR',
  }).format(amount);
}
