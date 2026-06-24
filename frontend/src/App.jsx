import { Fragment, useCallback, useEffect, useMemo, useState } from 'react'
import FullCalendar from '@fullcalendar/react'
import dayGridPlugin from '@fullcalendar/daygrid'
import interactionPlugin from '@fullcalendar/interaction'
import BriefingsPanel from './components/BriefingsPanel'
import PerfilClientePage from './components/PerfilClientePage'

const CHANNEL_COLORS = {
  email: '#0071E3',
  whatsapp: '#25D366',
  sms: '#FF9F0A',
  other: '#8E8E93'
}

const CHANNEL_SOFT = {
  email:    { bg: '#EFF6FF', text: '#1D4ED8', border: '#BFDBFE', label: 'Email' },
  whatsapp: { bg: '#F0FDF4', text: '#15803D', border: '#BBF7D0', label: 'WhatsApp' },
  sms:      { bg: '#FFFBEB', text: '#B45309', border: '#FDE68A', label: 'SMS' },
  other:    { bg: '#F8FAFC', text: '#475569', border: '#E2E8F0', label: 'Outro' },
}

const STATUS_ICON_COLOR = {
  'Cancelada':  '#DC2626',
  'Finalizada': '#16A34A',
}

function StatusIcon({ status, size = 11 }) {
  const props = {
    width: size, height: size, viewBox: '0 0 24 24',
    fill: 'none', stroke: 'currentColor', strokeWidth: 2.2,
    strokeLinecap: 'round', strokeLinejoin: 'round',
    style: { flexShrink: 0 },
  }
  if (status === 'Planejada')
    return <svg {...props}><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
  if (status === 'Briefing Enviado')
    return <svg {...props}><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
  if (status === 'Programada')
    return <svg {...props}><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/><polyline points="9 16 11 18 15 14"/></svg>
  if (status === 'Finalizada')
    return <svg {...props}><path d="M22 11.08V12a10 10 0 11-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
  if (status === 'Cancelada')
    return <svg {...props}><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>
  return <svg {...props}><circle cx="12" cy="12" r="4"/></svg>
}

const CAMPANHAS_MENU_ITEMS = [
  { key: 'calendar', label: 'Calendario CRM' },
  { key: 'utm', label: 'Gerador de Tags UTM' },
  { key: 'future-2', label: 'Checklist de Campanha', disabled: true }
]

const ADM_MENU_ITEMS = [
  { key: 'open-data', label: 'Open Data Emarsys' },
  { key: 'automation-results', label: 'Resultados de Automacoes' },
  { key: 'open-data-explorer', label: 'Explorador de Tabelas' },
  { key: 'comparativo-crm', label: 'Comparativo CRM' },
  { key: 'campanha-detalhe', label: 'Apuracao de Campanhas' },
  { key: 'perfil-cliente', label: 'Perfil do Cliente' },
  { key: 'apple-lover', label: 'Apple Lover' },
  { key: 'permissoes', label: 'Permissoes de Acesso' },
  { key: 'cupom', label: 'Consulta por Cupom' },
  { key: 'acessorios', label: 'Acessórios' },
  { key: 'sms-clientes', label: 'Base SMS' },
]

const TAB_PERMISSION_OPTIONS = [
  { key: 'resultado-geral', label: 'Resultado Geral' },
  { key: 'campanhas', label: 'Campanhas' },
  { key: 'projetos', label: 'Projetos' },
  { key: 'auditoria', label: 'Auditoria' },
]


const OPEN_DATA_LIMIT = 200
const ANNIVERSARY_AUTOMATION_COUPON = 'IPLACEANIVER'
const ANNIVERSARY_AUTOMATION_BASE_MATCHERS = ['00000000aniversario']
const ANNIVERSARY_AUTOMATION_STAGES = [
  {
    key: 'parte1',
    label: 'Parte 1: 7 dias antes do aniversario',
    shortLabel: 'Parte 1',
    matchers: ['aniversarioparte1', 'aniversariopart1'],
    programIds: ['7036']
  },
  {
    key: 'parte2',
    label: 'Parte 2: Dia do aniversario',
    shortLabel: 'Parte 2',
    matchers: ['aniversarioparte2', 'aniversariopart2'],
    programIds: ['7037']
  },
  {
    key: 'parte3',
    label: 'Parte 3: 12 dias apos do aniversario',
    shortLabel: 'Parte 3',
    matchers: ['aniversarioparte3', 'aniversariopart3'],
    programIds: ['7038']
  }
]

function normalizeChannel(channel) {
  const value = String(channel || '').toLowerCase()
  if (value.includes('email')) return 'email'
  if (value.includes('whats')) return 'whatsapp'
  if (value.includes('sms')) return 'sms'
  return 'other'
}

function formatDate(value) {
  if (!value) return 'Sem data'
  // Parseia YYYY-MM-DD como data local para evitar desvio de timezone UTC
  const str = String(value)
  const m = str.match(/^(\d{4})-(\d{2})-(\d{2})/)
  const date = m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : new Date(str)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('pt-BR', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric'
  }).format(date)
}

function formatRole(role) {
  return role === 'admin' ? 'Administrador' : 'Usuario'
}

function formatCreatedAt(value) {
  if (!value) return 'Nao informado'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('pt-BR', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  }).format(date)
}

function formatCurrency(value) {
  return new Intl.NumberFormat('pt-BR', {
    style: 'currency',
    currency: 'BRL',
    minimumFractionDigits: 2
  }).format(Number(value || 0))
}

