import { useCallback, useEffect, useRef, useState } from 'react'
import { BrowserRouter, NavLink, Navigate, Route, Routes } from 'react-router-dom'
import App from './App'
import { clearCredentials, isStoredAuthenticated } from './auth'
import GanttPage from './components/gantt/GanttPage'
import ResultadoGeralPage from './components/ResultadoGeralPage'
import AuditoriaPage from './components/AuditoriaPage'
import AdmPage from './components/AdmPage'
import PortalMapPage from './components/PortalMapPage'
import LoginPage from './components/LoginPage'

const ALL_TABS = [
  { to: '/resultado-geral', label: 'Resultado Geral', key: 'resultado-geral' },
  { to: '/campanhas', label: 'Campanhas', key: 'campanhas' },
  { to: '/gantt', label: 'Projetos', key: 'projetos' },
  { to: '/auditoria', label: 'Auditoria', key: 'auditoria' },
  { to: '/adm', label: 'Adm', key: 'adm' },
  { to: '/mapa-portal', label: 'Mapa', key: 'mapa' },
]

// 14 min 30 s — desloga antes dos 15 min do Render free entrar em sleep
const INACTIVITY_MS = 14 * 60 * 1000 + 30 * 1000

const ACTIVITY_EVENTS = ['mousemove', 'mousedown', 'keydown', 'touchstart', 'scroll', 'click']

function TopNavigation({ currentRole, viewerTabs, currentUsername, onLogout }) {
  const visibleTabs = ALL_TABS.filter((tab) => {
    if (tab.key === 'adm' || tab.key === 'mapa') return currentRole === 'admin'
    if (tab.key === 'auditoria') return currentUsername === 'crmiplaceadm'
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
  const [sessionMessage, setSessionMessage] = useState(null)
  const inactivityTimer = useRef(null)

  const fetchViewerTabs = useCallback(async () => {
    try {
      const res = await fetch('/api/config/viewer-tabs')
      if (res.ok) setViewerTabs(await res.json())
    } catch {
      // ignore
    }
  }, [])

  const handleLogout = useCallback((reason = null) => {
    clearCredentials()
    if (inactivityTimer.current) {
      clearTimeout(inactivityTimer.current)
      inactivityTimer.current = null
    }
    setCurrentRole(null)
    setCurrentUsername(null)
    setViewerTabs(null)
    setSessionMessage(
      reason === 'inactivity'
        ? 'Sessao encerrada por inatividade. Para continuar, atualize a pagina (F5) e faca login novamente.'
        : null
    )
    setAuthState('unauthenticated')
  }, [])

  const resetInactivityTimer = useCallback(() => {
    if (inactivityTimer.current) clearTimeout(inactivityTimer.current)
    inactivityTimer.current = setTimeout(() => handleLogout('inactivity'), INACTIVITY_MS)
  }, [handleLogout])

  // Liga/desliga o timer de inatividade conforme o estado de autenticacao
  useEffect(() => {
    if (authState !== 'authenticated') {
      if (inactivityTimer.current) {
        clearTimeout(inactivityTimer.current)
        inactivityTimer.current = null
      }
      return
    }

    ACTIVITY_EVENTS.forEach((evt) =>
      window.addEventListener(evt, resetInactivityTimer, { passive: true })
    )
    resetInactivityTimer()

    return () => {
      ACTIVITY_EVENTS.forEach((evt) =>
        window.removeEventListener(evt, resetInactivityTimer)
      )
      if (inactivityTimer.current) {
        clearTimeout(inactivityTimer.current)
        inactivityTimer.current = null
      }
    }
  }, [authState, resetInactivityTimer])

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
    setSessionMessage(null)
    setCurrentUsername(username)
    setCurrentRole(role)
    if (role !== 'admin') await fetchViewerTabs()
    setAuthState('authenticated')
  }, [fetchViewerTabs])

  if (authState === 'loading') {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50">
        <p className="text-sm text-slate-400">Carregando...</p>
      </div>
    )
  }

  if (authState === 'unauthenticated') {
    return <LoginPage onLogin={handleLogin} sessionMessage={sessionMessage} />
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
          <Route path="/resultado-geral" element={<ResultadoGeralPage currentRole={currentRole} />} />
          <Route path="/auditoria" element={currentUsername === 'crmiplaceadm' ? <AuditoriaPage /> : <Navigate to="/resultado-geral" replace />} />
          <Route path="/adm" element={<AdmPage />} />
          <Route path="/mapa-portal" element={<PortalMapPage />} />
          <Route path="*" element={<Navigate to="/resultado-geral" replace />} />
        </Routes>
      </div>
    </BrowserRouter>
  )
}
