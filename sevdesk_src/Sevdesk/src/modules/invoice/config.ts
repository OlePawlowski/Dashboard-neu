/** Firmenkonfiguration für Rechnungen – im CRM anpassen oder überschreiben */
export const COMPANY = {
  name: 'HelpCare GmbH',
  address: 'Kurfürstendamm 14',
  postalCode: '10719',
  city: 'Berlin',
  country: 'Deutschland',
  logoUrl: 'https://helpcare.de/wp-content/uploads/2025/08/logo-HC-footer.png',
  // Im Dashboard läuft das Rechnungsmodul unter /static/rechnungen/,
  // daher liegt das Logo dort und kann direkt über diesen Pfad geladen werden.
  logoLocalPath: '/static/rechnungen/logo-helpcare.png',
  primaryColor: '#f58060',
  primaryColorRgb: [245, 128, 96] as [number, number, number],
  phone: '+49 30 2325357-100',
  email: 'kontakt@helpcare.de',
  bank: {
    name: 'Deutsche Bank',
    iban: 'DE29 1007 0100 0351 6333 00',
    bic: 'DEUTDEBB101',
    taxId: '127/339/00063',
    vatId: '',
  },
};
