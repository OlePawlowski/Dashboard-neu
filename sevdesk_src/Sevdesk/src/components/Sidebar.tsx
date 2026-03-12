import { NavLink } from 'react-router-dom';
import { FileText } from 'lucide-react';

export function Sidebar() {
  return (
    <aside className="w-56 bg-white border-r border-gray-200 flex flex-col shrink-0">
      <nav className="p-2 pt-4">
        <NavLink
          to="/rechnungen"
          className={({ isActive }) =>
            `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
              isActive ? 'bg-primary-light text-primary' : 'text-gray-600 hover:bg-gray-50'
            }`
          }
        >
          <FileText className="w-5 h-5 shrink-0" />
          Rechnungen
        </NavLink>
      </nav>
    </aside>
  );
}
