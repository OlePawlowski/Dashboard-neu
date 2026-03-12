import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { Layout } from './components/Layout';
import { InvoiceList, NewInvoice } from './modules/invoice';

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index element={<Navigate to="/rechnungen" replace />} />
          <Route path="rechnungen" element={<InvoiceList />} />
          <Route path="rechnungen/neu" element={<NewInvoice />} />
          <Route path="rechnungen/:id" element={<NewInvoice />} />
        </Route>
        <Route path="*" element={<Navigate to="/rechnungen" replace />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
