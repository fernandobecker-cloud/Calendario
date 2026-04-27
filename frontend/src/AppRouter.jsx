import { useCallback, useEffect, useState } from 'react'
import { BrowserRouter, NavLink, Navigate, Route, Routes } from 'react-router-dom'
import App from './App'
import { clearCredentials, isStoredAuthenticated } from './auth'
import GanttPage from './components/gantt/GanttPage'
import ResultadoGeralPage from './components/ResultadoGeralPage'
import AuditoriaPage from './components/AuditoriaPage'
import AdmPage from './components/AdmPage'
import LoginPage from './components/LoginPage'

const ALL_TABS = [
  { to: '/resultado-geral', label: 'Resultado Geral', key: 'resultado-geral' },
  { to: '/campanhas', label: 'Campanhas', key: 'campanhas' },
  { to: '/gantt', label: 'Projetos', key: 'projetos' },
  { to: '/auditoria', label: 'Auditoria', key: 'auditoria' },
  { to: '/adm', label: 'Adm', key: 'adm' },
]

function TopNavigation({ currentRole, viewerTabs, currentUsername, onLogout }) {
  const visibleTabs = ALL_TABS.filter((tab) => {
    if (tab.key === 'adm') return currentRole === 'admin'
    if (currentRole === 'admin') return true
    if (viewerTabs && viewerTabs[tab.key] === false) return false
    return true
  })

  return (
    <header className="sticky top-0 z-40 border-b border-slate-200 bg-white/85 backdrop-blur">
      <div className="mx-auto flex w-full max-w-7xl items-center gap-2 px-4 py-3 md:px-6 lg:px-8">
        <div className="flex flex-1 flex-wrap items-center gap-2">
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

        <div className="flex shrink-0 items-center gap-3">
          {currentUsername && (
            <span className="hidden text-xs text-slate-400 sm:block">{currentUsername}</span>
          )}
          <button
            type="button"
            onClick={onLogout}
            className="rounded-full border border-slate-200 px-3 py-1.5 text-sm font-semibold text-slate-600 transition hover:bg-slate-100 hover:text-slate-900"
          >
            Sair
          </button>
        </div>
      </div>
    </header>
  )
}

export default function AppRouter() {
  const [authState, setAuthState] = useState('loading')
  const [currentRole, setCurrentRole] = useState(null)
  const [currentUsername, setCurrentUsername] = useState(null)
  const [viewerTabs, setViewerTabs] = useState(null)

  const fetchViewerTabs = useCallback(async () => {
    try {
      const res = await fetch('/api/config/viewer-tabs')
      if (res.ok) setViewerTabs(await res.json())
    } catch {
      // ignore
    }
  }, [])

  const checkAuth = useCallback(async () => {
    if (!isStoredAuthenticated()) {
      setAuthState('unauthenticated')
      return
    }
    try {
      const res = await fetch('/api/me')
      if (!res.ok) {
        clearCredentials()
        setAuthState('unauthenticated')
        return
      }
      const me = await res.json()
      setCurrentRole(me.role)
      setCurrentUsername(me.username)
      if (me.role !== 'admin') await fetchViewerTabs()
      setAuthState('authenticated')
    } catch {
      clearCredentials()
      setAuthState('unauthenticated')
    }
  }, [fetchViewerTabs])

  useEffect(() => {
    checkAuth()
  }, [checkAuth])

  const handleLogin = useCallback(async (username, role) => {
    setCurrentUsername(username)
    setCurrentRole(role)
    if (role !== 'admin') await fetchViewerTabs()
    setAuthState('authenticated')
  }, [fetchViewerTabs])

  const handleLogout = useCallback(() => {
    clearCredentials()
    setCurrentRole(null)
    setCurrentUsername(null)
    setViewerTabs(null)
    setAuthState('unauthenticated')
  }, [])

  if (authState === 'loading') {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50">
        <p className="text-sm text-slate-400">Carregando...</p>
      </div>
    )
  }

  if (authState === 'unauthenticated') {
    return <LoginPage onLogin={handleLogin} />
  }

  return (
    <BrowserRouter>
      <div className="min-h-screen bg-slate-50">
        <TopNavigation
          currentRole={currentRole}
          viewerTabs={viewerTabs}
          currentUsername={currentUsername}
          onLogout={handleLogout}
        />
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
