import { BrowserRouter, NavLink, Navigate, Route, Routes } from 'react-router-dom'
import App from './App'
import GanttPage from './components/gantt/GanttPage'

function TopNavigation() {
  const tabs = [
    { to: '/', label: 'Campanhas' },
    { to: '/gantt', label: 'Operacao' }
  ]

  return (
    <header className="sticky top-0 z-40 border-b border-slate-200 bg-white/85 backdrop-blur">
      <div className="mx-auto flex w-full max-w-7xl items-center gap-2 px-4 py-3 md:px-6 lg:px-8">
        {tabs.map((tab) => (
          <NavLink
            key={tab.to}
            to={tab.to}
            className={({ isActive }) =>
              `rounded-full px-4 py-1.5 text-sm font-semibold transition ${
                isActive ? 'bg-slate-900 text-white' : 'text-slate-700 hover:bg-slate-100'
              }`
            }
          >
            {tab.label}
          </NavLink>
        ))}
      </div>
    </header>
  )
}

export default function AppRouter() {
  return (
    <BrowserRouter>
      <div className="min-h-screen bg-slate-50">
        <TopNavigation />
        <Routes>
          <Route path="/" element={<App />} />
          <Route path="/gantt" element={<GanttPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </div>
    </BrowserRouter>
  )
}