function RegionalPanel({ data }) {
  const [expandedRegionals, setExpandedRegionals] = useState(new Set())
  const toggle = r => setExpandedRegionals(prev => {
    const next = new Set(prev); next.has(r) ? next.delete(r) : next.add(r); return next
  })
  if (!data?.regionais?.length) return (
    <div className="px-4 py-3 text-xs text-slate-400">Nenhum dado regional encontrado.</div>
  )
  return (
    <div className="p-4 bg-slate-50 space-y-2">
      {data.regionais.map(r => (
        <div key={r.regional} className="rounded-lg border border-slate-200 bg-white overflow-hidden">
          <button onClick={() => toggle(r.regional)}
            className="w-full flex items-center justify-between px-4 py-2.5 text-sm hover:bg-slate-50 text-left">
            <span className="font-semibold text-slate-700">{r.regional}</span>
            <div className="flex items-center gap-4">
              <span className="text-xs text-slate-400">{r.linhas} linhas</span>
              <span className="font-semibold text-emerald-700">{formatCurrency(r.receita)}</span>
              <svg className={`h-3.5 w-3.5 text-slate-400 transition-transform ${expandedRegionals.has(r.regional) ? 'rotate-180' : ''}`}
                viewBox="0 0 20 20" fill="currentColor"><path fillRule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clipRule="evenodd" /></svg>
            </div>
          </button>
          {expandedRegionals.has(r.regional) && (
            <div className="border-t border-slate-100 divide-y divide-slate-50">
              {r.lojas.map(loja => (
                <div key={loja.codigo_filial} className="flex items-center justify-between px-6 py-2 text-xs">
                  <span className="font-medium text-slate-600">{loja.centro_sap} — {loja.nome}</span>
                  <div className="flex items-center gap-4">
                    <span className="text-slate-400">{loja.linhas}p</span>
                    <span className="font-semibold text-slate-700 w-28 text-right">{formatCurrency(loja.receita)}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
      <p className="text-xs text-slate-400 pt-1">
        {data.total_cruzado} pedidos cruzados · {data.total_orders ?? data.total_cpfs} influenciados
      </p>
    </div>
  )
}

function formatOpenDataValue(value) {
  if (value === null || value === undefined || value === '') return '-'
  return String(value)
}

function normalizeLookup(value) {
  return String(value || '')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-zA-Z0-9]+/g, '')
    .toLowerCase()
}

function getMonthDateRange(year, month) {
  const y = Number(year)
  const m = Number(month)
  const safeMonth = Math.min(Math.max(m, 1), 12)
  const lastDay = new Date(y, safeMonth, 0).getDate()
  const monthText = String(safeMonth).padStart(2, '0')
  return {
    start: `${y}-${monthText}-01`,
    end: `${y}-${monthText}-${String(lastDay).padStart(2, '0')}`
  }
}

function getLocalIsoDate(date) {
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

function isGa4NoDataError(detail) {
  const message = String(detail || '').toLowerCase()
  return message.includes('future currency exchange rate not exist')
}

function toCsvValue(value) {
  const text = value === null || value === undefined ? '' : String(value)
  const escaped = text.replace(/"/g, '""')
  return `"${escaped}"`
}

export default function App({ mode = 'campanhas' }) {
  const [activeView, setActiveView] = useState(mode === 'adm' ? 'open-data' : 'calendar')
  const [events, setEvents] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [selectedChannel, setSelectedChannel] = useState('all')
  const [selectedEvent, setSelectedEvent] = useState(null)
  const [eventFormOpen, setEventFormOpen] = useState(false)
  const [eventFormMode, setEventFormMode] = useState('create')
  const [eventFormData, setEventFormData] = useState(null)
  const [eventFormLoading, setEventFormLoading] = useState(false)
  const [eventFormError, setEventFormError] = useState('')
  const [utmForm, setUtmForm] = useState({
    baseUrl: '',
    source: 'email',
    medium: 'crm',
    campaign: '',
    content: '',
    term: ''
  })

  const [currentUser, setCurrentUser] = useState(null)
  const [currentUserError, setCurrentUserError] = useState('')
  const [userManagementEnabled, setUserManagementEnabled] = useState(true)

  const [users, setUsers] = useState([])
  const [usersLoading, setUsersLoading] = useState(false)
  const [usersError, setUsersError] = useState('')
  const [usersSuccess, setUsersSuccess] = useState('')
  const [createLoading, setCreateLoading] = useState(false)
  const [createForm, setCreateForm] = useState({
    username: '',
    password: '',
    role: 'user'
  })
  const [passwordForm, setPasswordForm] = useState({
    currentPassword: '',
    newPassword: '',
    confirmPassword: ''
  })
  const [passwordLoading, setPasswordLoading] = useState(false)
  const [passwordError, setPasswordError] = useState('')
  const [passwordSuccess, setPasswordSuccess] = useState('')
  const [roleDrafts, setRoleDrafts] = useState({})
  const [roleSavingUser, setRoleSavingUser] = useState('')
  const now = useMemo(() => new Date(), [])
  const [openDataHealth, setOpenDataHealth] = useState(null)
  const [openDataItems, setOpenDataItems] = useState([])
  const [openDataOpenRateItems, setOpenDataOpenRateItems] = useState([])
  const [openDataProgramOpenRateItems, setOpenDataProgramOpenRateItems] = useState([])
  const currentMonthRange = useMemo(() => getMonthDateRange(now.getFullYear(), now.getMonth() + 1), [now])
  const [openDataAutomationStartDate, setOpenDataAutomationStartDate] = useState(currentMonthRange.start)
  const [openDataAutomationEndDate, setOpenDataAutomationEndDate] = useState(currentMonthRange.end)
  const [openDataLoading, setOpenDataLoading] = useState(false)
  const [openDataError, setOpenDataError] = useState('')
  const [openDataTables, setOpenDataTables] = useState([])
  const [openDataExplorerTable, setOpenDataExplorerTable] = useState('si_purchases_1091660394')
  const [openDataExplorerStartDate, setOpenDataExplorerStartDate] = useState(currentMonthRange.start)
  const [openDataExplorerEndDate, setOpenDataExplorerEndDate] = useState(currentMonthRange.end)
  const [openDataExplorerLimit, setOpenDataExplorerLimit] = useState(100)
  const [openDataExplorerPreview, setOpenDataExplorerPreview] = useState(null)
  const [openDataExplorerLoading, setOpenDataExplorerLoading] = useState(false)
  const [openDataExplorerError, setOpenDataExplorerError] = useState('')
  const [anniversaryAutomationCouponStats, setAnniversaryAutomationCouponStats] = useState(null)
  const [anniversaryAutomationCouponLoading, setAnniversaryAutomationCouponLoading] = useState(false)
  const [anniversaryAutomationCouponError, setAnniversaryAutomationCouponError] = useState('')
  const [automationEmarsysRevenueItems, setAutomationEmarsysRevenueItems] = useState([])
  const [automationGa4RevenueItems, setAutomationGa4RevenueItems] = useState([])
  const [permissoesDraft, setPermissoesDraft] = useState(null)
  const [permissoesSaving, setPermissoesSaving] = useState(false)
  const [permissoesError, setPermissoesError] = useState('')
  const [permissoesSuccess, setPermissoesSuccess] = useState('')
  const [comparativoCRMData, setComparativoCRMData] = useState(null)
  const [comparativoCRMLoading, setComparativoCRMLoading] = useState(false)
  const [comparativoCRMError, setComparativoCRMError] = useState('')
  const [comparativoCRMStart, setComparativoCRMStart] = useState(currentMonthRange.start)
  const [comparativoCRMEnd, setComparativoCRMEnd] = useState(currentMonthRange.end)
  const [comparativoCRMCanal, setComparativoCRMCanal] = useState('')
  const [smsApuracaoNome, setSmsApuracaoNome] = useState('')
  const [smsApuracaoData, setSmsApuracaoData] = useState(null)
  const [smsApuracaoLoading, setSmsApuracaoLoading] = useState(false)
  const [smsApuracaoError, setSmsApuracaoError] = useState('')
  const [emailApuracaoNome, setEmailApuracaoNome] = useState('')
  const [emailApuracaoData, setEmailApuracaoData] = useState(null)
  const [emailApuracaoLoading, setEmailApuracaoLoading] = useState(false)
  const [emailApuracaoError, setEmailApuracaoError] = useState('')
  const [smsRegional, setSmsRegional] = useState({}) // { [campaign_id]: { loading, error, data, expanded } }
  const [emailRegional, setEmailRegional] = useState({}) // { [campaign_id]: { loading, error, data, expanded } }
  const [appleLoverData, setAppleLoverData] = useState(null)
  const [appleLoverLoading, setAppleLoverLoading] = useState(false)
  const [appleLoverError, setAppleLoverError] = useState('')
  const [appleLoverStart, setAppleLoverStart] = useState(() => {
    const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-01`
  })
  const [appleLoverEnd, setAppleLoverEnd] = useState(() => {
    const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`
  })

  const [acessoriosData, setAcessoriosData] = useState(null)
  const [acessoriosLoading, setAcessoriosLoading] = useState(false)
  const [acessoriosError, setAcessoriosError] = useState('')
  const [acessoriosStart, setAcessoriosStart] = useState(currentMonthRange.start)
  const [acessoriosEnd, setAcessoriosEnd] = useState(currentMonthRange.end)
  const [acessoriosExportLoading, setAcessoriosExportLoading] = useState(false)
  const [acessoriosCanal, setAcessoriosCanal] = useState('')

  const [cupomQuery, setCupomQuery] = useState('')
  const [cupomStart, setCupomStart] = useState(currentMonthRange.start)
  const [cupomEnd, setCupomEnd] = useState(currentMonthRange.end)
  const [cupomData, setCupomData] = useState(null)
  const [cupomLoading, setCupomLoading] = useState(false)
  const [cupomError, setCupomError] = useState('')

  const [smsClientesStart, setSmsClientesStart] = useState(currentMonthRange.start)
  const [smsClientesEnd, setSmsClientesEnd] = useState(currentMonthRange.end)
  const [smsClientesStatus, setSmsClientesStatus] = useState('')
  const [smsClientesData, setSmsClientesData] = useState(null)
  const [smsClientesLoading, setSmsClientesLoading] = useState(false)
  const [smsClientesError, setSmsClientesError] = useState('')
  const [smsStatusOptions, setSmsStatusOptions] = useState([])

  const loadEvents = useCallback(async () => {
    setLoading(true)
    setError('')

    try {
      const response = await fetch('/api/events')
      const contentType = response.headers.get('content-type') || ''
      if (!contentType.includes('application/json')) {
        throw new Error('API respondeu em formato inesperado. Verifique se o backend FastAPI esta rodando na porta 8000.')
      }

      const payload = await response.json()
      if (!response.ok) {
        throw new Error(payload?.detail || payload?.message || 'Falha ao carregar campanhas')
      }
      const apiEvents = Array.isArray(payload?.events) ? payload.events : []

      const normalized = apiEvents.map((event) => {
        const channelKey = normalizeChannel(event?.extendedProps?.canal)

        return {
          ...event,
          allDay: true,
          backgroundColor: 'transparent',
          borderColor: 'transparent',
          extendedProps: {
            ...event.extendedProps,
            channelKey
          }
        }
      })

      setEvents(normalized)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erro inesperado ao buscar campanhas')
      setEvents([])
    } finally {
      setLoading(false)
    }
  }, [])

  const loadCurrentUser = useCallback(async () => {
    setCurrentUserError('')
    try {
      const response = await fetch('/api/auth-config')
      if (!response.ok) throw new Error('Nao foi possivel obter configuracao de autenticacao.')
      const payload = await response.json()
      setCurrentUser(payload?.current_user || null)
      setUserManagementEnabled(Boolean(payload?.user_management_enabled))
    } catch (err) {
      try {
        const response = await fetch('/api/me')
        if (!response.ok) throw new Error('Nao foi possivel obter o usuario logado.')
        const payload = await response.json()
        setCurrentUser(payload)
        setUserManagementEnabled(true)
      } catch (innerErr) {
        setCurrentUser(null)
        setCurrentUserError(innerErr instanceof Error ? innerErr.message : 'Falha ao carregar usuario logado.')
      }
    }
  }, [])

  const loadUsers = useCallback(async () => {
    if (currentUser?.role !== 'admin') return

    setUsersLoading(true)
    setUsersError('')

    try {
      const response = await fetch('/api/users')
      if (!response.ok) throw new Error('Nao foi possivel carregar usuarios.')
      const payload = await response.json()
      const loadedUsers = Array.isArray(payload?.users) ? payload.users : []
      setUsers(loadedUsers)
      setRoleDrafts(
        loadedUsers.reduce((acc, user) => {
          acc[user.username] = user.role
          return acc
        }, {})
      )
    } catch (err) {
      setUsers([])
      setUsersError(err instanceof Error ? err.message : 'Erro ao carregar usuarios.')
    } finally {
      setUsersLoading(false)
    }
  }, [currentUser?.role])

  const readErrorMessage = async (response, fallbackMessage) => {
    try {
      const text = await response.text()
      if (!text || !text.trim()) {
        return fallbackMessage
      }

      try {
        const payload = JSON.parse(text)
        if (typeof payload?.detail === 'string' && payload.detail.trim()) {
          return payload.detail
        }
      } catch (_error) {
        // resposta nao era JSON; devolve texto puro abaixo
      }

      return text.trim()
    } catch (_error) {
      return fallbackMessage
    }
  }

  const loadOpenData = useCallback(async () => {
    setOpenDataLoading(true)
    setOpenDataError('')
    let nextHealthPayload = null

    try {
      const openDataParams = new URLSearchParams({
        limit: String(OPEN_DATA_LIMIT),
        start: openDataAutomationStartDate,
        end: openDataAutomationEndDate
      })

      const emarsysRevenueParams = new URLSearchParams({
        start: openDataAutomationStartDate,
        end: openDataAutomationEndDate
      })
      ANNIVERSARY_AUTOMATION_STAGES.flatMap((stage) => stage.programIds).forEach((pid) =>
        emarsysRevenueParams.append('program_id', pid)
      )

      const ga4RevenueParams = new URLSearchParams({
        start: openDataAutomationStartDate,
        end: openDataAutomationEndDate
      })

      const [healthResponse, campaignsResponse, openRatesResponse, programOpenRatesResponse, emarsysRevenueResponse, ga4RevenueResponse] =
        await Promise.all([
          fetch('/api/open-data/emarsys/health'),
          fetch(`/api/open-data/emarsys/email-campaigns?${openDataParams.toString()}`),
          fetch(`/api/open-data/emarsys/email-open-rates?${openDataParams.toString()}`),
          fetch(`/api/open-data/emarsys/email-program-open-rates?${openDataParams.toString()}`),
          fetch(`/api/open-data/emarsys/automation-program-revenue?${emarsysRevenueParams.toString()}`),
          fetch(`/api/ga4/automation-revenue-by-campaign?${ga4RevenueParams.toString()}`)
        ])

      if (!healthResponse.ok) {
        const message = await readErrorMessage(healthResponse, 'Nao foi possivel validar a conexao com o Open Data.')
        throw new Error(message)
      }

      nextHealthPayload = await healthResponse.json()
      setOpenDataHealth(nextHealthPayload)

      const errors = []

      if (!campaignsResponse.ok) {
        const message = await readErrorMessage(campaignsResponse, 'Nao foi possivel carregar campanhas do Open Data.')
        setOpenDataItems([])
        errors.push(message)
      } else {
        const campaignsPayload = await campaignsResponse.json()
        setOpenDataItems(Array.isArray(campaignsPayload?.items) ? campaignsPayload.items : [])
      }

      if (!openRatesResponse.ok) {
        const message = await readErrorMessage(openRatesResponse, 'Nao foi possivel carregar taxas de abertura do Open Data.')
        setOpenDataOpenRateItems([])
        errors.push(message)
      } else {
        const openRatesPayload = await openRatesResponse.json()
        setOpenDataOpenRateItems(Array.isArray(openRatesPayload?.items) ? openRatesPayload.items : [])
      }

      if (!programOpenRatesResponse.ok) {
        const message = await readErrorMessage(
          programOpenRatesResponse,
          'Nao foi possivel carregar taxas de abertura por programa do Open Data.'
        )
        setOpenDataProgramOpenRateItems([])
        errors.push(message)
      } else {
        const programOpenRatesPayload = await programOpenRatesResponse.json()
        setOpenDataProgramOpenRateItems(Array.isArray(programOpenRatesPayload?.items) ? programOpenRatesPayload.items : [])
      }

      if (!emarsysRevenueResponse.ok) {
        setAutomationEmarsysRevenueItems([])
        const message = await readErrorMessage(emarsysRevenueResponse, 'Nao foi possivel carregar a receita Emarsys.')
        errors.push(message)
      } else {
        const payload = await emarsysRevenueResponse.json()
        setAutomationEmarsysRevenueItems(Array.isArray(payload?.items) ? payload.items : [])
      }

      if (!ga4RevenueResponse.ok) {
        setAutomationGa4RevenueItems([])
      } else {
        const payload = await ga4RevenueResponse.json()
        setAutomationGa4RevenueItems(Array.isArray(payload?.items) ? payload.items : [])
      }

      if (errors.length > 0) {
        setOpenDataError(errors.join(' | '))
      }
    } catch (err) {
      setOpenDataHealth(nextHealthPayload)
      setOpenDataItems([])
      setOpenDataOpenRateItems([])
      setOpenDataProgramOpenRateItems([])
      setAutomationEmarsysRevenueItems([])
      setAutomationGa4RevenueItems([])
      setOpenDataError(err instanceof Error ? err.message : 'Falha ao carregar Open Data da Emarsys.')
    } finally {
      setOpenDataLoading(false)
    }
  }, [openDataAutomationEndDate, openDataAutomationStartDate])

  const loadOpenDataTables = useCallback(async () => {
    setOpenDataExplorerError('')

    try {
      const response = await fetch('/api/open-data/emarsys/tables')
      const message = !response.ok ? await readErrorMessage(response, 'Nao foi possivel listar tabelas do Open Data.') : ''
      if (!response.ok) throw new Error(message)
      const payload = await response.json()
      const items = Array.isArray(payload?.items) ? payload.items : []
      setOpenDataTables(items)
      if (!items.some((item) => item.table_name === openDataExplorerTable) && items[0]?.table_name) {
        setOpenDataExplorerTable(items[0].table_name)
      }
    } catch (err) {
      setOpenDataTables([])
      setOpenDataExplorerError(err instanceof Error ? err.message : 'Falha ao listar tabelas do Open Data.')
    }
  }, [openDataExplorerTable])

  const loadOpenDataExplorerPreview = useCallback(async () => {
    if (!openDataExplorerTable) {
      setOpenDataExplorerPreview(null)
      return
    }

    setOpenDataExplorerLoading(true)
    setOpenDataExplorerError('')

    try {
      const params = new URLSearchParams({
        table: openDataExplorerTable,
        limit: String(openDataExplorerLimit),
        start: openDataExplorerStartDate,
        end: openDataExplorerEndDate
      })
      const response = await fetch(`/api/open-data/emarsys/table-preview?${params.toString()}`)
      const message = !response.ok ? await readErrorMessage(response, 'Nao foi possivel carregar a tabela do Open Data.') : ''
      if (!response.ok) throw new Error(message)
      const payload = await response.json()
      setOpenDataExplorerPreview(payload)
    } catch (err) {
      setOpenDataExplorerPreview(null)
      setOpenDataExplorerError(err instanceof Error ? err.message : 'Falha ao carregar a tabela do Open Data.')
    } finally {
      setOpenDataExplorerLoading(false)
    }
  }, [openDataExplorerEndDate, openDataExplorerLimit, openDataExplorerStartDate, openDataExplorerTable])

  useEffect(() => {
    loadCurrentUser()
  }, [loadCurrentUser])

  useEffect(() => {
    if (activeView === 'users') {
      loadUsers()
    }
  }, [activeView, loadUsers])


  useEffect(() => {
    if (activeView === 'open-data-explorer') {
      loadOpenDataTables()
    }
  }, [activeView, loadOpenDataTables])

  useEffect(() => {
    if (activeView === 'open-data-explorer') {
      loadOpenDataExplorerPreview()
    }
  }, [activeView, loadOpenDataExplorerPreview])

  useEffect(() => {
    if (!userManagementEnabled && activeView === 'users') {
      setActiveView('calendar')
    }
  }, [activeView, userManagementEnabled])

  const menuItems = useMemo(() => {
    if (mode === 'adm') return ADM_MENU_ITEMS
    const base = CAMPANHAS_MENU_ITEMS
    if (!userManagementEnabled) return base
    return [...base, { key: 'users', label: 'Usuarios e Perfis' }]
  }, [mode, userManagementEnabled])

  const filteredEvents = useMemo(() => {
    if (selectedChannel === 'all') return events
    return events.filter((event) => event?.extendedProps?.channelKey === selectedChannel)
  }, [events, selectedChannel])

  const openDataOpenRatesByCampaign = useMemo(() => {
    return openDataOpenRateItems.reduce((acc, item) => {
      const key = `${item.campaign_id || ''}-${item.data || ''}`
      acc[key] = item
      return acc
    }, {})
  }, [openDataOpenRateItems])

  // The server already filters by date range; no client-side date filter needed.
  const filteredAutomationOpenRateItems = openDataProgramOpenRateItems

  const anniversaryAutomationStages = useMemo(() => {
    const emarsysRevenueByProgram = automationEmarsysRevenueItems.reduce((acc, item) => {
      const programId = String(item.program_id || '').trim()
      if (programId) acc[programId] = Number(item.receita || 0)
      return acc
    }, {})

    const ga4RevenueByStage = {}
    for (const item of automationGa4RevenueItems) {
      const normalizedName = normalizeLookup(item.campaignName || '')
      for (const stage of ANNIVERSARY_AUTOMATION_STAGES) {
        const matchesStage = stage.matchers.some((matcher) => normalizedName.includes(matcher))
        if (matchesStage) {
          ga4RevenueByStage[stage.key] = (ga4RevenueByStage[stage.key] || 0) + Number(item.purchaseRevenue || 0)
          break
        }
      }
    }

    return ANNIVERSARY_AUTOMATION_STAGES.map((stage) => {
      const items = filteredAutomationOpenRateItems.filter((item) => {
        const sends = Number(item.enviados || 0)
        if (sends <= 0) return false

        const normalizedCampaign = normalizeLookup(item.campanha)
        const programId = String(item.program_id || '').trim()
        const matchesBase = ANNIVERSARY_AUTOMATION_BASE_MATCHERS.some((matcher) => normalizedCampaign.includes(matcher))
        const matchesStageName = stage.matchers.some((matcher) => normalizedCampaign.includes(matcher))
        const matchesProgramId = Array.isArray(stage.programIds)
          ? stage.programIds.includes(programId)
          : false

        return (matchesBase && matchesStageName) || matchesProgramId
      })
      const sends = items.reduce((sum, item) => sum + Number(item.enviados || 0), 0)
      const opens = items.reduce((sum, item) => sum + Number(item.aberturas_unicas || 0), 0)
      const openRate = sends > 0 ? (opens / sends) * 100 : 0
      const emarsysRevenue = (stage.programIds || []).reduce((sum, pid) => sum + (emarsysRevenueByProgram[pid] || 0), 0)
      const ga4Revenue = ga4RevenueByStage[stage.key] || 0

      return {
        ...stage,
        items,
        sends,
        opens,
        openRate,
        emarsysRevenue,
        ga4Revenue
      }
    })
  }, [openDataProgramOpenRateItems, automationEmarsysRevenueItems, automationGa4RevenueItems])

  const anniversaryAutomationTotals = useMemo(() => {
    const sends = anniversaryAutomationStages.reduce((sum, stage) => sum + stage.sends, 0)
    const opens = anniversaryAutomationStages.reduce((sum, stage) => sum + stage.opens, 0)
    const emarsysRevenue = anniversaryAutomationStages.reduce((sum, stage) => sum + stage.emarsysRevenue, 0)
    const ga4Revenue = anniversaryAutomationStages.reduce((sum, stage) => sum + stage.ga4Revenue, 0)
    return {
      sends,
      opens,
      openRate: sends > 0 ? (opens / sends) * 100 : 0,
      emarsysRevenue,
      ga4Revenue
    }
  }, [anniversaryAutomationStages])

  const loadAnniversaryAutomationCouponStats = useCallback(async () => {
    if (!openDataAutomationStartDate || !openDataAutomationEndDate) {
      setAnniversaryAutomationCouponStats(null)
      setAnniversaryAutomationCouponError('')
      return
    }

    setAnniversaryAutomationCouponLoading(true)
    setAnniversaryAutomationCouponError('')

    try {
      const params = new URLSearchParams({
        start: openDataAutomationStartDate,
        end: openDataAutomationEndDate
      })
      params.append('coupon', ANNIVERSARY_AUTOMATION_COUPON)

      const response = await fetch(`/api/ga4/coupon-orders?${params.toString()}`)
      let payload = null
      try {
        payload = await response.json()
      } catch (_error) {
        payload = null
      }

      if (!response.ok) {
        const detail = payload?.detail || 'Nao foi possivel carregar a receita da automacao de aniversario.'
        if (isGa4NoDataError(detail)) {
          setAnniversaryAutomationCouponStats(null)
          setAnniversaryAutomationCouponError('')
          return
        }
        throw new Error(detail)
      }

      setAnniversaryAutomationCouponStats(payload)
    } catch (err) {
      setAnniversaryAutomationCouponStats(null)
      setAnniversaryAutomationCouponError(
        err instanceof Error ? err.message : 'Falha ao carregar a receita da automacao de aniversario.'
      )
    } finally {
      setAnniversaryAutomationCouponLoading(false)
    }
  }, [openDataAutomationEndDate, openDataAutomationStartDate])


  useEffect(() => {
    if (activeView !== 'permissoes') return
    setPermissoesError('')
    setPermissoesSuccess('')
    fetch('/api/config/viewer-tabs')
      .then((r) => r.json())
      .then((data) => setPermissoesDraft(data))
      .catch(() => setPermissoesError('Nao foi possivel carregar as permissoes.'))
  }, [activeView])

  const loadComparativoCRM = useCallback(async (canalOverride) => {
    if (!comparativoCRMStart || !comparativoCRMEnd) return
    const canal = canalOverride !== undefined ? canalOverride : comparativoCRMCanal
    setComparativoCRMLoading(true)
    setComparativoCRMError('')
    try {
      const params = new URLSearchParams({ start: comparativoCRMStart, end: comparativoCRMEnd })
      if (canal) params.set('canal', canal)
      const res = await fetch(`/api/open-data/comparativo-crm?${params}`)
      const payload = await res.json()
      if (!res.ok) throw new Error(payload?.detail || 'Erro ao calcular comparativo CRM.')
      setComparativoCRMData(payload)
    } catch (err) {
      setComparativoCRMError(err instanceof Error ? err.message : 'Erro inesperado.')
      setComparativoCRMData(null)
    } finally {
      setComparativoCRMLoading(false)
    }
  }, [comparativoCRMStart, comparativoCRMEnd, comparativoCRMCanal])


  const loadSmsApuracao = useCallback(async () => {
    if (smsApuracaoNome.trim().length < 2) return
    setSmsApuracaoLoading(true)
    setSmsApuracaoError('')
    try {
      const params = new URLSearchParams({ nome: smsApuracaoNome.trim() })
      const res = await fetch(`/api/open-data/sms-apuracao?${params}`)
      const payload = await res.json()
      if (!res.ok) throw new Error(payload?.detail || 'Erro ao apurar SMS.')
      setSmsApuracaoData(payload)
    } catch (err) {
      setSmsApuracaoError(err instanceof Error ? err.message : 'Erro inesperado.')
      setSmsApuracaoData(null)
    } finally {
      setSmsApuracaoLoading(false)
    }
  }, [smsApuracaoNome])

  const loadEmailApuracao = useCallback(async () => {
    if (emailApuracaoNome.trim().length < 2) return
    setEmailApuracaoLoading(true)
    setEmailApuracaoError('')
    try {
      const params = new URLSearchParams({ nome: emailApuracaoNome.trim() })
      const res = await fetch(`/api/open-data/email-apuracao?${params}`)
      const payload = await res.json()
      if (!res.ok) throw new Error(payload?.detail || 'Erro ao apurar e-mail.')
      setEmailApuracaoData(payload)
    } catch (err) {
      setEmailApuracaoError(err instanceof Error ? err.message : 'Erro inesperado.')
      setEmailApuracaoData(null)
    } finally {
      setEmailApuracaoLoading(false)
    }
  }, [emailApuracaoNome])

  const toggleSmsRegional = useCallback(async (campaignId, dispatchDate) => {
    setSmsRegional(prev => {
      const cur = prev[campaignId] || {}
      if (cur.data || cur.loading) return { ...prev, [campaignId]: { ...cur, expanded: !cur.expanded } }
      return { ...prev, [campaignId]: { loading: true, error: '', data: null, expanded: true } }
    })
    setSmsRegional(prev => {
      if (prev[campaignId]?.data || prev[campaignId]?.loading === false) return prev
      const params = new URLSearchParams({ campaign_id: campaignId, date: dispatchDate })
      fetch(`/api/open-data/sms-apuracao-regional?${params}`)
        .then(r => r.json().then(d => ({ ok: r.ok, d })))
        .then(({ ok, d }) => {
          const errMsg = ok ? '' : (Array.isArray(d?.detail) ? d.detail.map(e => e.msg || JSON.stringify(e)).join('; ') : (d?.detail || 'Erro'))
          setSmsRegional(p => ({ ...p, [campaignId]: { loading: false, error: errMsg, data: ok ? d : null, expanded: true } }))
        })
        .catch(err => {
          setSmsRegional(p => ({ ...p, [campaignId]: { loading: false, error: err.message || 'Erro', data: null, expanded: true } }))
        })
      return prev
    })
  }, [])

  const toggleEmailRegional = useCallback(async (campaignId, startDate, endDate) => {
    setEmailRegional(prev => {
      const cur = prev[campaignId] || {}
      if (cur.data || cur.loading) return { ...prev, [campaignId]: { ...cur, expanded: !cur.expanded } }
      return { ...prev, [campaignId]: { loading: true, error: '', data: null, expanded: true } }
    })
    setEmailRegional(prev => {
      if (prev[campaignId]?.data || prev[campaignId]?.loading === false) return prev
      const params = new URLSearchParams({ campaign_id: campaignId, start: startDate, end: endDate })
      fetch(`/api/open-data/email-apuracao-regional?${params}`)
        .then(r => r.json().then(d => ({ ok: r.ok, d })))
        .then(({ ok, d }) => {
          const errMsg = ok ? '' : (Array.isArray(d?.detail) ? d.detail.map(e => e.msg || JSON.stringify(e)).join('; ') : (d?.detail || 'Erro'))
          setEmailRegional(p => ({ ...p, [campaignId]: { loading: false, error: errMsg, data: ok ? d : null, expanded: true } }))
        })
        .catch(err => {
          setEmailRegional(p => ({ ...p, [campaignId]: { loading: false, error: err.message || 'Erro', data: null, expanded: true } }))
        })
      return prev
    })
  }, [])

  const loadAppleLover = useCallback(async () => {
    setAppleLoverLoading(true)
    setAppleLoverError('')
    try {
      const params = new URLSearchParams({ start: appleLoverStart, end: appleLoverEnd })
      const res = await fetch(`/api/open-data/apple-lover/tiers?${params}`)
      const text = await res.text()
      let payload = null
      try { payload = text ? JSON.parse(text) : null } catch (_) { /* handled below */ }
      if (!res.ok) throw new Error(payload?.detail || `HTTP ${res.status}`)
      if (!payload) throw new Error('A API nao retornou dados.')
      setAppleLoverData(payload)
    } catch (err) {
      setAppleLoverError(err instanceof Error ? err.message : 'Erro inesperado.')
      setAppleLoverData(null)
    } finally {
      setAppleLoverLoading(false)
    }
  }, [appleLoverStart, appleLoverEnd])

  const loadAcessorios = useCallback(async (canalOverride) => {
    setAcessoriosLoading(true)
    setAcessoriosError('')
    setAcessoriosData(null)
    try {
      const canal = canalOverride !== undefined ? canalOverride : acessoriosCanal
      const params = new URLSearchParams({ start: acessoriosStart, end: acessoriosEnd })
      if (canal) params.set('canal', canal)
      const res = await fetch(`/api/open-data/acessorios?${params}`)
      const text = await res.text()
      let payload = null
      try { payload = text ? JSON.parse(text) : null } catch (_) { /* handled below */ }
      if (!res.ok) throw new Error(payload?.detail || `HTTP ${res.status}`)
      if (!payload) throw new Error('A API nao retornou dados.')
      setAcessoriosData(payload)
    } catch (err) {
      setAcessoriosError(err instanceof Error ? err.message : 'Erro inesperado.')
    } finally {
      setAcessoriosLoading(false)
    }
  }, [acessoriosStart, acessoriosEnd, acessoriosCanal])

  const loadCupom = useCallback(async () => {
    const codes = cupomQuery.trim().toUpperCase().split(/[\s,;]+/).filter(Boolean)
    if (!codes.length) return
    setCupomLoading(true)
    setCupomError('')
    setCupomData(null)
    try {
      const params = new URLSearchParams({ start: cupomStart, end: cupomEnd })
      codes.forEach((c) => params.append('coupon', c))
      const res = await fetch(`/api/ga4/coupon-orders?${params}`)
      const text = await res.text()
      let payload = null
      try { payload = text ? JSON.parse(text) : null } catch (_) { /* handled below */ }
      if (!res.ok) throw new Error(payload?.detail || `HTTP ${res.status}`)
      if (!payload) throw new Error('A API nao retornou dados.')
      setCupomData(payload)
    } catch (err) {
      setCupomError(err instanceof Error ? err.message : 'Erro inesperado.')
    } finally {
      setCupomLoading(false)
    }
  }, [cupomQuery, cupomStart, cupomEnd])

  const loadSmsStatusOptions = useCallback(async (start, end) => {
    if (!start || !end) return
    try {
      const params = new URLSearchParams({ start, end })
      const res = await fetch(`/api/open-data/sms-status-options?${params}`)
      const text = await res.text()
      let payload = null
      try { payload = text ? JSON.parse(text) : null } catch (_) { /* ignore */ }
      if (res.ok && payload?.items) setSmsStatusOptions(payload.items.map((i) => i.status))
    } catch (_) { /* ignore status load errors */ }
  }, [])

  useEffect(() => {
    if (activeView === 'sms-clientes') {
      loadSmsStatusOptions(smsClientesStart, smsClientesEnd)
    }
  }, [activeView, smsClientesStart, smsClientesEnd, loadSmsStatusOptions])

  const loadSmsClientes = useCallback(async () => {
    if (!smsClientesStart || !smsClientesEnd) return
    setSmsClientesLoading(true)
    setSmsClientesError('')
    setSmsClientesData(null)
    try {
      const params = new URLSearchParams({ start: smsClientesStart, end: smsClientesEnd })
      if (smsClientesStatus) params.set('status', smsClientesStatus)
      const res = await fetch(`/api/open-data/sms-clientes?${params}`)
      const text = await res.text()
      let payload = null
      try { payload = text ? JSON.parse(text) : null } catch (_) { /* handled below */ }
      if (!res.ok) throw new Error(payload?.detail || `HTTP ${res.status}`)
      if (!payload) throw new Error('A API nao retornou dados.')
      setSmsClientesData(payload)
    } catch (err) {
      setSmsClientesError(err instanceof Error ? err.message : 'Erro inesperado.')
    } finally {
      setSmsClientesLoading(false)
    }
  }, [smsClientesStart, smsClientesEnd, smsClientesStatus])

  const saturationDays = useMemo(() => {
    const today = new Date()
    today.setHours(0, 0, 0, 0)
    const limit = new Date(today)
    limit.setDate(limit.getDate() + 30)
    const map = {}
    filteredEvents.forEach((event) => {
      const key = event.start
      if (!key) return
      const d = new Date(key + 'T00:00:00')
      if (d < today || d > limit) return
      map[key] = (map[key] || 0) + 1
    })
    return Object.entries(map).filter(([, count]) => count >= 3)
  }, [filteredEvents])

  const handleEventClick = useCallback((clickInfo) => {
    setSelectedEvent(clickInfo.event)
  }, [])

  const closeModal = useCallback(() => {
    setSelectedEvent(null)
  }, [])

  const openCreateForm = useCallback(() => {
    setEventFormData({ data: '', campanha: '', canal: '', direcionamento: '', status: '', produto: '', observacao: '' })
    setEventFormMode('create')
    setEventFormError('')
    setEventFormOpen(true)
  }, [])

  const openEditForm = useCallback((event) => {
    const p = event.extendedProps || {}
    setEventFormData({
      data: event.startStr || (typeof event.start === 'string' ? event.start.slice(0, 10) : '') || '',
      campanha: p.titulo_original || '',
      canal: p.canal || '',
      direcionamento: p.direcionamento || '',
      status: p.status || '',
      produto: p.produto || '',
      observacao: p.observacao || '',
      _row: p._row,
    })
    setEventFormMode('edit')
    setEventFormError('')
    setEventFormOpen(true)
    setSelectedEvent(null)
  }, [])

  const handleSaveEvent = useCallback(async (formData) => {
    setEventFormLoading(true)
    setEventFormError('')
    try {
      const body = { ...formData }
      delete body._row
      const isEdit = eventFormMode === 'edit' && formData._row
      const url = isEdit ? `/api/events/${formData._row}` : '/api/events'
      const method = isEdit ? 'PUT' : 'POST'
      const res = await fetch(url, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      const payload = await res.json()
      if (!res.ok) throw new Error(payload?.detail || 'Erro ao salvar campanha.')
      setEventFormOpen(false)
      loadEvents()
    } catch (err) {
      setEventFormError(err instanceof Error ? err.message : 'Erro inesperado.')
    } finally {
      setEventFormLoading(false)
    }
  }, [eventFormMode, loadEvents])

  const handleDeleteEvent = useCallback(async (row) => {
    if (!window.confirm('Excluir esta campanha da planilha?')) return
    try {
      const res = await fetch(`/api/events/${row}`, { method: 'DELETE' })
      if (!res.ok) { const p = await res.json(); throw new Error(p?.detail || 'Erro ao excluir.') }
      setSelectedEvent(null)
      loadEvents()
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Erro inesperado ao excluir.')
    }
  }, [loadEvents])

  const handleDatesSet = useCallback(() => {
    loadEvents()
  }, [loadEvents])

  const handleRefresh = useCallback(() => {
    loadEvents()
  }, [loadEvents])

  const handleCreateUser = useCallback(
    async (event) => {
      event.preventDefault()
      setUsersError('')
      setUsersSuccess('')

      if (!createForm.username || !createForm.password) {
        setUsersError('Preencha usuario e senha.')
        return
      }

      setCreateLoading(true)

      try {
        const response = await fetch('/api/users', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(createForm)
        })

        let payload = null
        try {
          payload = await response.json()
        } catch (_error) {
          payload = null
        }

        if (!response.ok) {
          const detail = payload?.detail || 'Nao foi possivel cadastrar usuario.'
          throw new Error(detail)
        }

        setCreateForm({ username: '', password: '', role: 'user' })
        setUsersSuccess(`Usuario ${payload?.username || createForm.username} cadastrado com sucesso.`)
        await loadUsers()
      } catch (err) {
        setUsersError(err instanceof Error ? err.message : 'Erro ao cadastrar usuario.')
      } finally {
        setCreateLoading(false)
      }
    },
    [createForm, loadUsers]
  )

  const handleDeleteUser = useCallback(
    async (username) => {
      const shouldDelete = window.confirm(`Deseja descadastrar o usuario "${username}"?`)
      if (!shouldDelete) return

      setUsersError('')
      setUsersSuccess('')
      setUsersLoading(true)

      try {
        const response = await fetch(`/api/users/${encodeURIComponent(username)}`, {
          method: 'DELETE'
        })

        let payload = null
        try {
          payload = await response.json()
        } catch (_error) {
          payload = null
        }

        if (!response.ok) {
          const detail = payload?.detail || 'Nao foi possivel descadastrar usuario.'
          throw new Error(detail)
        }

        setUsersSuccess(`Usuario ${username} removido com sucesso.`)
        await loadUsers()
      } catch (err) {
        setUsersError(err instanceof Error ? err.message : 'Erro ao remover usuario.')
      } finally {
        setUsersLoading(false)
      }
    },
    [loadUsers]
  )

  const handleChangeMyPassword = useCallback(
    async (event) => {
      event.preventDefault()
      setPasswordError('')
      setPasswordSuccess('')

      if (!passwordForm.currentPassword || !passwordForm.newPassword) {
        setPasswordError('Preencha senha atual e nova senha.')
        return
      }

      if (passwordForm.newPassword !== passwordForm.confirmPassword) {
        setPasswordError('A confirmacao da nova senha nao confere.')
        return
      }

      setPasswordLoading(true)
      try {
        const response = await fetch('/api/me/password', {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            current_password: passwordForm.currentPassword,
            new_password: passwordForm.newPassword
          })
        })

        let payload = null
        try {
          payload = await response.json()
        } catch (_error) {
          payload = null
        }

        if (!response.ok) {
          const detail = payload?.detail || 'Nao foi possivel alterar a senha.'
          throw new Error(detail)
        }

        setPasswordForm({ currentPassword: '', newPassword: '', confirmPassword: '' })
        setPasswordSuccess('Senha alterada com sucesso. No proximo login use a nova senha.')
      } catch (err) {
        setPasswordError(err instanceof Error ? err.message : 'Erro ao alterar senha.')
      } finally {
        setPasswordLoading(false)
      }
    },
    [passwordForm]
  )

  const handleUpdateRole = useCallback(
    async (username) => {
      const nextRole = roleDrafts[username]
      if (!nextRole) return

      setUsersError('')
      setUsersSuccess('')
      setRoleSavingUser(username)

      try {
        const response = await fetch(`/api/users/${encodeURIComponent(username)}/role`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ role: nextRole })
        })

        let payload = null
        try {
          payload = await response.json()
        } catch (_error) {
          payload = null
        }

        if (!response.ok) {
          const detail = payload?.detail || 'Nao foi possivel atualizar o perfil.'
          throw new Error(detail)
        }

        setUsersSuccess(`Perfil de ${username} atualizado para ${formatRole(nextRole)}.`)
        await loadUsers()
      } catch (err) {
        setUsersError(err instanceof Error ? err.message : 'Erro ao atualizar perfil.')
      } finally {
        setRoleSavingUser('')
      }
    },
    [roleDrafts, loadUsers]
  )

  const utmUrl = useMemo(() => {
    if (!utmForm.baseUrl || !utmForm.campaign) return ''

    try {
      const url = new URL(utmForm.baseUrl)
      url.searchParams.set('utm_source', utmForm.source)
      url.searchParams.set('utm_medium', utmForm.medium)
      url.searchParams.set('utm_campaign', utmForm.campaign)

      if (utmForm.content) url.searchParams.set('utm_content', utmForm.content)
      if (utmForm.term) url.searchParams.set('utm_term', utmForm.term)

      return url.toString()
    } catch (_error) {
      return ''
    }
  }, [utmForm])

  const copyUtmUrl = useCallback(async () => {
    if (!utmUrl) return
    try {
      await navigator.clipboard.writeText(utmUrl)
      alert('URL copiada!')
    } catch (_error) {
      alert('Nao foi possivel copiar automaticamente. Copie manualmente.')
    }
  }, [utmUrl])

  const renderCalendarView = () => (
    <>
      <section className="rounded-2xl bg-gradient-to-r from-brand-500 to-brand-600 p-6 text-white shadow-soft md:p-8">
        <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight md:text-4xl">CRM Campaign Planner</h1>
            <p className="mt-2 text-sm text-blue-100 md:text-base">Calendario editorial de campanhas</p>
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={openCreateForm}
              className="rounded-xl bg-white px-4 py-2 text-sm font-semibold text-brand-700 transition hover:bg-blue-50"
            >
              + Nova Campanha
            </button>
            <button
              type="button"
              onClick={handleRefresh}
              className="rounded-xl bg-white/20 px-4 py-2 text-sm font-semibold transition hover:bg-white/30"
            >
              Atualizar
            </button>
          </div>
        </div>
      </section>

      {saturationDays.length > 0 && (
        <section className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-amber-800">
          {(() => {
            const sorted = [...saturationDays].sort(([a], [b]) => a.localeCompare(b))
            const fmt = (iso) => {
              const [, m, d] = iso.split('-')
              return `${d}/${m}`
            }
            const LIMIT = 6
            const shown = sorted.slice(0, LIMIT).map(([date, count]) => `${fmt(date)} (${count})`).join(', ')
            const extra = sorted.length > LIMIT ? ` e mais ${sorted.length - LIMIT} dia(s)` : ''
            return `Risco de saturacao: 3+ campanhas em ${shown}${extra}`
          })()}
        </section>
      )}

      <section className="flex flex-wrap items-center gap-2 rounded-xl border border-slate-200 bg-white p-3 shadow-sm">
        {[
          { key: 'all',      label: 'Todos',     soft: { bg: '#F8FAFC', text: '#475569', border: '#E2E8F0' } },
          { key: 'email',    label: 'Email',      soft: CHANNEL_SOFT.email },
          { key: 'whatsapp', label: 'WhatsApp',   soft: CHANNEL_SOFT.whatsapp },
          { key: 'sms',      label: 'SMS',        soft: CHANNEL_SOFT.sms },
        ].map((item) => {
          const isActive = selectedChannel === item.key
          return (
            <button
              key={item.key}
              type="button"
              onClick={() => setSelectedChannel(item.key)}
              style={isActive ? {
                background: item.soft.bg,
                color: item.soft.text,
                borderColor: item.soft.border,
              } : {}}
              className={`flex items-center gap-2 rounded-full border px-4 py-1.5 text-sm font-medium transition ${
                isActive
                  ? 'font-semibold'
                  : 'border-slate-200 bg-white text-slate-600 hover:border-slate-400'
              }`}
            >
              {item.key !== 'all' && (
                <span
                  className="inline-block h-2 w-2 rounded-full"
                  style={{ background: item.soft.text, opacity: 0.7 }}
                />
              )}
              {item.label}
            </button>
          )
        })}
      </section>

      {error && <section className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-rose-700">{error}</section>}

      <section className="rounded-2xl border border-slate-200 bg-white p-3 shadow-soft md:p-5">
        <div className="relative">
          {loading && (
            <div className="absolute inset-0 z-10 grid place-items-center rounded-xl bg-white/70 backdrop-blur-[1px]">
              <span className="text-sm font-medium text-slate-700">Carregando campanhas...</span>
            </div>
          )}

          <FullCalendar
            plugins={[dayGridPlugin, interactionPlugin]}
            initialView="dayGridMonth"
            locale="pt-br"
            buttonText={{
              today: 'Hoje',
              month: 'Mes',
              week: 'Semana'
            }}
            headerToolbar={{
              left: 'prev,next today',
              center: 'title',
              right: 'dayGridMonth,dayGridWeek'
            }}
            events={filteredEvents}
            datesSet={handleDatesSet}
            eventClick={handleEventClick}
            height="auto"
            dayMaxEventRows={3}
            eventContent={(info) => {
              const key = info.event.extendedProps?.channelKey || 'other'
              const status = info.event.extendedProps?.status || ''
              const soft = CHANNEL_SOFT[key] || CHANNEL_SOFT.other
              const iconColor = STATUS_ICON_COLOR[status] ?? soft.text
              return (
                <div
                  title={`${info.event.title} · ${status}`}
                  style={{
                    background: soft.bg,
                    color: soft.text,
                    border: `1px solid ${soft.border}`,
                    borderRadius: '5px',
                    padding: '1px 5px',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '4px',
                    fontSize: '11px',
                    fontWeight: 600,
                    width: '100%',
                    overflow: 'hidden',
                    cursor: 'pointer',
                  }}
                >
                  <span style={{ color: iconColor, display: 'flex', flexShrink: 0 }}>
                    <StatusIcon status={status} />
                  </span>
                  <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {soft.label}
                  </span>
                </div>
              )
            }}
          />
        </div>
      </section>

      <BriefingsPanel events={events} onEdit={openEditForm} />
    </>
  )

  const renderUtmView = () => (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft md:p-6">
      <h1 className="text-2xl font-semibold text-slate-900">Gerador de Tags UTM</h1>
      <p className="mt-2 text-sm text-slate-600">
        Padrao sugerido para CRM: <code>utm_medium=crm</code> e origem por canal.
      </p>

      <div className="mt-6 grid gap-4 md:grid-cols-2">
        <label className="flex flex-col gap-1 text-sm">
          URL base
          <input
            className="rounded-lg border border-slate-300 px-3 py-2"
            placeholder="https://www.seusite.com/pagina"
            value={utmForm.baseUrl}
            onChange={(event) => setUtmForm((prev) => ({ ...prev, baseUrl: event.target.value }))}
          />
        </label>

        <label className="flex flex-col gap-1 text-sm">
          utm_campaign
          <input
            className="rounded-lg border border-slate-300 px-3 py-2"
            placeholder="black_friday_2026"
            value={utmForm.campaign}
            onChange={(event) => setUtmForm((prev) => ({ ...prev, campaign: event.target.value }))}
          />
        </label>

        <label className="flex flex-col gap-1 text-sm">
          utm_source
          <select
            className="rounded-lg border border-slate-300 px-3 py-2"
            value={utmForm.source}
            onChange={(event) => setUtmForm((prev) => ({ ...prev, source: event.target.value }))}
          >
            <option value="email">email</option>
            <option value="whatsapp">whatsapp</option>
            <option value="sms">sms</option>
          </select>
        </label>

        <label className="flex flex-col gap-1 text-sm">
          utm_medium
          <input
            className="rounded-lg border border-slate-300 px-3 py-2"
            value={utmForm.medium}
            onChange={(event) => setUtmForm((prev) => ({ ...prev, medium: event.target.value }))}
          />
        </label>

        <label className="flex flex-col gap-1 text-sm">
          utm_content (opcional)
          <input
            className="rounded-lg border border-slate-300 px-3 py-2"
            value={utmForm.content}
            onChange={(event) => setUtmForm((prev) => ({ ...prev, content: event.target.value }))}
          />
        </label>

        <label className="flex flex-col gap-1 text-sm">
          utm_term (opcional)
          <input
            className="rounded-lg border border-slate-300 px-3 py-2"
            value={utmForm.term}
            onChange={(event) => setUtmForm((prev) => ({ ...prev, term: event.target.value }))}
          />
        </label>
      </div>

      <div className="mt-6 space-y-2">
        <p className="text-sm font-medium text-slate-700">URL final</p>
        <textarea
          readOnly
          className="h-28 w-full rounded-lg border border-slate-300 bg-slate-50 p-3 text-sm"
          value={utmUrl || 'Preencha URL base e utm_campaign para gerar a URL.'}
        />
        <button
          type="button"
          className="rounded-lg bg-brand-500 px-4 py-2 text-sm font-semibold text-white transition hover:bg-brand-600 disabled:cursor-not-allowed disabled:bg-slate-400"
          onClick={copyUtmUrl}
          disabled={!utmUrl}
        >
          Copiar URL
        </button>
      </div>
    </section>
  )

  const renderOpenDataView = () => (
    <section className="space-y-5">
      <section className="rounded-2xl bg-gradient-to-r from-slate-900 to-slate-700 p-6 text-white shadow-soft md:p-8">
        <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight md:text-4xl">Open Data Emarsys</h1>
            <p className="mt-2 text-sm text-slate-200 md:text-base">
              Consulta isolada do BigQuery para validar campanhas sem impactar o calendario do portal.
            </p>
          </div>
          <button
            type="button"
            onClick={loadOpenData}
            className="rounded-xl bg-white/15 px-4 py-2 text-sm font-semibold transition hover:bg-white/25"
          >
            Atualizar
          </button>
        </div>
      </section>

      {openDataError && (
        <section className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-rose-700">{openDataError}</section>
      )}

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
        <article className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Status</p>
          <p className="mt-2 text-xl font-semibold text-slate-900">
            {openDataHealth?.status === 'connected' ? 'Conectado' : openDataLoading ? 'Validando...' : 'Pendente'}
          </p>
        </article>
        <article className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Projeto</p>
          <p className="mt-2 text-sm font-semibold text-slate-900">{formatOpenDataValue(openDataHealth?.project_id)}</p>
        </article>
        <article className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Local</p>
          <p className="mt-2 text-sm font-semibold text-slate-900">{formatOpenDataValue(openDataHealth?.location)}</p>
        </article>
        <article className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Campanhas carregadas</p>
          <p className="mt-2 text-xl font-semibold text-slate-900">
            {new Intl.NumberFormat('pt-BR').format(openDataItems.length)}
          </p>
        </article>
        <article className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Taxas de abertura</p>
          <p className="mt-2 text-xl font-semibold text-slate-900">
            {new Intl.NumberFormat('pt-BR').format(openDataOpenRateItems.length)}
          </p>
        </article>
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft md:p-6">
        <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">Campanhas de Email</h2>
            <p className="mt-1 text-sm text-slate-600">
              Amostra das campanhas vindas do dataset Open Data da Emarsys com envios e taxa de abertura por campanha.
            </p>
          </div>
        </div>

        {openDataLoading ? (
          <p className="mt-4 text-sm text-slate-600">Carregando campanhas do Open Data...</p>
        ) : openDataItems.length === 0 ? (
          <p className="mt-4 text-sm text-slate-600">Nenhuma campanha retornada no momento.</p>
        ) : (
          <div className="mt-4 overflow-x-auto">
            <table className="min-w-full divide-y divide-slate-200 text-sm">
              <thead>
                <tr className="text-left text-slate-600">
                  <th className="px-3 py-2 font-semibold">Data</th>
                  <th className="px-3 py-2 font-semibold">Campanha</th>
                  <th className="px-3 py-2 font-semibold">Canal</th>
                  <th className="px-3 py-2 font-semibold">Status</th>
                  <th className="px-3 py-2 font-semibold">Direcionamento</th>
                  <th className="px-3 py-2 font-semibold">Produto</th>
                  <th className="px-3 py-2 font-semibold">Enviados</th>
                  <th className="px-3 py-2 font-semibold">Aberturas</th>
                  <th className="px-3 py-2 font-semibold">Taxa de abertura</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {openDataItems.map((item, index) => {
                  const metricsKey = `${item.campaign_id || ''}-${item.data || ''}`
                  const metrics = openDataOpenRatesByCampaign[metricsKey]

                  return (
                    <tr key={`${item.campaign_id || item.id || 'campaign'}-${index}`} className="align-top">
                      <td className="px-3 py-3 text-slate-700">{formatDate(item.data)}</td>
                      <td className="px-3 py-3">
                        <p className="font-medium text-slate-900">{formatOpenDataValue(item.campanha)}</p>
                        <p className="mt-1 text-xs text-slate-500">{formatOpenDataValue(item.observacao)}</p>
                      </td>
                      <td className="px-3 py-3 text-slate-700">{formatOpenDataValue(item.canal)}</td>
                      <td className="px-3 py-3 text-slate-700">{formatOpenDataValue(item.status)}</td>
                      <td className="px-3 py-3 text-slate-700">{formatOpenDataValue(item.direcionamento)}</td>
                      <td className="px-3 py-3 text-slate-700">{formatOpenDataValue(item.produto)}</td>
                      <td className="px-3 py-3 text-slate-700">
                        {new Intl.NumberFormat('pt-BR').format(Number(metrics?.enviados || 0))}
                      </td>
                      <td className="px-3 py-3 text-slate-700">
                        {new Intl.NumberFormat('pt-BR').format(Number(metrics?.aberturas_unicas || 0))}
                      </td>
                      <td className="px-3 py-3">
                        <span className="inline-flex rounded-full bg-brand-50 px-2.5 py-1 text-xs font-semibold text-brand-700">
                          {metrics?.taxa_abertura_percentual === null || metrics?.taxa_abertura_percentual === undefined
                            ? '-'
                            : `${Number(metrics.taxa_abertura_percentual).toLocaleString('pt-BR', {
                                minimumFractionDigits: 0,
                                maximumFractionDigits: 2
                              })}%`}
                        </span>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </section>
  )

  const renderAutomationResultsView = () => (
    <section className="space-y-5">
      <section className="rounded-2xl bg-gradient-to-r from-amber-500 to-orange-500 p-6 text-white shadow-soft md:p-8">
        <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight md:text-4xl">Resultados de Automacoes</h1>
            <p className="mt-2 text-sm text-amber-50 md:text-base">
              Leitura consolidada das automacoes CRM com filtros proprios e receita associada.
            </p>
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <label className="flex flex-col gap-1 text-sm text-white/90">
              Inicio
              <input
                type="date"
                value={openDataAutomationStartDate}
                onChange={(event) => setOpenDataAutomationStartDate(event.target.value)}
                className="rounded-lg border border-white/40 bg-white/95 px-3 py-2 text-sm text-slate-900"
              />
            </label>
            <label className="flex flex-col gap-1 text-sm text-white/90">
              Fim
              <input
                type="date"
                value={openDataAutomationEndDate}
                onChange={(event) => setOpenDataAutomationEndDate(event.target.value)}
                className="rounded-lg border border-white/40 bg-white/95 px-3 py-2 text-sm text-slate-900"
              />
            </label>
            <button
              type="button"
              onClick={() => { loadOpenData(); loadAnniversaryAutomationCouponStats() }}
              className="self-end rounded-xl bg-white/15 px-4 py-2 text-sm font-semibold transition hover:bg-white/25"
            >
              Atualizar
            </button>
          </div>
        </div>
      </section>

      {openDataError && (
        <section className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-rose-700">{openDataError}</section>
      )}

      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft md:p-6">
        <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">Automacao de Aniversario</h2>
            <p className="mt-1 text-sm text-slate-600">
              Taxas de abertura das pecas `Parte 1`, `Parte 2` e `Parte 3`, com receita do cupom {ANNIVERSARY_AUTOMATION_COUPON}.
            </p>
          </div>
        </div>

        {anniversaryAutomationCouponError && (
          <p className="mt-4 text-sm text-rose-700">{anniversaryAutomationCouponError}</p>
        )}

        {openDataLoading ? (
          <p className="mt-4 text-sm text-slate-600">Carregando automacao de aniversario...</p>
        ) : anniversaryAutomationStages.every((stage) => stage.items.length === 0) ? (
          <p className="mt-4 text-sm text-slate-600">Nao encontrei campanhas da automacao de aniversario no periodo selecionado.</p>
        ) : (
          <div className="mt-4 space-y-4">
            <div className="rounded-xl border border-slate-200 overflow-x-auto">
              <div className="grid grid-cols-[minmax(180px,1fr)_120px_120px_110px_150px_150px] gap-3 border-b border-slate-200 px-4 py-3 text-xs font-semibold uppercase tracking-wide text-slate-500 min-w-[830px]">
                <span>Etapa</span>
                <span>Enviados</span>
                <span>Aberturas</span>
                <span>% Abertura</span>
                <span>Receita Emarsys</span>
                <span>Receita GA4</span>
              </div>
              {anniversaryAutomationStages.map((stage) => (
                <div
                  key={stage.key}
                  className="grid grid-cols-[minmax(180px,1fr)_120px_120px_110px_150px_150px] gap-3 border-b border-slate-100 px-4 py-3 text-sm last:border-b-0 min-w-[830px]"
                >
                  <span className="font-medium text-slate-900">{stage.label}</span>
                  <span className="text-slate-700">{new Intl.NumberFormat('pt-BR').format(stage.sends)}</span>
                  <span className="text-slate-700">{new Intl.NumberFormat('pt-BR').format(stage.opens)}</span>
                  <span className="text-slate-700">
                    {Number(stage.openRate).toLocaleString('pt-BR', {
                      minimumFractionDigits: 0,
                      maximumFractionDigits: 2
                    })}
                    %
                  </span>
                  <span className="text-slate-700">{formatCurrency(stage.emarsysRevenue)}</span>
                  <span className="text-slate-700">{formatCurrency(stage.ga4Revenue)}</span>
                </div>
              ))}
            </div>

            <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
              <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-500">Consolidado</h3>
              <p className="mt-2 text-2xl font-semibold text-slate-900">
                {Number(anniversaryAutomationTotals.openRate).toLocaleString('pt-BR', {
                  minimumFractionDigits: 0,
                  maximumFractionDigits: 2
                })}%
              </p>
              <p className="mt-1 text-sm text-slate-600">
                {new Intl.NumberFormat('pt-BR').format(anniversaryAutomationTotals.opens)} aberturas unicas de{' '}
                {new Intl.NumberFormat('pt-BR').format(anniversaryAutomationTotals.sends)} enviados
              </p>
              <div className="mt-3 grid grid-cols-2 gap-3 text-sm">
                <div>
                  <p className="font-medium text-slate-500">Receita Emarsys</p>
                  <p className="text-slate-900 font-semibold">{formatCurrency(anniversaryAutomationTotals.emarsysRevenue)}</p>
                </div>
                <div>
                  <p className="font-medium text-slate-500">Receita GA4</p>
                  <p className="text-slate-900 font-semibold">{formatCurrency(anniversaryAutomationTotals.ga4Revenue)}</p>
                </div>
              </div>
              {anniversaryAutomationCouponLoading ? (
                <p className="mt-3 text-sm text-slate-600">Carregando receita do cupom...</p>
              ) : (
                <div className="mt-3 space-y-1 text-sm text-slate-600">
                  <p className="font-medium text-slate-500">Cupom {ANNIVERSARY_AUTOMATION_COUPON} (GA4)</p>
                  <p>
                    Pedidos com cupom: {new Intl.NumberFormat('pt-BR').format(Number(anniversaryAutomationCouponStats?.transactions || 0))}
                  </p>
                  <p>Receita: {formatCurrency(anniversaryAutomationCouponStats?.purchaseRevenue)}</p>
                  <p>Ticket medio: {formatCurrency(anniversaryAutomationCouponStats?.average_ticket)}</p>
                </div>
              )}
            </div>
          </div>
        )}
      </section>
    </section>
  )

  const exportOpenDataExplorerCsv = useCallback(() => {
    const columns = Array.isArray(openDataExplorerPreview?.columns) ? openDataExplorerPreview.columns : []
    const items = Array.isArray(openDataExplorerPreview?.items) ? openDataExplorerPreview.items : []
    if (columns.length === 0) return

    const headers = columns.map((column) => String(column.name || ''))
    const csvLines = [
      headers.map(toCsvValue).join(','),
      ...items.map((item) => headers.map((header) => toCsvValue(item?.[header])).join(','))
    ]
    const blob = new Blob([csvLines.join('\n')], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${openDataExplorerTable || 'open_data'}.csv`
    link.click()
    URL.revokeObjectURL(url)
  }, [openDataExplorerPreview, openDataExplorerTable])

  const renderOpenDataExplorerView = () => {
    const previewColumns = Array.isArray(openDataExplorerPreview?.columns) ? openDataExplorerPreview.columns : []
    const previewItems = Array.isArray(openDataExplorerPreview?.items) ? openDataExplorerPreview.items : []

    return (
      <section className="space-y-5">
        <section className="rounded-2xl bg-gradient-to-r from-cyan-700 to-sky-600 p-6 text-white shadow-soft md:p-8">
          <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
            <div>
              <h1 className="text-2xl font-semibold tracking-tight md:text-4xl">Explorador de Tabelas</h1>
              <p className="mt-2 text-sm text-cyan-50 md:text-base">
                Explore tabelas do Open Data, filtre periodo quando houver `partitiontime` e exporte o resultado carregado.
              </p>
            </div>
            <div className="flex flex-wrap items-end gap-3">
              <label className="flex min-w-[260px] flex-col gap-1 text-sm text-white/90">
                Tabela
                <select
                  value={openDataExplorerTable}
                  onChange={(event) => setOpenDataExplorerTable(event.target.value)}
                  className="rounded-lg border border-white/40 bg-white/95 px-3 py-2 text-sm text-slate-900"
                >
                  {openDataTables.map((item) => (
                    <option key={item.table_name} value={item.table_name}>
                      {item.table_name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex flex-col gap-1 text-sm text-white/90">
                Inicio
                <input
                  type="date"
                  value={openDataExplorerStartDate}
                  onChange={(event) => setOpenDataExplorerStartDate(event.target.value)}
                  className="rounded-lg border border-white/40 bg-white/95 px-3 py-2 text-sm text-slate-900"
                />
              </label>
              <label className="flex flex-col gap-1 text-sm text-white/90">
                Fim
                <input
                  type="date"
                  value={openDataExplorerEndDate}
                  onChange={(event) => setOpenDataExplorerEndDate(event.target.value)}
                  className="rounded-lg border border-white/40 bg-white/95 px-3 py-2 text-sm text-slate-900"
                />
              </label>
              <label className="flex flex-col gap-1 text-sm text-white/90">
                Limite
                <input
                  type="number"
                  min="1"
                  max="500"
                  value={openDataExplorerLimit}
                  onChange={(event) => setOpenDataExplorerLimit(Number(event.target.value || 100))}
                  className="w-24 rounded-lg border border-white/40 bg-white/95 px-3 py-2 text-sm text-slate-900"
                />
              </label>
              <button
                type="button"
                onClick={loadOpenDataExplorerPreview}
                className="rounded-lg bg-white px-4 py-2 text-sm font-semibold text-sky-700 transition hover:bg-slate-100"
              >
                Atualizar
              </button>
            </div>
          </div>
        </section>

        {openDataExplorerError && (
          <section className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-rose-700">{openDataExplorerError}</section>
        )}

        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft md:p-6">
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div>
              <h2 className="text-lg font-semibold text-slate-900">{openDataExplorerTable || 'Tabela'}</h2>
              <p className="mt-1 text-sm text-slate-600">
                {previewColumns.length > 0
                  ? `${previewColumns.length} colunas mapeadas e ${new Intl.NumberFormat('pt-BR').format(previewItems.length)} linhas carregadas`
                  : 'Selecione uma tabela para visualizar os dados.'}
              </p>
            </div>
            <button
              type="button"
              onClick={exportOpenDataExplorerCsv}
              disabled={previewItems.length === 0}
              className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-700 disabled:cursor-not-allowed disabled:bg-slate-300"
            >
              Exportar CSV
            </button>
          </div>

          {openDataExplorerLoading ? (
            <p className="mt-4 text-sm text-slate-600">Carregando tabela...</p>
          ) : previewItems.length === 0 ? (
            <p className="mt-4 text-sm text-slate-600">Nenhum dado retornado para os filtros atuais.</p>
          ) : (
            <div className="mt-4 overflow-x-auto">
              <table className="min-w-full divide-y divide-slate-200 text-sm">
                <thead>
                  <tr className="text-left text-slate-600">
                    {previewColumns.map((column) => (
                      <th key={column.name} className="px-3 py-2 font-semibold">
                        <div>{column.name}</div>
                        <div className="text-xs font-normal text-slate-400">{column.type}</div>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {previewItems.map((item, index) => (
                    <tr key={`${openDataExplorerTable}-${index}`} className="align-top">
                      {previewColumns.map((column) => (
                        <td key={`${index}-${column.name}`} className="max-w-[320px] px-3 py-3 text-slate-700">
                          <span className="break-words">{formatOpenDataValue(item?.[column.name])}</span>
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </section>
    )
  }

  const renderUsersView = () => (
    <section className="space-y-5">
      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft md:p-6">
        <h1 className="text-2xl font-semibold text-slate-900">Usuarios e Perfis</h1>
        {currentUserError && <p className="mt-3 text-sm text-rose-700">{currentUserError}</p>}
        {currentUser && (
          <p className="mt-3 text-sm text-slate-700">
            Logado como <span className="font-semibold">{currentUser.username}</span> ({formatRole(currentUser.role)}).
          </p>
        )}
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft md:p-6">
        <h2 className="text-lg font-semibold text-slate-900">Alterar minha senha</h2>
        <form className="mt-4 grid gap-4 md:grid-cols-3" onSubmit={handleChangeMyPassword}>
          <label className="flex flex-col gap-1 text-sm">
            Senha atual
            <input
              required
              type="password"
              className="rounded-lg border border-slate-300 px-3 py-2"
              value={passwordForm.currentPassword}
              onChange={(event) => setPasswordForm((prev) => ({ ...prev, currentPassword: event.target.value }))}
            />
          </label>

          <label className="flex flex-col gap-1 text-sm">
            Nova senha
            <input
              required
              type="password"
              className="rounded-lg border border-slate-300 px-3 py-2"
              value={passwordForm.newPassword}
              onChange={(event) => setPasswordForm((prev) => ({ ...prev, newPassword: event.target.value }))}
            />
          </label>

          <label className="flex flex-col gap-1 text-sm">
            Confirmar nova senha
            <input
              required
              type="password"
              className="rounded-lg border border-slate-300 px-3 py-2"
              value={passwordForm.confirmPassword}
              onChange={(event) => setPasswordForm((prev) => ({ ...prev, confirmPassword: event.target.value }))}
            />
          </label>

          <div className="md:col-span-3">
            <button
              type="submit"
              disabled={passwordLoading}
              className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {passwordLoading ? 'Salvando...' : 'Salvar nova senha'}
            </button>
          </div>
        </form>

        {passwordError && <p className="mt-4 text-sm text-rose-700">{passwordError}</p>}
        {passwordSuccess && <p className="mt-4 text-sm text-emerald-700">{passwordSuccess}</p>}
      </section>

      {currentUser?.role !== 'admin' ? (
        <section className="rounded-2xl border border-amber-200 bg-amber-50 p-5 text-sm text-amber-800">
          Apenas administradores podem cadastrar e descadastrar usuarios.
        </section>
      ) : (
        <>
          <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft md:p-6">
            <h2 className="text-lg font-semibold text-slate-900">Cadastrar novo usuario</h2>

            <form className="mt-4 grid gap-4 md:grid-cols-3" onSubmit={handleCreateUser}>
              <label className="flex flex-col gap-1 text-sm">
                Usuario
                <input
                  required
                  className="rounded-lg border border-slate-300 px-3 py-2"
                  placeholder="exemplo.usuario"
                  value={createForm.username}
                  onChange={(event) => setCreateForm((prev) => ({ ...prev, username: event.target.value }))}
                />
              </label>

              <label className="flex flex-col gap-1 text-sm">
                Senha
                <input
                  required
                  type="password"
                  className="rounded-lg border border-slate-300 px-3 py-2"
                  placeholder="Minimo 6 caracteres"
                  value={createForm.password}
                  onChange={(event) => setCreateForm((prev) => ({ ...prev, password: event.target.value }))}
                />
              </label>

              <label className="flex flex-col gap-1 text-sm">
                Perfil
                <select
                  className="rounded-lg border border-slate-300 px-3 py-2"
                  value={createForm.role}
                  onChange={(event) => setCreateForm((prev) => ({ ...prev, role: event.target.value }))}
                >
                  <option value="user">Usuario</option>
                  <option value="admin">Administrador</option>
                </select>
              </label>

              <div className="md:col-span-3">
                <button
                  type="submit"
                  disabled={createLoading}
                  className="rounded-lg bg-brand-500 px-4 py-2 text-sm font-semibold text-white transition hover:bg-brand-600 disabled:cursor-not-allowed disabled:bg-slate-400"
                >
                  {createLoading ? 'Cadastrando...' : 'Cadastrar usuario'}
                </button>
              </div>
            </form>

            {usersError && <p className="mt-4 text-sm text-rose-700">{usersError}</p>}
            {usersSuccess && <p className="mt-4 text-sm text-emerald-700">{usersSuccess}</p>}
          </section>

          <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft md:p-6">
            <div className="flex items-center justify-between gap-4">
              <h2 className="text-lg font-semibold text-slate-900">Usuarios cadastrados</h2>
              <button
                type="button"
                onClick={loadUsers}
                className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-100"
              >
                Atualizar lista
              </button>
            </div>

            {usersLoading ? (
              <p className="mt-4 text-sm text-slate-600">Carregando usuarios...</p>
            ) : users.length === 0 ? (
              <p className="mt-4 text-sm text-slate-600">Nenhum usuario encontrado.</p>
            ) : (
              <div className="mt-4 overflow-x-auto">
                <table className="min-w-full divide-y divide-slate-200 text-sm">
                  <thead>
                    <tr className="text-left text-slate-600">
                      <th className="px-2 py-2 font-semibold">Usuario</th>
                      <th className="px-2 py-2 font-semibold">Perfil</th>
                      <th className="px-2 py-2 font-semibold">Criado em</th>
                      <th className="px-2 py-2 font-semibold">Acoes</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {users.map((user) => {
                      const isCurrentUser = user.username === currentUser?.username
                      return (
                        <tr key={user.username}>
                          <td className="px-2 py-3">
                            {user.username}
                            {isCurrentUser ? ' (voce)' : ''}
                          </td>
                          <td className="px-2 py-3">
                            <select
                              value={roleDrafts[user.username] || user.role}
                              disabled={isCurrentUser || roleSavingUser === user.username}
                              onChange={(event) =>
                                setRoleDrafts((prev) => ({ ...prev, [user.username]: event.target.value }))
                              }
                              className="rounded-md border border-slate-300 px-2 py-1 text-xs"
                            >
                              <option value="user">Usuario</option>
                              <option value="admin">Administrador</option>
                            </select>
                          </td>
                          <td className="px-2 py-3">{formatCreatedAt(user.created_at)}</td>
                          <td className="px-2 py-3">
                            <div className="flex flex-wrap gap-2">
                              <button
                                type="button"
                                disabled={isCurrentUser || roleSavingUser === user.username}
                                onClick={() => handleUpdateRole(user.username)}
                                className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                              >
                                Salvar perfil
                              </button>
                              <button
                                type="button"
                                disabled={usersLoading || isCurrentUser}
                                onClick={() => handleDeleteUser(user.username)}
                                className="rounded-md border border-rose-300 px-3 py-1.5 text-xs font-semibold text-rose-700 hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-50"
                              >
                                Descadastrar
                              </button>
                            </div>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </section>
  )

  const renderPermissoesView = () => {
    const handleSave = async () => {
      setPermissoesSaving(true)
      setPermissoesError('')
      setPermissoesSuccess('')
      try {
        const res = await fetch('/api/config/viewer-tabs', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(permissoesDraft),
        })
        if (!res.ok) throw new Error('Falha ao salvar.')
        const saved = await res.json()
        setPermissoesDraft(saved)
        setPermissoesSuccess('Permissoes salvas com sucesso.')
      } catch (err) {
        setPermissoesError(err instanceof Error ? err.message : 'Erro ao salvar.')
      } finally {
        setPermissoesSaving(false)
      }
    }

    return (
      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft md:p-6">
        <h1 className="text-2xl font-semibold text-slate-900">Permissoes de Acesso</h1>
        <p className="mt-1 text-sm text-slate-500">
          Escolha quais abas o usuario viewer (CRMIPLACE) pode acessar.
        </p>

        {permissoesError && (
          <p className="mt-4 rounded-lg bg-rose-50 px-4 py-2 text-sm text-rose-700">{permissoesError}</p>
        )}
        {permissoesSuccess && (
          <p className="mt-4 rounded-lg bg-green-50 px-4 py-2 text-sm text-green-700">{permissoesSuccess}</p>
        )}

        {permissoesDraft === null ? (
          <p className="mt-6 text-sm text-slate-500">Carregando...</p>
        ) : (
          <div className="mt-6 space-y-3">
            {TAB_PERMISSION_OPTIONS.map((tab) => (
              <label key={tab.key} className="flex cursor-pointer items-center gap-3">
                <input
                  type="checkbox"
                  className="h-4 w-4 rounded border-slate-300 accent-brand-600"
                  checked={permissoesDraft[tab.key] !== false}
                  onChange={(e) =>
                    setPermissoesDraft((prev) => ({ ...prev, [tab.key]: e.target.checked }))
                  }
                />
                <span className="text-sm text-slate-800">{tab.label}</span>
              </label>
            ))}

            <div className="pt-4">
              <button
                type="button"
                disabled={permissoesSaving}
                onClick={handleSave}
                className="rounded-lg bg-brand-600 px-5 py-2 text-sm font-semibold text-white transition hover:bg-brand-700 disabled:opacity-50"
              >
                {permissoesSaving ? 'Salvando...' : 'Salvar permissoes'}
              </button>
            </div>
          </div>
        )}
      </section>
    )
  }

  const renderAppleLoverView = () => {
    const d = appleLoverData

    const TIERS = [
      {
        key: 'T1 - Ecosystem Enthusiast',
        short: 'T1',
        name: 'Ecosystem Enthusiast',
        desc: 'Clientes com alto envolvimento comprovado no ecossistema Apple.',
        criteria: ['≥ 2 categorias Apple compradas', '≥ 2 pedidos Apple no período', 'Usa dispositivo Apple (Mac ou iPhone)'],
        bg: 'bg-violet-50', border: 'border-violet-200', text: 'text-violet-700', badge: 'bg-violet-100 text-violet-700',
        count: () => d.summary.t1,
      },
      {
        key: 'T2 - Aspirational Buyer',
        short: 'T2',
        name: 'Aspirational Buyer',
        desc: 'Clientes com forte sinal de intenção Apple, mas ainda em transição.',
        criteria: ['≥ 2 dos critérios a seguir:', '• Comprou produto Apple', '• Ticket médio ≥ R$ 2.000', '• Visitou ≥ 2 categorias Apple'],
        bg: 'bg-blue-50', border: 'border-blue-200', text: 'text-blue-700', badge: 'bg-blue-100 text-blue-700',
        count: () => d.summary.t2,
      },
      {
        key: 'T3 - Apple Interested',
        short: 'T3',
        name: 'Apple Interested',
        desc: 'Clientes que demonstraram interesse em produtos Apple mas ainda não compraram.',
        criteria: ['Visitou categoria Apple no site', 'ou usa dispositivo Apple'],
        bg: 'bg-slate-50', border: 'border-slate-200', text: 'text-slate-600', badge: 'bg-slate-100 text-slate-600',
        count: () => d.summary.t3,
      },
    ]

    const tierMetrics = (key) => {
      const list = d.contacts.filter(c => c.apple_lover_tier === key)
      const totalSpend = list.reduce((s, c) => s + (c.total_apple_spend || 0), 0)
      const buyers = list.filter(c => c.qtd_apple_purchases > 0)
      const avgTicket = buyers.length ? buyers.reduce((s, c) => s + (c.average_order_value || 0), 0) / buyers.length : 0
      const pctDevice = list.length ? Math.round(list.filter(c => c.uses_apple_device).length / list.length * 100) : 0
      return { totalSpend, avgTicket, pctDevice }
    }

    const exportCsv = () => {
      if (!d?.contacts?.length) return
      const cols = ['contact_id','external_id','apple_lover_tier','apple_lover_score','qtd_apple_purchases','qtd_apple_categories_bought','total_apple_spend','last_apple_purchase_date','visited_apple_category','qtd_apple_categories_visited','uses_apple_device','average_order_value','average_future_spend','buyer_status']
      const esc = v => { const s = String(v ?? ''); return s.includes(',') || s.includes('"') || s.includes('\n') ? `"${s.replace(/"/g,'""')}"` : s }
      const csv = [cols.join(','), ...d.contacts.map(r => cols.map(k => esc(r[k])).join(','))].join('\n')
      const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }))
      a.download = `apple_lover_${appleLoverStart}_${appleLoverEnd}.csv`; a.click()
    }

    return (
      <section className="space-y-5">
        {/* Header */}
        <section className="rounded-2xl bg-gradient-to-r from-slate-800 to-slate-700 p-6 text-white shadow-soft md:p-8">
          <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
            <div>
              <h1 className="text-2xl font-semibold tracking-tight md:text-4xl">Apple Lover</h1>
              <p className="mt-2 text-sm text-slate-300">
                Classificação de contatos por afinidade com o ecossistema Apple
              </p>
            </div>
            <div className="flex flex-wrap items-end gap-3">
              <label className="flex flex-col gap-1 text-sm text-white/90">
                Início
                <input type="date" value={appleLoverStart} onChange={e => setAppleLoverStart(e.target.value)}
                  className="rounded-lg border border-white/40 bg-white/95 px-3 py-2 text-sm text-slate-900" />
              </label>
              <label className="flex flex-col gap-1 text-sm text-white/90">
                Fim
                <input type="date" value={appleLoverEnd} onChange={e => setAppleLoverEnd(e.target.value)}
                  className="rounded-lg border border-white/40 bg-white/95 px-3 py-2 text-sm text-slate-900" />
              </label>
              <button type="button" onClick={loadAppleLover} disabled={appleLoverLoading}
                className="rounded-lg bg-white px-5 py-2 text-sm font-semibold text-slate-800 transition hover:bg-slate-100 disabled:opacity-60">
                {appleLoverLoading ? 'Consultando...' : 'Consultar'}
              </button>
            </div>
          </div>
        </section>

        {appleLoverError && (
          <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{appleLoverError}</div>
        )}
        {!d && !appleLoverLoading && !appleLoverError && (
          <div className="rounded-xl border border-slate-200 bg-white px-6 py-10 text-center text-sm text-slate-400">
            Selecione o período e clique em "Consultar".
          </div>
        )}
        {appleLoverLoading && (
          <div className="rounded-xl border border-slate-200 bg-white px-6 py-10 text-center text-sm text-slate-400">
            Consultando BigQuery… isso pode levar alguns instantes.
          </div>
        )}

        {d && !appleLoverLoading && (
          <>
            {/* Total + exportar */}
            <div className="flex items-center justify-between rounded-xl border border-slate-200 bg-white px-5 py-4">
              <div>
                <span className="text-sm text-slate-500">Total Apple Lovers</span>
                <span className="ml-3 text-2xl font-bold text-slate-900">{d.summary.total.toLocaleString('pt-BR')}</span>
                <span className="ml-3 text-xs text-slate-400">{d.start_date} → {d.end_date}</span>
              </div>
              <button onClick={exportCsv}
                className="rounded-lg border border-slate-200 px-4 py-2 text-xs font-semibold text-slate-600 hover:bg-slate-50">
                Exportar CSV ({d.contacts.length})
              </button>
            </div>

            {/* Cards por tier */}
            <div className="grid gap-4 md:grid-cols-3">
              {TIERS.map(t => {
                const m = tierMetrics(t.key)
                return (
                  <div key={t.key} className={`rounded-2xl border ${t.border} ${t.bg} p-6`}>
                    <div className="flex items-start justify-between">
                      <span className={`rounded-full px-3 py-1 text-xs font-bold ${t.badge}`}>{t.short}</span>
                      <span className="text-3xl font-bold text-slate-900">{t.count().toLocaleString('pt-BR')}</span>
                    </div>
                    <p className={`mt-3 text-base font-semibold ${t.text}`}>{t.name}</p>
                    <p className="mt-1 text-xs text-slate-500">{t.desc}</p>

                    <ul className="mt-3 space-y-1">
                      {t.criteria.map((c, i) => (
                        <li key={i} className={`text-xs ${t.text}`}>{c}</li>
                      ))}
                    </ul>

                    <div className="mt-4 space-y-2 border-t border-current/10 pt-4">
                      <div className="flex items-center justify-between text-xs">
                        <span className="text-slate-400">Receita Apple</span>
                        <span className="font-semibold text-slate-800">{formatCurrency(m.totalSpend)}</span>
                      </div>
                      <div className="flex items-center justify-between text-xs">
                        <span className="text-slate-400">Ticket Médio</span>
                        <span className="font-semibold text-slate-800">{m.avgTicket > 0 ? formatCurrency(m.avgTicket) : '—'}</span>
                      </div>
                      <div className="flex items-center justify-between text-xs">
                        <span className="text-slate-400">Disp. Apple</span>
                        <span className="font-semibold text-slate-800">{m.pctDevice}%</span>
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          </>
        )}
      </section>
    )
  }

  const renderCampanhaDetalheView = () => (
    <section className="space-y-8">

      {/* ── Bloco SMS ── */}
      <section className="space-y-4">
        <section className="rounded-2xl bg-gradient-to-r from-orange-600 to-amber-500 p-6 text-white shadow-soft md:p-8">
          <h2 className="text-2xl font-semibold tracking-tight md:text-3xl">Apuracao SMS</h2>
          <p className="mt-1 text-sm text-orange-100">
            Busca campanhas SMS pelo nome nos últimos 180 dias. A receita considera compras nos 7 dias seguintes ao envio.
          </p>
        </section>

        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft md:p-6">
          <form onSubmit={(e) => { e.preventDefault(); loadSmsApuracao() }} className="flex gap-3">
            <input
              type="text"
              placeholder="Nome ou parte do nome da campanha SMS..."
              value={smsApuracaoNome}
              onChange={(e) => setSmsApuracaoNome(e.target.value)}
              minLength={2}
              className="flex-1 rounded-xl border border-slate-300 px-4 py-2.5 text-sm text-slate-900 outline-none transition focus:border-orange-400 focus:ring-2 focus:ring-orange-200"
            />
            <button
              type="submit"
              disabled={smsApuracaoLoading || smsApuracaoNome.trim().length < 2}
              className="rounded-xl bg-orange-500 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-orange-600 disabled:opacity-50"
            >
              {smsApuracaoLoading ? 'Buscando...' : 'Buscar'}
            </button>
          </form>
        </section>

        {smsApuracaoError && (
          <section className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
            {smsApuracaoError}
          </section>
        )}

        {smsApuracaoLoading ? (
          <section className="rounded-2xl border border-slate-200 bg-white p-8 text-center shadow-soft">
            <p className="text-sm text-slate-500">Consultando campanhas SMS...</p>
          </section>
        ) : smsApuracaoData && (
          <section className="rounded-2xl border border-slate-200 bg-white shadow-soft">
            <div className="border-b border-slate-100 px-5 py-4">
              <h3 className="text-base font-semibold text-slate-900">
                Resultados para &ldquo;{smsApuracaoData.nome}&rdquo;
              </h3>
              <p className="mt-0.5 text-xs text-slate-500">
                {smsApuracaoData.total} campanha(s)
              </p>
            </div>
            {smsApuracaoData.total === 0 ? (
              <p className="px-5 py-8 text-center text-sm text-slate-400">Nenhuma campanha SMS encontrada.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-100 bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                      <th className="px-4 py-3">Campanha</th>
                      <th className="px-4 py-3 text-right">Enviados</th>
                      <th className="px-4 py-3 text-right">Pedidos</th>
                      <th className="px-4 py-3 text-right">Receita Atribuida</th>
                      <th className="px-4 py-3"></th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {smsApuracaoData.items.map((item) => {
                      const reg = smsRegional[item.campaign_id] || {}
                      return (
                        <Fragment key={item.campaign_id}>
                          <tr className="hover:bg-slate-50">
                            <td className="px-4 py-3 text-slate-900">{item.nome_campanha}</td>
                            <td className="px-4 py-3 text-right text-slate-700">{item.enviados.toLocaleString('pt-BR')}</td>
                            <td className="px-4 py-3 text-right text-slate-700">{item.pedidos_atribuidos.toLocaleString('pt-BR')}</td>
                            <td className="px-4 py-3 text-right font-semibold text-slate-900">{formatCurrency(item.receita_atribuida)}</td>
                            <td className="px-4 py-3 text-right">
                              <button onClick={() => toggleSmsRegional(item.campaign_id, item.dispatch_date)}
                                disabled={reg.loading}
                                className="rounded-md border border-slate-200 bg-white px-2 py-1 text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-50">
                                {reg.loading ? '…' : reg.expanded ? '▲ Regional' : '▼ Regional'}
                              </button>
                            </td>
                          </tr>
                          {reg.expanded && (
                            <tr>
                              <td colSpan={5} className="p-0 border-b border-slate-200">
                                {reg.error
                                  ? <div className="px-4 py-2 text-xs text-rose-600">{reg.error}</div>
                                  : reg.data
                                    ? <RegionalPanel data={reg.data} />
                                    : <div className="px-4 py-2 text-xs text-slate-400">Carregando...</div>
                                }
                              </td>
                            </tr>
                          )}
                        </Fragment>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        )}
      </section>

      {/* ── Bloco E-mail ── */}
      <section className="space-y-4">
        <section className="rounded-2xl bg-gradient-to-r from-blue-700 to-cyan-600 p-6 text-white shadow-soft md:p-8">
          <h2 className="text-2xl font-semibold tracking-tight md:text-3xl">Apuracao E-mail</h2>
          <p className="mt-1 text-sm text-blue-100">
            Busca campanhas de e-mail pelo nome nos últimos 180 dias. A receita considera compras nos 7 dias após a abertura.
          </p>
        </section>

        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft md:p-6">
          <form onSubmit={(e) => { e.preventDefault(); loadEmailApuracao() }} className="flex gap-3">
            <input
              type="text"
              placeholder="Nome ou parte do nome da campanha de e-mail..."
              value={emailApuracaoNome}
              onChange={(e) => setEmailApuracaoNome(e.target.value)}
              minLength={2}
              className="flex-1 rounded-xl border border-slate-300 px-4 py-2.5 text-sm text-slate-900 outline-none transition focus:border-blue-400 focus:ring-2 focus:ring-blue-200"
            />
            <button
              type="submit"
              disabled={emailApuracaoLoading || emailApuracaoNome.trim().length < 2}
              className="rounded-xl bg-blue-600 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-blue-700 disabled:opacity-50"
            >
              {emailApuracaoLoading ? 'Buscando...' : 'Buscar'}
            </button>
          </form>
        </section>

        {emailApuracaoError && (
          <section className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
            {emailApuracaoError}
          </section>
        )}

        {emailApuracaoLoading ? (
          <section className="rounded-2xl border border-slate-200 bg-white p-8 text-center shadow-soft">
            <p className="text-sm text-slate-500">Consultando campanhas de e-mail...</p>
          </section>
        ) : emailApuracaoData && (() => {
          const emailItems = (emailApuracaoData.items || []).filter(i => i.enviados >= 10)
          const topApple = emailApuracaoData.top_apple || []
          const topNaoApple = emailApuracaoData.top_nao_apple || []
          const fmtC = (n) => new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(n ?? 0)
          return (
          <>
          <section className="rounded-2xl border border-slate-200 bg-white shadow-soft">
            <div className="border-b border-slate-100 px-5 py-4">
              <h3 className="text-base font-semibold text-slate-900">
                Resultados para &ldquo;{emailApuracaoData.nome}&rdquo;
              </h3>
              <p className="mt-0.5 text-xs text-slate-500">
                {emailItems.length} campanha(s) encontrada(s)
                {emailApuracaoData.total > emailItems.length && ` (${emailApuracaoData.total - emailItems.length} teste(s) oculto(s))`}
              </p>
            </div>
            {emailItems.length === 0 ? (
              <p className="px-5 py-8 text-center text-sm text-slate-400">Nenhuma campanha de e-mail encontrada.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-100 bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                      <th className="px-4 py-3">Campanha</th>
                      <th className="px-4 py-3 text-right">Enviados</th>
                      <th className="px-4 py-3 text-right">Aberturas</th>
                      <th className="px-4 py-3 text-right">Taxa Abertura</th>
                      <th className="px-4 py-3 text-right">Pedidos</th>
                      <th className="px-4 py-3 text-right">Receita Atribuida</th>
                      <th className="px-4 py-3 text-right">Itens</th>
                      <th className="px-4 py-3 text-right">Itens Apple</th>
                      <th className="px-4 py-3 text-right">Itens Não-Apple</th>
                      <th className="px-4 py-3 text-right">Receita Apple</th>
                      <th className="px-4 py-3 text-right">Receita Não-Apple</th>
                      <th className="px-4 py-3"></th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {emailItems.map((item) => {
                      const reg = emailRegional[item.campaign_id] || {}
                      return (
                        <Fragment key={item.campaign_id}>
                          <tr className="hover:bg-slate-50">
                            <td className="px-4 py-3 text-slate-900">{item.nome_campanha}</td>
                            <td className="px-4 py-3 text-right text-slate-700">{item.enviados.toLocaleString('pt-BR')}</td>
                            <td className="px-4 py-3 text-right text-slate-700">{item.aberturas.toLocaleString('pt-BR')}</td>
                            <td className="px-4 py-3 text-right text-slate-700">
                              {item.taxa_abertura !== null ? `${item.taxa_abertura.toLocaleString('pt-BR')}%` : '—'}
                            </td>
                            <td className="px-4 py-3 text-right text-slate-700">{item.pedidos_atribuidos.toLocaleString('pt-BR')}</td>
                            <td className="px-4 py-3 text-right font-semibold text-slate-900">{formatCurrency(item.receita_atribuida)}</td>
                            <td className="px-4 py-3 text-right text-slate-600">{(item.total_itens || 0).toLocaleString('pt-BR')}</td>
                            <td className="px-4 py-3 text-right text-slate-700">
                              <div>{(item.itens_apple || 0).toLocaleString('pt-BR')}</div>
                              <div className="text-xs text-slate-400">{item.total_itens > 0 ? `${Math.round((item.itens_apple / item.total_itens) * 100)}%` : '—'}</div>
                            </td>
                            <td className="px-4 py-3 text-right text-slate-700">
                              <div>{(item.itens_nao_apple || 0).toLocaleString('pt-BR')}</div>
                              <div className="text-xs text-slate-400">{item.total_itens > 0 ? `${Math.round((item.itens_nao_apple / item.total_itens) * 100)}%` : '—'}</div>
                            </td>
                            <td className="px-4 py-3 text-right font-medium text-slate-800">{formatCurrency(item.receita_apple || 0)}</td>
                            <td className="px-4 py-3 text-right font-medium text-slate-800">{formatCurrency(item.receita_nao_apple || 0)}</td>
                            <td className="px-4 py-3 text-right">
                              <button onClick={() => toggleEmailRegional(item.campaign_id, item.start_date, item.end_date)}
                                disabled={reg.loading}
                                className="rounded-md border border-slate-200 bg-white px-2 py-1 text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-50">
                                {reg.loading ? '…' : reg.expanded ? '▲ Regional' : '▼ Regional'}
                              </button>
                            </td>
                          </tr>
                          {reg.expanded && (
                            <tr>
                              <td colSpan={12} className="p-0 border-b border-slate-200">
                                {reg.error
                                  ? <div className="px-4 py-2 text-xs text-rose-600">{reg.error}</div>
                                  : reg.data
                                    ? <RegionalPanel data={reg.data} />
                                    : <div className="px-4 py-2 text-xs text-slate-400">Carregando...</div>
                                }
                              </td>
                            </tr>
                          )}
                        </Fragment>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          {/* Top produtos Apple / Não-Apple */}
          {(topApple.length > 0 || topNaoApple.length > 0) && (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              {[
                { titulo: 'Top Produtos Apple', cor: 'text-slate-700', dados: topApple },
                { titulo: 'Top Produtos Não-Apple', cor: 'text-slate-700', dados: topNaoApple },
              ].map(({ titulo, dados }) => (
                <section key={titulo} className="rounded-2xl border border-slate-200 bg-white shadow-soft">
                  <div className="border-b border-slate-100 px-5 py-3">
                    <h4 className="text-sm font-semibold text-slate-800">{titulo}</h4>
                  </div>
                  {dados.length === 0 ? (
                    <p className="px-5 py-6 text-center text-xs text-slate-400">Sem dados.</p>
                  ) : (
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b border-slate-100 bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                          <th className="px-4 py-2">Produto</th>
                          <th className="px-4 py-2 text-right">Qtd</th>
                          <th className="px-4 py-2 text-right">Receita</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100">
                        {dados.map((p, i) => (
                          <tr key={i} className="hover:bg-slate-50">
                            <td className="px-4 py-2 text-xs text-slate-800">{p.nome}</td>
                            <td className="px-4 py-2 text-right text-xs text-slate-700">{(p.qtd || 0).toLocaleString('pt-BR')}</td>
                            <td className="px-4 py-2 text-right text-xs font-medium text-slate-900">{fmtC(p.receita)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </section>
              ))}
            </div>
          )}
          </>
          )
        })()}
      </section>

    </section>
  )

  const renderAcessoriosView = () => {
    const fmtN = (n) => new Intl.NumberFormat('pt-BR').format(n ?? 0)
    const fmtPct = (n) => `${(n ?? 0).toFixed(1)}%`
    const d = acessoriosData

    const MARCA_CONFIG = {
      JBL:               { bg: 'from-orange-600 to-amber-500',   badge: 'bg-orange-100 text-orange-700' },
      Logitech:          { bg: 'from-blue-700 to-blue-500',      badge: 'bg-blue-100 text-blue-700' },
      'Originais iPlace': { bg: 'from-violet-700 to-purple-600', badge: 'bg-violet-100 text-violet-700' },
    }

    // Heat-map: 0 → cinza | 0–1% → cinza claro | >1% → amarelo→laranja (≥15% = saturado)
    const heatBg = (rate) => {
      const v = rate ?? 0
      if (v <= 0)  return { background: '#e2e8f0', color: '#94a3b8' }   // cinza slate-200
      if (v < 1)   return { background: '#f1f5f9', color: '#94a3b8' }   // cinza claro slate-100
      const pct = Math.min((v - 1) / 14, 1)                             // 1% → 0, 15% → 1
      const r = Math.round(254 - pct * (254 - 37))
      const g = Math.round(243 - pct * (243 - 99))
      const b = Math.round(199 - pct * (199 - 235))
      return { background: `rgb(${r},${g},${b})`, color: pct > 0.5 ? '#1e1b4b' : '#374151' }
    }

    // Build matrix rows grouped by linha_apple for a given grupo
    const LINHA_ORDER = ['iPhone', 'Mac', 'iPad', 'Apple Watch', 'Apple TV']
    const CAT_ORDER_PARCEIRO = [
      'Capa/Case', 'Carregador', 'Película', 'Cabo', 'Adaptador',
      'Bolsa/Mochila', 'Teclado', 'Mouse', 'Fone', 'Caneta', 'Pulseira', 'Caixa de Som', 'AirTag',
    ]
    const CAT_ORDER_APPLE = [
      'AirPods', 'AirTag', 'EarPods', 'Carregador Apple', 'Cabo Apple', 'MagSafe',
      'Magic Mouse', 'Magic Keyboard', 'Caneta', 'Pulseira', 'Capa/Case', 'Adaptador', 'Teclado',
    ]
    const buildMatrix = (rows, catOrder) => {
      const linhasSet = new Set(rows.map((r) => r.linha_apple))
      const linhas = LINHA_ORDER.filter((l) => linhasSet.has(l))
      const catsSet = new Set(rows.map((r) => r.categoria))
      const cats = [
        ...catOrder.filter((c) => catsSet.has(c)),
        ...[...catsSet].filter((c) => !catOrder.includes(c) && c !== 'Outros').sort(),
        ...( catsSet.has('Outros') ? ['Outros'] : [] ),
      ]
      const lookup = {}
      rows.forEach((r) => { lookup[`${r.linha_apple}|${r.categoria}`] = r })
      return { linhas, cats, lookup }
    }

    const MatrizTable = ({ titulo, rows, catOrder }) => {
      if (!rows?.length) return null
      const { linhas, cats, lookup } = buildMatrix(rows, catOrder)
      const totalPorLinha = {}
      ;(d?.total_por_linha || []).forEach((t) => { totalPorLinha[t.linha_apple] = t.total_pedidos })
      return (
        <section className="rounded-2xl border border-slate-200 bg-white shadow-soft overflow-hidden">
          <div className="border-b border-slate-100 px-5 py-3 flex items-center gap-3">
            <h4 className="text-sm font-semibold text-slate-800 flex-1">{titulo}</h4>
            <span className="text-xs text-slate-400">attach rate por linha de dispositivo</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="bg-slate-50 border-b border-slate-100 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                  <th className="px-4 py-2 whitespace-nowrap">Linha Apple</th>
                  <th className="px-4 py-2 text-right">Total Pedidos</th>
                  {cats.map((c) => <th key={c} className="px-3 py-2 text-center whitespace-nowrap">{c}</th>)}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {linhas.map((linha) => (
                  <tr key={linha} className="hover:bg-slate-50/50">
                    <td className="px-4 py-2 font-semibold text-slate-800 whitespace-nowrap">{linha}</td>
                    <td className="px-4 py-2 text-right text-slate-500">{fmtN(totalPorLinha[linha] ?? 0)}</td>
                    {cats.map((cat) => {
                      const cell = lookup[`${linha}|${cat}`]
                      const rate = cell ? cell.rate : 0
                      const pedidos = cell ? cell.pedidos_com_acessorio : 0
                      return (
                        <td key={cat} className="px-3 py-2 text-center" style={heatBg(rate)}>
                          <span className="font-bold">{fmtPct(rate)}</span>
                          <br />
                          <span className="opacity-70">{fmtN(pedidos)}</span>
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )
    }

    const exportOportunidade = async (linha) => {
      setAcessoriosExportLoading(true)
      try {
        const params = new URLSearchParams({ start: acessoriosStart, end: acessoriosEnd })
        if (linha) params.set('linha', linha)
        if (acessoriosCanal) params.set('canal', acessoriosCanal)
        const res = await fetch(`/api/open-data/acessorios/oportunidade-export?${params}`)
        const json = await res.json()
        if (!res.ok) throw new Error(json.detail || 'Erro ao exportar')
        const items = json.items || []
        if (!items.length) { alert('Nenhum pedido encontrado.'); return }
        const cols = ['cod_filial','numero_pedido','linha_apple','data_pedido','canal']
        const esc  = (v) => { const s = String(v ?? ''); return s.includes(',') ? `"${s}"` : s }
        const csv  = [cols.join(','), ...items.map((r) => cols.map((c) => esc(r[c])).join(','))].join('\n')
        const a    = document.createElement('a')
        a.href     = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }))
        a.download = `oportunidade_acessorios_${acessoriosStart}_${acessoriosEnd}${linha ? '_' + linha : ''}.csv`
        a.click()
      } catch (err) {
        alert(`Erro: ${err.message}`)
      } finally {
        setAcessoriosExportLoading(false)
      }
    }

    const TopProdutosTable = ({ marca }) => {
      const dados = d?.top_produtos?.[marca]?.qtd || []
      return (
        <section className="rounded-2xl border border-slate-200 bg-white shadow-soft">
          <div className="border-b border-slate-100 px-4 py-3">
            <h4 className="text-sm font-semibold text-slate-800">Top 10 — {marca}</h4>
          </div>
          {!dados.length ? (
            <p className="px-4 py-5 text-center text-xs text-slate-400">Sem dados no período.</p>
          ) : (
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-slate-100 bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                  <th className="px-4 py-2">Produto</th>
                  <th className="px-4 py-2 text-right">Pedidos</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {dados.map((p, i) => (
                  <tr key={i} className="hover:bg-slate-50">
                    <td className="px-4 py-2 text-slate-800">{p.nome}</td>
                    <td className="px-4 py-2 text-right text-slate-700">{fmtN(p.qtd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      )
    }

    return (
      <section className="space-y-5">
        {/* Header */}
        <section className="rounded-2xl bg-gradient-to-r from-slate-700 to-slate-600 p-6 text-white shadow-soft md:p-8">
          <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
            <div>
              <h1 className="text-2xl font-semibold tracking-tight md:text-4xl">Acessórios</h1>
              <p className="mt-2 text-sm text-slate-300">
                Attach rate de acessórios por linha de dispositivo Apple — pedidos faturados
              </p>
            </div>
            <div className="flex flex-wrap items-end gap-3">
              {/* Canal filter */}
              <div className="flex flex-col gap-1">
                <span className="text-xs text-white/70">Canal</span>
                <div className="flex rounded-lg overflow-hidden border border-white/30">
                  {[
                    { value: '',          label: 'Todos' },
                    { value: 'VAREJO',    label: 'Varejo' },
                    { value: 'ECOMMERCE', label: 'E-comm' },
                  ].map((opt) => (
                    <button
                      key={opt.value}
                      type="button"
                      onClick={() => {
                        setAcessoriosCanal(opt.value)
                        loadAcessorios(opt.value)
                      }}
                      className={`px-3 py-2 text-xs font-semibold transition ${
                        acessoriosCanal === opt.value
                          ? 'bg-white text-slate-800'
                          : 'bg-white/10 text-white hover:bg-white/20'
                      }`}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              </div>
              <label className="flex flex-col gap-1 text-sm text-white/90">
                Início
                <input type="date" value={acessoriosStart} onChange={(e) => setAcessoriosStart(e.target.value)}
                  className="rounded-lg border border-white/40 bg-white/95 px-3 py-2 text-sm text-slate-900" />
              </label>
              <label className="flex flex-col gap-1 text-sm text-white/90">
                Fim
                <input type="date" value={acessoriosEnd} onChange={(e) => setAcessoriosEnd(e.target.value)}
                  className="rounded-lg border border-white/40 bg-white/95 px-3 py-2 text-sm text-slate-900" />
              </label>
              <button type="button" onClick={() => loadAcessorios()} disabled={acessoriosLoading}
                className="rounded-lg bg-white px-5 py-2 text-sm font-semibold text-slate-800 transition hover:bg-slate-100 disabled:opacity-60">
                {acessoriosLoading ? 'Consultando...' : 'Consultar'}
              </button>
            </div>
          </div>
        </section>

        {/* Error */}
        {acessoriosError && (
          <section className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
            {acessoriosError}
          </section>
        )}

        {/* Loading */}
        {acessoriosLoading && (
          <section className="rounded-2xl border border-slate-200 bg-white p-8 text-center shadow-soft">
            <p className="text-sm text-slate-500">Consultando BigQuery... pode levar até 30s.</p>
          </section>
        )}

        {/* Results */}
        {!acessoriosLoading && d && (
          <>

            {/* Matriz — Acessórios Apple */}
            {d.matrix_apple?.length > 0 && (
              <MatrizTable
                titulo="Acessórios — Marca: Apple"
                rows={d.matrix_apple}
                catOrder={CAT_ORDER_APPLE}
              />
            )}

            {/* Matriz — Parceiros */}
            {d.matrix_parceiro?.length > 0 && (
              <MatrizTable
                titulo="Acessórios — Marcas: Originais iPlace, JBL, Logitech, Mister"
                rows={d.matrix_parceiro}
                catOrder={CAT_ORDER_PARCEIRO}
              />
            )}

            {/* Pool de Oportunidade */}
            {d.oportunidade?.length > 0 && (
              <section className="rounded-2xl border border-amber-200 bg-amber-50 p-5 shadow-soft">
                <div className="mb-4 flex items-start justify-between">
                  <div>
                    <h3 className="text-base font-semibold text-amber-900">Pool de Oportunidade</h3>
                    <p className="mt-0.5 text-xs text-amber-700">
                      Pedidos faturados com dispositivo Apple que não tiveram nenhum acessório no mesmo pedido
                    </p>
                  </div>
                  <button
                    type="button"
                    disabled={acessoriosExportLoading}
                    onClick={() => exportOportunidade('')}
                    className="ml-4 rounded-lg bg-amber-700 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-amber-800 disabled:opacity-60"
                  >
                    {acessoriosExportLoading ? 'Exportando...' : 'Exportar todos (CSV)'}
                  </button>
                </div>
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  {d.oportunidade.map((op) => (
                    <div key={op.linha_apple} className="rounded-xl bg-white/70 p-4 border border-amber-200">
                      <p className="text-xs font-semibold text-amber-800">{op.linha_apple}</p>
                      <p className="mt-1 text-2xl font-bold text-amber-900">{fmtN(op.sem_acessorio)}</p>
                      <p className="text-xs text-amber-600">
                        {fmtPct(op.pct_sem_acessorio)} do total ({fmtN(op.total_pedidos)})
                      </p>
                      <button
                        type="button"
                        disabled={acessoriosExportLoading}
                        onClick={() => exportOportunidade(op.linha_apple)}
                        className="mt-2 text-xs font-medium text-amber-700 underline hover:text-amber-900 disabled:opacity-60"
                      >
                        Exportar {op.linha_apple}
                      </button>
                    </div>
                  ))}
                </div>
              </section>
            )}

            {/* Cards de marca + top produtos */}
            <h3 className="pt-2 text-sm font-semibold text-slate-700">Marcas Parceiras</h3>

            {d.por_marca?.length > 0 ? (
              <div className="grid grid-cols-1 gap-5 md:grid-cols-3">
                {d.por_marca.map((m) => {
                  const cfg = MARCA_CONFIG[m.marca] || { bg: 'from-slate-600 to-slate-500', badge: 'bg-slate-100 text-slate-700' }
                  return (
                    <div key={m.marca} className="flex flex-col gap-3">
                      <section className={`rounded-2xl bg-gradient-to-r ${cfg.bg} p-5 text-white shadow-soft`}>
                        <h3 className="mb-4 text-xl font-bold">{m.marca}</h3>
                        <div className="grid grid-cols-2 gap-3">
                          {[
                            { label: 'Pedidos', value: fmtN(m.pedidos) },
                            { label: 'Itens',   value: fmtN(m.itens) },
                          ].map((c) => (
                            <div key={c.label}>
                              <p className="text-xs text-white/70">{c.label}</p>
                              <p className="text-base font-semibold">{c.value}</p>
                            </div>
                          ))}
                        </div>
                      </section>
                      <TopProdutosTable marca={m.marca} />
                    </div>
                  )
                })}
              </div>
            ) : (
              <section className="rounded-2xl border border-slate-200 bg-white p-8 text-center shadow-soft">
                <p className="text-sm text-slate-400">Nenhum dado de marca parceira encontrado no período.</p>
              </section>
            )}
          </>
        )}
      </section>
    )
  }

  const renderCupomView = () => {
    const fmt = (n) => new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(n ?? 0)
    const fmtN = (n) => new Intl.NumberFormat('pt-BR').format(n ?? 0)

    const exportCsv = () => {
      if (!cupomData?.by_coupon?.length) return
      const cols = ['cupom', 'pedidos', 'receita', 'ticket_medio']
      const esc = (v) => { const s = String(v ?? ''); return s.includes(',') ? `"${s}"` : s }
      const rows = cupomData.by_coupon.map((r) =>
        [r.coupon, r.transactions, r.purchaseRevenue, r.transactions > 0 ? (r.purchaseRevenue / r.transactions).toFixed(2) : '0'].map(esc).join(',')
      )
      const csv = [cols.join(','), ...rows].join('\n')
      const a = document.createElement('a')
      a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }))
      a.download = `cupom_${cupomStart}_${cupomEnd}.csv`
      a.click()
    }

    return (
      <section className="space-y-5">
        {/* Header */}
        <section className="rounded-2xl bg-gradient-to-r from-emerald-700 to-teal-600 p-6 text-white shadow-soft md:p-8">
          <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
            <div>
              <h1 className="text-2xl font-semibold tracking-tight md:text-4xl">Consulta por Cupom</h1>
              <p className="mt-2 text-sm text-emerald-100">
                Pedidos e receita por cupom no período selecionado (dados GA4)
              </p>
            </div>
            <div className="flex flex-wrap items-end gap-3">
              <label className="flex flex-col gap-1 text-sm text-white/90">
                Início
                <input type="date" value={cupomStart} onChange={(e) => setCupomStart(e.target.value)}
                  className="rounded-lg border border-white/40 bg-white/95 px-3 py-2 text-sm text-slate-900" />
              </label>
              <label className="flex flex-col gap-1 text-sm text-white/90">
                Fim
                <input type="date" value={cupomEnd} onChange={(e) => setCupomEnd(e.target.value)}
                  className="rounded-lg border border-white/40 bg-white/95 px-3 py-2 text-sm text-slate-900" />
              </label>
            </div>
          </div>
        </section>

        {/* Search */}
        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft">
          <form onSubmit={(e) => { e.preventDefault(); loadCupom() }} className="flex gap-3">
            <input
              type="text"
              placeholder="Código do cupom (ex: BLACKFRIDAY, VOLTA10)..."
              value={cupomQuery}
              onChange={(e) => setCupomQuery(e.target.value)}
              className="flex-1 rounded-xl border border-slate-300 px-4 py-2.5 text-sm text-slate-900 outline-none transition focus:border-emerald-400 focus:ring-2 focus:ring-emerald-200"
            />
            <button
              type="submit"
              disabled={cupomLoading || !cupomQuery.trim()}
              className="rounded-xl bg-emerald-600 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-emerald-700 disabled:opacity-50"
            >
              {cupomLoading ? 'Buscando...' : 'Buscar'}
            </button>
          </form>
          <p className="mt-2 text-xs text-slate-400">Para buscar mais de um cupom, separe por vírgula ou espaço.</p>
        </section>

        {/* Error */}
        {cupomError && (
          <section className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
            {cupomError}
          </section>
        )}

        {/* Loading */}
        {cupomLoading && (
          <section className="rounded-2xl border border-slate-200 bg-white p-8 text-center shadow-soft">
            <p className="text-sm text-slate-500">Consultando GA4...</p>
          </section>
        )}

        {/* Results */}
        {!cupomLoading && cupomData && (
          <>
            {/* Summary cards */}
            <section className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              {[
                { label: 'Total de Pedidos', value: fmtN(cupomData.transactions) },
                { label: 'Receita Total', value: fmt(cupomData.purchaseRevenue) },
                { label: 'Ticket Médio', value: fmt(cupomData.average_ticket) },
              ].map((card) => (
                <div key={card.label} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft">
                  <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{card.label}</p>
                  <p className="mt-1 text-2xl font-bold text-slate-900">{card.value}</p>
                </div>
              ))}
            </section>

            {/* Breakdown table */}
            {cupomData.transactions === 0 ? (
              <section className="rounded-2xl border border-slate-200 bg-white p-8 text-center shadow-soft">
                <p className="text-sm text-slate-400">Nenhum pedido encontrado para o cupom no período.</p>
              </section>
            ) : (
              <section className="rounded-2xl border border-slate-200 bg-white shadow-soft">
                <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
                  <div>
                    <h3 className="text-base font-semibold text-slate-900">Breakdown por Cupom</h3>
                    <p className="mt-0.5 text-xs text-slate-500">
                      {cupomData.start_date} a {cupomData.end_date}
                    </p>
                  </div>
                  <button
                    onClick={exportCsv}
                    className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 transition hover:bg-slate-50"
                  >
                    Exportar CSV
                  </button>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-slate-100 bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                        <th className="px-5 py-3">Cupom</th>
                        <th className="px-5 py-3 text-right">Pedidos</th>
                        <th className="px-5 py-3 text-right">Receita</th>
                        <th className="px-5 py-3 text-right">Ticket Médio</th>
                        <th className="px-5 py-3 text-right">% Pedidos</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {cupomData.by_coupon.map((row) => (
                        <tr key={row.coupon} className="hover:bg-slate-50">
                          <td className="px-5 py-3 font-mono text-xs font-semibold text-slate-800">{row.coupon || '(sem cupom)'}</td>
                          <td className="px-5 py-3 text-right text-slate-700">{fmtN(row.transactions)}</td>
                          <td className="px-5 py-3 text-right font-semibold text-slate-900">{fmt(row.purchaseRevenue)}</td>
                          <td className="px-5 py-3 text-right text-slate-700">
                            {fmt(row.transactions > 0 ? row.purchaseRevenue / row.transactions : 0)}
                          </td>
                          <td className="px-5 py-3 text-right text-slate-500">
                            {cupomData.transactions > 0
                              ? `${((row.transactions / cupomData.transactions) * 100).toFixed(1)}%`
                              : '—'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            )}
          </>
        )}
      </section>
    )
  }

  const renderSmsClientesView = () => {
    const exportCsv = () => {
      if (!smsClientesData) return
      const params = new URLSearchParams({ start: smsClientesStart, end: smsClientesEnd })
      if (smsClientesStatus) params.set('status', smsClientesStatus)
      window.location.href = `/api/open-data/sms-clientes/export?${params}`
    }

    return (
      <section className="space-y-5">
        {/* Header */}
        <section className="rounded-2xl bg-gradient-to-r from-violet-700 to-purple-600 p-6 text-white shadow-soft md:p-8">
          <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
            <div>
              <h1 className="text-2xl font-semibold tracking-tight md:text-4xl">Base SMS</h1>
              <p className="mt-2 text-sm text-violet-100">
                Clientes que receberam SMS no período selecionado
              </p>
            </div>
            <div className="flex flex-wrap items-end gap-3">
              <label className="flex flex-col gap-1 text-sm text-white/90">
                Início
                <input type="date" value={smsClientesStart} onChange={(e) => setSmsClientesStart(e.target.value)}
                  className="rounded-lg border border-white/40 bg-white/95 px-3 py-2 text-sm text-slate-900" />
              </label>
              <label className="flex flex-col gap-1 text-sm text-white/90">
                Fim
                <input type="date" value={smsClientesEnd} onChange={(e) => setSmsClientesEnd(e.target.value)}
                  className="rounded-lg border border-white/40 bg-white/95 px-3 py-2 text-sm text-slate-900" />
              </label>
            </div>
          </div>
        </section>

        {/* Filters */}
        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft">
          <div className="flex flex-wrap items-end gap-3">
            <div className="flex flex-col gap-1">
              <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">Status do Envio</label>
              <select
                value={smsClientesStatus}
                onChange={(e) => setSmsClientesStatus(e.target.value)}
                className="rounded-xl border border-slate-300 px-3 py-2.5 text-sm text-slate-900 outline-none focus:border-violet-400 focus:ring-2 focus:ring-violet-200"
              >
                <option value="">Todos os status</option>
                {smsStatusOptions.map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
            </div>
            <button
              type="button"
              onClick={loadSmsClientes}
              disabled={smsClientesLoading || !smsClientesStart || !smsClientesEnd}
              className="rounded-xl bg-violet-600 px-6 py-2.5 text-sm font-semibold text-white transition hover:bg-violet-700 disabled:opacity-50"
            >
              {smsClientesLoading ? 'Consultando...' : 'Consultar'}
            </button>
          </div>
        </section>

        {/* Error */}
        {smsClientesError && (
          <section className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
            {smsClientesError}
          </section>
        )}

        {/* Loading */}
        {smsClientesLoading && (
          <section className="rounded-2xl border border-slate-200 bg-white p-8 text-center shadow-soft">
            <p className="text-sm text-slate-500">Consultando BigQuery...</p>
          </section>
        )}

        {/* Results */}
        {!smsClientesLoading && smsClientesData && (
          <>
            <section className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft">
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Total de Envios</p>
                <p className="mt-1 text-2xl font-bold text-slate-900">{smsClientesData.total.toLocaleString('pt-BR')}</p>
              </div>
              <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft">
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Campanhas</p>
                <p className="mt-1 text-2xl font-bold text-slate-900">{smsClientesData.items.length.toLocaleString('pt-BR')}</p>
              </div>
              <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft">
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Período</p>
                <p className="mt-1 text-lg font-semibold text-slate-900">{smsClientesData.start_date} → {smsClientesData.end_date}</p>
              </div>
            </section>

            {smsClientesData.items.length === 0 ? (
              <section className="rounded-2xl border border-slate-200 bg-white p-8 text-center shadow-soft">
                <p className="text-sm text-slate-400">Nenhum envio encontrado no período com os filtros selecionados.</p>
              </section>
            ) : (
              <section className="rounded-2xl border border-slate-200 bg-white shadow-soft">
                <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
                  <div>
                    <h3 className="text-base font-semibold text-slate-900">Campanhas SMS</h3>
                    <p className="mt-0.5 text-xs text-slate-500">{smsClientesData.items.length} campanhas · {smsClientesData.total.toLocaleString('pt-BR')} envios no total</p>
                  </div>
                  <button
                    onClick={exportCsv}
                    className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 transition hover:bg-slate-50"
                  >
                    Exportar CSV (base completa)
                  </button>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-slate-100 bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                        <th className="px-5 py-3">Campanha</th>
                        <th className="px-5 py-3 text-right">Envios</th>
                        <th className="px-5 py-3 text-right">% do Total</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {smsClientesData.items.map((row) => (
                        <tr key={row.campaign_id} className="hover:bg-slate-50">
                          <td className="px-5 py-3 text-slate-800">{row.nome_campanha}</td>
                          <td className="px-5 py-3 text-right font-semibold text-slate-900">{row.total_envios.toLocaleString('pt-BR')}</td>
                          <td className="px-5 py-3 text-right text-slate-500">
                            {smsClientesData.total > 0 ? `${((row.total_envios / smsClientesData.total) * 100).toFixed(1)}%` : '—'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            )}
          </>
        )}
      </section>
    )
  }

  const renderComparativoCRMView = () => (
    <section className="space-y-5">
      <section className="rounded-2xl bg-gradient-to-r from-indigo-700 to-blue-600 p-6 text-white shadow-soft md:p-8">
        <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight md:text-4xl">Comparativo CRM</h1>
            <p className="mt-2 text-sm text-indigo-100 md:text-base">
              Atribuicao vs Influencia — mesma base de pedidos, duas metodologias de calculo de receita CRM.
            </p>
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <div className="flex flex-col gap-1">
              <span className="text-xs text-white/70">Canal</span>
              <div className="flex rounded-lg overflow-hidden border border-white/30">
                {[
                  { value: '',          label: 'Todos' },
                  { value: 'VAREJO',    label: 'Loja' },
                  { value: 'ECOMMERCE', label: 'E-comm' },
                ].map((opt) => (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => { setComparativoCRMCanal(opt.value); loadComparativoCRM(opt.value) }}
                    className={`px-3 py-2 text-xs font-semibold transition ${
                      comparativoCRMCanal === opt.value
                        ? 'bg-white text-indigo-700'
                        : 'bg-white/15 text-white hover:bg-white/25'
                    }`}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>
            <label className="flex flex-col gap-1 text-sm text-white/90">
              Inicio
              <input
                type="date"
                value={comparativoCRMStart}
                onChange={(e) => setComparativoCRMStart(e.target.value)}
                className="rounded-lg border border-white/40 bg-white/95 px-3 py-2 text-sm text-slate-900"
              />
            </label>
            <label className="flex flex-col gap-1 text-sm text-white/90">
              Fim
              <input
                type="date"
                value={comparativoCRMEnd}
                onChange={(e) => setComparativoCRMEnd(e.target.value)}
                className="rounded-lg border border-white/40 bg-white/95 px-3 py-2 text-sm text-slate-900"
              />
            </label>
            <button
              type="button"
              onClick={loadComparativoCRM}
              className="self-end rounded-xl bg-white/15 px-4 py-2 text-sm font-semibold transition hover:bg-white/25"
            >
              Atualizar
            </button>
          </div>
        </div>
      </section>

      {comparativoCRMError && (
        <section className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          {comparativoCRMError}
        </section>
      )}

      {comparativoCRMLoading ? (
        <section className="rounded-2xl border border-slate-200 bg-white p-8 text-center shadow-soft">
          <p className="text-sm text-slate-500">Calculando comparativo... Isso pode levar alguns segundos.</p>
        </section>
      ) : comparativoCRMData && (
        <section className="grid gap-5 md:grid-cols-3">
          <div className="rounded-2xl border border-indigo-200 bg-indigo-50 p-6 shadow-soft">
            <div className="mb-4">
              <span className="rounded-full bg-indigo-100 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-indigo-700">
                Modelo 1 — Atribuicao (Emarsys)
              </span>
            </div>
            <p className="text-xs text-indigo-500">Emarsys atribui uma fracao do valor do pedido ao canal CRM</p>
            <div className="mt-5 space-y-4">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-indigo-600">Receita CRM (Atribuida)</p>
                <p className="mt-1 text-3xl font-bold text-indigo-900">{formatCurrency(comparativoCRMData.receita_atribuicao)}</p>
              </div>
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-indigo-600">Valor Total dos Pedidos</p>
                <p className="mt-1 text-xl font-semibold text-indigo-800">{formatCurrency(comparativoCRMData.valor_pedidos)}</p>
              </div>
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-indigo-600">Pedidos Atribuidos</p>
                <p className="mt-1 text-xl font-semibold text-indigo-800">{Number(comparativoCRMData.pedidos).toLocaleString('pt-BR')}</p>
              </div>
            </div>
          </div>

          <div className="rounded-2xl border border-emerald-200 bg-emerald-50 p-6 shadow-soft">
            <div className="mb-4">
              <span className="rounded-full bg-emerald-100 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-emerald-700">
                Modelo 2 — Influencia (Binario)
              </span>
            </div>
            <p className="text-xs text-emerald-500">100% do valor do pedido e creditado ao CRM se houver qualquer atribuicao</p>
            <div className="mt-5 space-y-4">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-emerald-600">Receita CRM (Influencia)</p>
                <p className="mt-1 text-3xl font-bold text-emerald-900">{formatCurrency(comparativoCRMData.valor_pedidos)}</p>
              </div>
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-emerald-600">Pedidos Influenciados</p>
                <p className="mt-1 text-xl font-semibold text-emerald-800">{Number(comparativoCRMData.pedidos).toLocaleString('pt-BR')}</p>
              </div>
            </div>
          </div>

          <div className="rounded-2xl border border-rose-200 bg-rose-50 p-6 shadow-soft">
            <div className="mb-4">
              <span className="rounded-full bg-rose-100 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-rose-700">
                Somente Transacional
              </span>
            </div>
            <p className="text-xs text-rose-400">Pedidos atribuidos exclusivamente a campanhas transacionais (sem nenhuma campanha de marketing)</p>
            <div className="mt-5 space-y-4">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-rose-600">Receita Transacional</p>
                <p className="mt-1 text-3xl font-bold text-rose-900">{formatCurrency(comparativoCRMData.receita_transacional)}</p>
              </div>
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-rose-600">Pedidos Transacionais</p>
                <p className="mt-1 text-xl font-semibold text-rose-800">{Number(comparativoCRMData.pedidos_transacional).toLocaleString('pt-BR')}</p>
              </div>
            </div>
          </div>
        </section>
      )}
    </section>
  )

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-7xl flex-col gap-5 px-4 py-6 md:px-6 lg:px-8">
      <div className="grid gap-4 md:grid-cols-[260px_1fr]">
        <aside className="h-fit rounded-2xl border border-slate-200 bg-white p-3 shadow-soft">
          <p className="px-2 pb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Ferramentas CRM</p>
          <nav className="space-y-1">
            {menuItems.map((item) => (
              <button
                key={item.key}
                type="button"
                disabled={item.disabled}
                onClick={() => setActiveView(item.key)}
                className={`w-full rounded-lg px-3 py-2 text-left text-sm transition ${
                  activeView === item.key
                    ? 'bg-brand-50 font-semibold text-brand-700'
                    : 'text-slate-700 hover:bg-slate-100'
                } ${item.disabled ? 'cursor-not-allowed opacity-50' : ''}`}
              >
                {item.label}
              </button>
            ))}
          </nav>
        </aside>

        <div className="space-y-5">
          {activeView === 'calendar' && renderCalendarView()}
          {activeView === 'open-data' && renderOpenDataView()}
          {activeView === 'automation-results' && renderAutomationResultsView()}
          {activeView === 'open-data-explorer' && renderOpenDataExplorerView()}
          {activeView === 'utm' && renderUtmView()}
          {activeView === 'users' && userManagementEnabled && renderUsersView()}
          {activeView === 'permissoes' && renderPermissoesView()}
          {activeView === 'comparativo-crm' && renderComparativoCRMView()}
          {activeView === 'campanha-detalhe' && renderCampanhaDetalheView()}
          {activeView === 'perfil-cliente' && <PerfilClientePage />}
          {activeView === 'apple-lover' && renderAppleLoverView()}
          {activeView === 'acessorios' && renderAcessoriosView()}
          {activeView === 'cupom' && renderCupomView()}
          {activeView === 'sms-clientes' && renderSmsClientesView()}
        </div>
      </div>

      {selectedEvent && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 p-4"
          role="dialog"
          aria-modal="true"
          onClick={closeModal}
        >
          <div
            className="w-full max-w-md rounded-2xl bg-white p-5 shadow-2xl"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="mb-4 flex items-start justify-between gap-4">
              <h2 className="text-lg font-semibold text-slate-900">{selectedEvent.title}</h2>
              <button
                type="button"
                className="rounded-md px-2 py-1 text-slate-500 hover:bg-slate-100 hover:text-slate-900"
                onClick={closeModal}
              >
                X
              </button>
            </div>

            <div className="space-y-3 text-sm text-slate-700">
              <p>
                <span className="font-semibold text-slate-900">Data:</span>{' '}
                {selectedEvent.extendedProps?.data_original || formatDate(selectedEvent.startStr)}
              </p>
              <p>
                <span className="font-semibold text-slate-900">Canal:</span>{' '}
                {selectedEvent.extendedProps?.canal || 'Nao informado'}
              </p>
              <p>
                <span className="font-semibold text-slate-900">Produto:</span>{' '}
                {selectedEvent.extendedProps?.produto || 'Nao informado'}
              </p>
              <p>
                <span className="font-semibold text-slate-900">Observacao:</span>{' '}
                {selectedEvent.extendedProps?.observacao || 'Sem observacao'}
              </p>
            </div>

            {selectedEvent.extendedProps?._row && (
              <div className="mt-5 flex gap-2 border-t border-slate-100 pt-4">
                <button
                  type="button"
                  onClick={() => openEditForm(selectedEvent)}
                  className="flex-1 rounded-lg bg-slate-900 py-2 text-sm font-semibold text-white transition hover:bg-slate-700"
                >
                  Editar
                </button>
                <button
                  type="button"
                  onClick={() => handleDeleteEvent(selectedEvent.extendedProps._row)}
                  className="rounded-lg border border-rose-200 px-4 py-2 text-sm font-semibold text-rose-600 transition hover:bg-rose-50"
                >
                  Excluir
                </button>
              </div>
            )}
          </div>
        </div>
      )}

      {eventFormOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 p-4"
          role="dialog"
          aria-modal="true"
        >
          <div
            className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-5 flex items-center justify-between">
              <h2 className="text-lg font-semibold text-slate-900">
                {eventFormMode === 'create' ? 'Nova Campanha' : 'Editar Campanha'}
              </h2>
              <button type="button" onClick={() => setEventFormOpen(false)} className="rounded-md px-2 py-1 text-slate-500 hover:bg-slate-100">X</button>
            </div>

            {eventFormError && (
              <div className="mb-4 rounded-lg bg-rose-50 px-4 py-3 text-sm text-rose-700">{eventFormError}</div>
            )}

            <form
              onSubmit={(e) => { e.preventDefault(); handleSaveEvent(eventFormData) }}
              className="space-y-4"
            >
              <div className="grid gap-4 sm:grid-cols-2">
                <label className="flex flex-col gap-1 text-sm">
                  <span className="font-medium text-slate-700">Data *</span>
                  <input
                    type="date" required
                    value={eventFormData.data}
                    onChange={(e) => setEventFormData(d => ({ ...d, data: e.target.value }))}
                    className="rounded-lg border border-slate-300 px-3 py-2 text-slate-900 outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-200"
                  />
                </label>
                <label className="flex flex-col gap-1 text-sm">
                  <span className="font-medium text-slate-700">Canal</span>
                  <select
                    value={eventFormData.canal}
                    onChange={(e) => setEventFormData(d => ({ ...d, canal: e.target.value }))}
                    className="rounded-lg border border-slate-300 px-3 py-2 text-slate-900 outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-200"
                  >
                    <option value="">Selecione</option>
                    <option value="Email">Email</option>
                    <option value="SMS">SMS</option>
                    <option value="WhatsApp">WhatsApp</option>
                  </select>
                </label>
              </div>

              <label className="flex flex-col gap-1 text-sm">
                <span className="font-medium text-slate-700">Campanha</span>
                <input
                  type="text"
                  value={eventFormData.campanha}
                  onChange={(e) => setEventFormData(d => ({ ...d, campanha: e.target.value }))}
                  className="rounded-lg border border-slate-300 px-3 py-2 text-slate-900 outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-200"
                />
              </label>

              <div className="grid gap-4 sm:grid-cols-2">
                <label className="flex flex-col gap-1 text-sm">
                  <span className="font-medium text-slate-700">Direcionamento</span>
                  <select
                    value={eventFormData.direcionamento}
                    onChange={(e) => setEventFormData(d => ({ ...d, direcionamento: e.target.value }))}
                    className="rounded-lg border border-slate-300 px-3 py-2 text-slate-900 outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-200"
                  >
                    <option value="">Selecione</option>
                    <option>E-comm</option>
                    <option>Loja</option>
                    <option>Televendas</option>
                    <option>E-comm+Loja</option>
                    <option>E-comm+Televendas</option>
                  </select>
                </label>
                <label className="flex flex-col gap-1 text-sm">
                  <span className="font-medium text-slate-700">Status</span>
                  <select
                    value={eventFormData.status}
                    onChange={(e) => setEventFormData(d => ({ ...d, status: e.target.value }))}
                    className="rounded-lg border border-slate-300 px-3 py-2 text-slate-900 outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-200"
                  >
                    <option value="">Selecione</option>
                    <option>Planejada</option>
                    <option>Briefing Enviado</option>
                    <option>Programada</option>
                    <option>Finalizada</option>
                    <option>Cancelada</option>
                  </select>
                </label>
              </div>

              <label className="flex flex-col gap-1 text-sm">
                <span className="font-medium text-slate-700">Produto</span>
                <input
                  type="text"
                  value={eventFormData.produto}
                  onChange={(e) => setEventFormData(d => ({ ...d, produto: e.target.value }))}
                  className="rounded-lg border border-slate-300 px-3 py-2 text-slate-900 outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-200"
                />
              </label>

              <label className="flex flex-col gap-1 text-sm">
                <span className="font-medium text-slate-700">Observacao</span>
                <textarea
                  rows={2}
                  value={eventFormData.observacao}
                  onChange={(e) => setEventFormData(d => ({ ...d, observacao: e.target.value }))}
                  className="rounded-lg border border-slate-300 px-3 py-2 text-slate-900 outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-200"
                />
              </label>

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setEventFormOpen(false)}
                  className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-50"
                >
                  Cancelar
                </button>
                <button
                  type="submit"
                  disabled={eventFormLoading || !eventFormData.data}
                  className="rounded-lg bg-brand-600 px-5 py-2 text-sm font-semibold text-white transition hover:bg-brand-700 disabled:opacity-50"
                >
                  {eventFormLoading ? 'Salvando...' : 'Salvar'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </main>
  )
}
