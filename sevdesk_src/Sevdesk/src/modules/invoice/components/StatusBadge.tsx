import type { InvoiceStatus } from '../types';

const statusConfig: Record<
  InvoiceStatus,
  { label: string; className: string }
> = {
  entwurf: {
    label: 'Entwurf',
    className: 'bg-violet-100 text-violet-700',
  },
  offen: {
    label: 'Offen',
    className: 'bg-amber-100 text-amber-700',
  },
  faellig: {
    label: 'Fällig',
    className: 'bg-red-100 text-red-700',
  },
  bezahlt: {
    label: 'Bezahlt',
    className: 'bg-emerald-100 text-emerald-700',
  },
  festgeschrieben: {
    label: 'Festgeschrieben',
    className: 'bg-slate-100 text-slate-700',
  },
};

interface StatusBadgeProps {
  status: InvoiceStatus;
}

export function StatusBadge({ status }: StatusBadgeProps) {
  const config = statusConfig[status];
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${config.className}`}
    >
      {status === 'bezahlt' && (
        <span className="w-1.5 h-1.5 rounded-full bg-current" />
      )}
      {status === 'faellig' && (
        <span className="w-1.5 h-1.5 rounded-full bg-current" />
      )}
      {status === 'offen' && (
        <span className="w-1.5 h-1.5 rounded-full bg-current" />
      )}
      {config.label}
    </span>
  );
}
