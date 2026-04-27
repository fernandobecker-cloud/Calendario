import { useEffect, useState } from 'react'
import { BrowserRouter, NavLink, Navigate, Route, Routes } from 'react-router-dom'
import App from './App'
import GanttPage from './components/gantt/GanttPage'
import ResultadoGeralPage from './components/ResultadoGeralPage'
import AuditoriaPage from './components/AuditoriaPage'
import AdmPage from './components/AdmPage'

const ALL_TABS = [
  { to: '/resultado-geral', label: 'Resultado Geral', key: 'resultado-geral' },
  { to: '/campanhas', label: 'Campanhas', key: 'campanhas' },
  { to: '/gantt', label: 'Projetos', key: 'projetos' },
  { to: '/auditoria', label: 'Auditoria', key: 'auditoria' },
  { to: '/adm', label: 'Adm', key: 'adm' },
]

function TopNavigation({ currentRole, viewerTabs }) {
  const visibleTabs = ALL_TABS.filter((tab) => {
    if (tab.key === 'adm') return currentRole === 'admin'
    if (currentRole === 'admin') return true
    if (viewerTabs && viewerTabs[tab.key] === false) return false
    return true
  })

  return (
    <header className="sticky top-0 z-40 border-b border-slate-200 bg-white/85 backdrop-blur">
      <div className="mx-auto flex w-full max-w-7xl items-center gap-2 px-4 py-3 md:px-6 lg:px-8">
        {visibleTabs.map((tab) => (
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
  const [currentRole, setCurrentRole] = useState(null)
  const [viewerTabs, setViewerTabs] = useState(null)

  useEffect(() => {
    async function loadAuth() {
      try {
        const meRes = await fetch('/api/me')
        if (!meRes.ok) return
        const me = await meRes.json()
        setCurrentRole(me.role)
        if (me.role !== 'admin') {
          const tabRes = await fetch('/api/config/viewer-tabs')
          if (tabRes.ok) setViewerTabs(await tabRes.json())
        }
      } catch {
        // ignore — show all tabs on auth error
      }
    }
    loadAuth()
  }, [])

  return (
    <BrowserRouter>
      <div className="min-h-screen bg-slate-50">
        <TopNavigation currentRole={currentRole} viewerTabs={viewerTabs} />
        <Routes>
          <Route path="/" element={<Navigate to="/resultado-geral" replace />} />
          <Route path="/campanhas" element={<App />} />
          <Route path="/gantt" element={<GanttPage />} />
          <Route path="/resultado-geral" element={<ResultadoGeralPage />} />
          <Route path="/auditoria" element={<AuditoriaPage />} />
          <Route path="/adm" element={<AdmPage />} />
          <Route path="*" element={<Navigate to="/resultado-geral" replace />} />
        </Routes>
      </div>
    </BrowserRouter>
  )
}
