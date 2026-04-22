import { useCallback, useEffect, useMemo, useState } from 'react'
import FullCalendar from '@fullcalendar/react'
import dayGridPlugin from '@fullcalendar/daygrid'
import interactionPlugin from '@fullcalendar/interaction'
import BriefingsPanel from './components/BriefingsPanel'

const CHANNEL_COLORS = {
  email: '#0071E3',
  whatsapp: '#25D366',
  sms: '#FF9F0A',
  other: '#8E8E93'
}

const BASE_MENU_ITEMS = [
  { key: 'calendar', label: 'Calendario CRM' },
  { key: 'open-data', label: 'Open Data Emarsys' },
  { key: 'automation-results', label: 'Resultados de Automacoes' },
  { key: 'open-data-explorer', label: 'Explorador de Tabelas' },
  { key: 'utm', label: 'Gerador de Tags UTM' },
  { key: 'results', label: 'Resumo de Resultados' },
  { key: 'future-2', label: 'Checklist de Campanha', disabled: true }
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
  const date = new Date(value)
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

function formatMetricValue(key, value) {
  if (key === 'purchaseRevenue') {
    return new Intl.NumberFormat('pt-BR', {
      style: 'currency',
      currency: 'BRL',
      minimumFractionDigits: 2
    }).format(Number(value || 0))
  }
  return new Intl.NumberFormat('pt-BR').format(Number(value || 0))
}

function formatVariation(value) {
  if (value === null || value === undefined) return 'N/A'
  const numeric = Number(value)
  const sign = numeric > 0 ? '+' : ''
  return `${sign}${numeric.toFixed(2)}%`
}

function variationTextColor(value) {
  if (value === null || value === undefined || Number(value) === 0) return 'text-slate-600'
  return Number(value) > 0 ? 'text-emerald-700' : 'text-rose-700'
}

function formatCurrency(value) {
  return new Intl.NumberFormat('pt-BR', {
    style: 'currency',
    currency: 'BRL',
    minimumFractionDigits: 2
  }).format(Number(value || 0))
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

function getRelativeMonth(year, month, offset) {
  const baseDate = new Date(Number(year), Number(month) - 1 + Number(offset), 1)
  return {
    year: baseDate.getFullYear(),
    month: baseDate.getMonth() + 1
  }
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

export default function App() {
  const [activeView, setActiveView] = useState('calendar')
  const [events, setEvents] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [selectedChannel, setSelectedChannel] = useState('all')
  const [selectedEvent, setSelectedEvent] = useState(null)
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
  const [reportYear, setReportYear] = useState(now.getFullYear())
  const [reportMonth, setReportMonth] = useState(now.getMonth() + 1)
  const [ga4Report, setGa4Report] = useState(null)
  const [ga4Loading, setGa4Loading] = useState(false)
  const [ga4Error, setGa4Error] = useState('')
  const [crmAssists, setCrmAssists] = useState(null)
  const [crmAssistsLoading, setCrmAssistsLoading] = useState(false)
  const [crmAssistsError, setCrmAssistsError] = useState('')
  const [crmLtv, setCrmLtv] = useState(null)
  const [crmLtvLoading, setCrmLtvLoading] = useState(false)
  const [crmLtvError, setCrmLtvError] = useState('')
  const [abandonedCartCoupons, setAbandonedCartCoupons] = useState(null)
  const [abandonedCartCouponsLoading, setAbandonedCartCouponsLoading] = useState(false)
  const [abandonedCartCouponsError, setAbandonedCartCouponsError] = useState('')
  const [abandonedCartNonCrmSummary, setAbandonedCartNonCrmSummary] = useState(null)
  const [abandonedCartNonCrmSummaryLoading, setAbandonedCartNonCrmSummaryLoading] = useState(false)
  const [abandonedCartNonCrmSummaryError, setAbandonedCartNonCrmSummaryError] = useState('')
  const [crmResultsComparisons, setCrmResultsComparisons] = useState(null)
  const [crmResultsComparisonsLoading, setCrmResultsComparisonsLoading] = useState(false)
  const [crmResultsComparisonsError, setCrmResultsComparisonsError] = useState('')
  const [abandonedCartCrmScope, setAbandonedCartCrmScope] = useState('all')
  const [crmFunnel, setCrmFunnel] = useState(null)
  const [crmFunnelLoading, setCrmFunnelLoading] = useState(false)
  const [crmFunnelError, setCrmFunnelError] = useState('')
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
        const fallbackColor = CHANNEL_COLORS[channelKey] || CHANNEL_COLORS.other

        return {
          ...event,
          allDay: true,
          backgroundColor: event.backgroundColor || fallbackColor,
          borderColor: event.borderColor || fallbackColor,
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

  const loadGa4MonthlyReport = useCallback(async () => {
    setGa4Loading(true)
    setGa4Error('')

    try {
      const response = await fetch(`/api/ga4/crm/monthly?year=${reportYear}&month=${reportMonth}`)
      let payload = null
      try {
        payload = await response.json()
      } catch (_error) {
        payload = null
      }

      if (!response.ok) {
        const detail = payload?.detail || 'Nao foi possivel carregar resumo de resultados.'
        if (isGa4NoDataError(detail)) {
          setGa4Report(null)
          setGa4Error('')
          return
        }
        throw new Error(detail)
      }

      setGa4Report(payload)
    } catch (err) {
      setGa4Report(null)
      setGa4Error(err instanceof Error ? err.message : 'Falha ao carregar resumo de resultados.')
    } finally {
      setGa4Loading(false)
    }
  }, [reportMonth, reportYear])

  const loadCrmAssists = useCallback(async () => {
    setCrmAssistsLoading(true)
    setCrmAssistsError('')
    const period = getMonthDateRange(reportYear, reportMonth)

    try {
      const response = await fetch(`/api/ga4/crm-assists?start=${period.start}&end=${period.end}`)
      let payload = null
      try {
        payload = await response.json()
      } catch (_error) {
        payload = null
      }

      if (!response.ok) {
        const detail = payload?.detail || 'Nao foi possivel carregar assists de CRM.'
        if (isGa4NoDataError(detail)) {
          setCrmAssists(null)
          setCrmAssistsError('')
          return
        }
        throw new Error(detail)
      }

      setCrmAssists(payload)
    } catch (err) {
      setCrmAssists(null)
      setCrmAssistsError(err instanceof Error ? err.message : 'Falha ao carregar assists de CRM.')
    } finally {
      setCrmAssistsLoading(false)
    }
  }, [reportMonth, reportYear])

  const loadCrmLtv = useCallback(async () => {
    setCrmLtvLoading(true)
    setCrmLtvError('')
    const period = getMonthDateRange(reportYear, reportMonth)

    try {
      const response = await fetch(`/api/ga4/crm-ltv?start=${period.start}&end=${period.end}`)
      let payload = null
      try {
        payload = await response.json()
      } catch (_error) {
        payload = null
      }

      if (!response.ok) {
        const detail = payload?.detail || 'Nao foi possivel carregar LTV de CRM.'
        if (isGa4NoDataError(detail)) {
          setCrmLtv(null)
          setCrmLtvError('')
          return
        }
        throw new Error(detail)
      }

      setCrmLtv(payload)
    } catch (err) {
      setCrmLtv(null)
      setCrmLtvError(err instanceof Error ? err.message : 'Falha ao carregar LTV de CRM.')
    } finally {
      setCrmLtvLoading(false)
    }
  }, [reportMonth, reportYear])

  const loadAbandonedCartCoupons = useCallback(async () => {
    setAbandonedCartCouponsLoading(true)
    setAbandonedCartCouponsError('')
    const period = getMonthDateRange(reportYear, reportMonth)

    try {
      const params = new URLSearchParams({
        start: period.start,
        end: period.end,
        crm_scope: abandonedCartCrmScope
      })
      const response = await fetch(`/api/ga4/abandoned-cart-coupons?${params.toString()}`)
      let payload = null
      try {
        payload = await response.json()
      } catch (_error) {
        payload = null
      }

      if (!response.ok) {
        const detail = payload?.detail || 'Nao foi possivel carregar pedidos com cupons de carrinho abandonado.'
        if (isGa4NoDataError(detail)) {
          setAbandonedCartCoupons(null)
          setAbandonedCartCouponsError('')
          return
        }
        throw new Error(detail)
      }

      setAbandonedCartCoupons(payload)
    } catch (err) {
      setAbandonedCartCoupons(null)
      setAbandonedCartCouponsError(
        err instanceof Error ? err.message : 'Falha ao carregar pedidos com cupons de carrinho abandonado.'
      )
    } finally {
      setAbandonedCartCouponsLoading(false)
    }
  }, [abandonedCartCrmScope, reportMonth, reportYear])

  const loadAbandonedCartNonCrmSummary = useCallback(async () => {
    setAbandonedCartNonCrmSummaryLoading(true)
    setAbandonedCartNonCrmSummaryError('')
    const period = getMonthDateRange(reportYear, reportMonth)

    try {
      const params = new URLSearchParams({
        start: period.start,
        end: period.end,
        crm_scope: 'non_crm'
      })
      const response = await fetch(`/api/ga4/abandoned-cart-coupons?${params.toString()}`)
      let payload = null
      try {
        payload = await response.json()
      } catch (_error) {
        payload = null
      }

      if (!response.ok) {
        const detail = payload?.detail || 'Nao foi possivel carregar o resumo de carrinho abandonado nao CRM.'
        if (isGa4NoDataError(detail)) {
          setAbandonedCartNonCrmSummary(null)
          setAbandonedCartNonCrmSummaryError('')
          return
        }
        throw new Error(detail)
      }

      setAbandonedCartNonCrmSummary(payload)
    } catch (err) {
      setAbandonedCartNonCrmSummary(null)
      setAbandonedCartNonCrmSummaryError(
        err instanceof Error ? err.message : 'Falha ao carregar o resumo de carrinho abandonado nao CRM.'
      )
    } finally {
      setAbandonedCartNonCrmSummaryLoading(false)
    }
  }, [reportMonth, reportYear])

  const loadCrmResultsComparisons = useCallback(async () => {
    setCrmResultsComparisonsLoading(true)
    setCrmResultsComparisonsError('')

    const sameMonthLastYear = { year: reportYear - 1, month: reportMonth }
    const previousMonth = getRelativeMonth(reportYear, reportMonth, -1)

    const loadComparisonSummary = async ({ year, month }) => {
      const period = getMonthDateRange(year, month)
      const [ga4Response, nonCrmResponse] = await Promise.all([
        fetch(`/api/ga4/crm/monthly?year=${year}&month=${month}`),
        fetch(`/api/ga4/abandoned-cart-coupons?${new URLSearchParams({
          start: period.start,
          end: period.end,
          crm_scope: 'non_crm'
        }).toString()}`)
      ])

      let ga4Payload = null
      let nonCrmPayload = null

      try {
        ga4Payload = await ga4Response.json()
      } catch (_error) {
        ga4Payload = null
      }

      try {
        nonCrmPayload = await nonCrmResponse.json()
      } catch (_error) {
        nonCrmPayload = null
      }

      if (!ga4Response.ok) {
        const detail = ga4Payload?.detail || 'Nao foi possivel carregar comparativo de resultados.'
        if (isGa4NoDataError(detail)) {
          return { totalRevenue: 0, purchaseRevenue: 0, nonCrmRevenue: 0 }
        }
        throw new Error(detail)
      }

      if (!nonCrmResponse.ok) {
        const detail = nonCrmPayload?.detail || 'Nao foi possivel carregar comparativo de carrinho abandonado nao CRM.'
        if (isGa4NoDataError(detail)) {
          return {
            totalRevenue: Number(ga4Payload?.current_year?.purchaseRevenue || 0),
            purchaseRevenue: Number(ga4Payload?.current_year?.purchaseRevenue || 0),
            nonCrmRevenue: 0
          }
        }
        throw new Error(detail)
      }

      const purchaseRevenue = Number(ga4Payload?.current_year?.purchaseRevenue || 0)
      const nonCrmRevenue = Number(nonCrmPayload?.purchaseRevenue || 0)

      return {
        totalRevenue: purchaseRevenue + nonCrmRevenue,
        purchaseRevenue,
        nonCrmRevenue
      }
    }

    try {
      const [lastYearSummary, previousMonthSummary] = await Promise.all([
        loadComparisonSummary(sameMonthLastYear),
        loadComparisonSummary(previousMonth)
      ])

      setCrmResultsComparisons({
        lastYearSameMonth: lastYearSummary,
        previousMonth: previousMonthSummary
      })
    } catch (err) {
      setCrmResultsComparisons(null)
      setCrmResultsComparisonsError(
        err instanceof Error ? err.message : 'Falha ao carregar comparativos do resultado geral CRM.'
      )
    } finally {
      setCrmResultsComparisonsLoading(false)
    }
  }, [reportMonth, reportYear])

  const loadCrmFunnel = useCallback(async () => {
    setCrmFunnelLoading(true)
    setCrmFunnelError('')

    try {
      const response = await fetch(`/api/ga4/crm-funnel?year=${reportYear}&month=${reportMonth}`)
      let payload = null
      try {
        payload = await response.json()
      } catch (_error) {
        payload = null
      }

      if (!response.ok) {
        const detail = payload?.detail || 'Nao foi possivel carregar funil de CRM.'
        if (isGa4NoDataError(detail)) {
          setCrmFunnel(null)
          setCrmFunnelError('')
          return
        }
        throw new Error(detail)
      }

      setCrmFunnel(payload)
    } catch (err) {
      setCrmFunnel(null)
      setCrmFunnelError(err instanceof Error ? err.message : 'Falha ao carregar funil de CRM.')
    } finally {
      setCrmFunnelLoading(false)
    }
  }, [reportMonth, reportYear])

  const loadAllResults = useCallback(async () => {
    await Promise.all([
      loadGa4MonthlyReport(),
      loadCrmAssists(),
      loadCrmLtv(),
      loadAbandonedCartCoupons(),
      loadAbandonedCartNonCrmSummary(),
      loadCrmResultsComparisons(),
      loadCrmFunnel()
    ])
  }, [
    loadAbandonedCartCoupons,
    loadAbandonedCartNonCrmSummary,
    loadCrmResultsComparisons,
    loadCrmAssists,
    loadCrmFunnel,
    loadCrmLtv,
    loadGa4MonthlyReport
  ])

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
      const [healthResponse, campaignsResponse, openRatesResponse, programOpenRatesResponse] = await Promise.all([
        fetch('/api/open-data/emarsys/health'),
        fetch(`/api/open-data/emarsys/email-campaigns?${openDataParams.toString()}`),
        fetch(`/api/open-data/emarsys/email-open-rates?${openDataParams.toString()}`),
        fetch(`/api/open-data/emarsys/email-program-open-rates?${openDataParams.toString()}`)
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

      if (errors.length > 0) {
        setOpenDataError(errors.join(' | '))
      }
    } catch (err) {
      setOpenDataHealth(nextHealthPayload)
      setOpenDataItems([])
      setOpenDataOpenRateItems([])
      setOpenDataProgramOpenRateItems([])
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
    if (activeView === 'results') {
      loadAllResults()
    }
  }, [activeView, loadAllResults])

  useEffect(() => {
    if (activeView === 'open-data' || activeView === 'automation-results') {
      loadOpenData()
    }
  }, [activeView, loadOpenData])

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
    if (!userManagementEnabled) return BASE_MENU_ITEMS
    return [...BASE_MENU_ITEMS, { key: 'users', label: 'Usuarios e Perfis' }]
  }, [userManagementEnabled])

  const abandonedCartScopeLabel = useMemo(() => {
    if (abandonedCartCrmScope === 'only_crm') return 'somente CRM'
    if (abandonedCartCrmScope === 'non_crm') return 'nao CRM'
    return 'todos os canais'
  }, [abandonedCartCrmScope])

  const crmResultsSummary = useMemo(() => {
    const purchaseRevenue = Number(ga4Report?.current_year?.purchaseRevenue || 0)
    const nonCrmRevenue = Number(abandonedCartNonCrmSummary?.purchaseRevenue || 0)
    return {
      purchaseRevenue,
      nonCrmRevenue,
      totalRevenue: purchaseRevenue + nonCrmRevenue
    }
  }, [abandonedCartNonCrmSummary?.purchaseRevenue, ga4Report?.current_year?.purchaseRevenue])

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

      return {
        ...stage,
        items,
        sends,
        opens,
        openRate
      }
    })
  }, [openDataProgramOpenRateItems])

  const anniversaryAutomationTotals = useMemo(() => {
    const sends = anniversaryAutomationStages.reduce((sum, stage) => sum + stage.sends, 0)
    const opens = anniversaryAutomationStages.reduce((sum, stage) => sum + stage.opens, 0)
    return {
      sends,
      opens,
      openRate: sends > 0 ? (opens / sends) * 100 : 0
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
    if (activeView === 'automation-results') {
      loadAnniversaryAutomationCouponStats()
    }
  }, [activeView, loadAnniversaryAutomationCouponStats])

  const saturationDays = useMemo(() => {
    const map = {}
    filteredEvents.forEach((event) => {
      const key = event.start
      if (!key) return
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
          <button
            type="button"
            onClick={handleRefresh}
            className="rounded-xl bg-white/20 px-4 py-2 text-sm font-semibold transition hover:bg-white/30"
          >
            Atualizar
          </button>
        </div>
      </section>

      {saturationDays.length > 0 && (
        <section className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-amber-800">
          Risco de saturacao de comunicacao: ha {saturationDays.length} dia(s) com 3+ campanhas.
        </section>
      )}

      <section className="flex flex-wrap items-center gap-2 rounded-xl border border-slate-200 bg-white p-3 shadow-sm">
        {[
          { key: 'all', label: 'Todos', color: '#8E8E93' },
          { key: 'email', label: 'Email', color: CHANNEL_COLORS.email },
          { key: 'whatsapp', label: 'WhatsApp', color: CHANNEL_COLORS.whatsapp },
          { key: 'sms', label: 'SMS', color: CHANNEL_COLORS.sms }
        ].map((item) => (
          <button
            key={item.key}
            type="button"
            onClick={() => setSelectedChannel(item.key)}
            className={`rounded-full border px-4 py-1.5 text-sm font-medium transition ${
              selectedChannel === item.key
                ? 'border-slate-900 bg-slate-900 text-white'
                : 'border-slate-300 bg-white text-slate-700 hover:border-slate-500'
            }`}
          >
            <span className="mr-2 inline-block h-2.5 w-2.5 rounded-full" style={{ backgroundColor: item.color }} />
            {item.label}
          </button>
        ))}
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
          />
        </div>
      </section>

      <BriefingsPanel events={events} />
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
            <div className="rounded-xl border border-slate-200">
              <div className="grid grid-cols-[minmax(0,1fr)_140px_140px_140px] gap-3 border-b border-slate-200 px-4 py-3 text-xs font-semibold uppercase tracking-wide text-slate-500">
                <span>Etapa</span>
                <span>Enviados</span>
                <span>Aberturas</span>
                <span>% abertura</span>
              </div>
              {anniversaryAutomationStages.map((stage) => (
                <div
                  key={stage.key}
                  className="grid grid-cols-[minmax(0,1fr)_140px_140px_140px] gap-3 border-b border-slate-100 px-4 py-3 text-sm last:border-b-0"
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
              {anniversaryAutomationCouponLoading ? (
                <p className="mt-3 text-sm text-slate-600">Carregando receita...</p>
              ) : (
                <div className="mt-3 space-y-1 text-sm text-slate-600">
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

  const renderResultsView = () => {
    const metrics = [
      { key: 'sessions', label: 'Sessoes' },
      { key: 'totalUsers', label: 'Usuarios' },
      { key: 'transactions', label: 'Transacoes' },
      { key: 'purchaseRevenue', label: 'Receita de compras' }
    ]

    return (
      <section className="space-y-5">
        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft md:p-6">
          <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
            <div>
              <h1 className="text-2xl font-semibold text-slate-900">Resumo de Resultados CRM</h1>
              <p className="mt-1 text-sm text-slate-600">Comparativo do mes atual contra o mesmo mes do ano anterior.</p>
            </div>
            <div className="flex flex-wrap items-end gap-3">
              <label className="flex flex-col gap-1 text-sm">
                Ano
                <input
                  type="number"
                  min="2000"
                  max="2100"
                  className="w-28 rounded-lg border border-slate-300 px-3 py-2"
                  value={reportYear}
                  onChange={(event) => setReportYear(Number(event.target.value || now.getFullYear()))}
                />
              </label>
              <label className="flex flex-col gap-1 text-sm">
                Mes
                <input
                  type="number"
                  min="1"
                  max="12"
                  className="w-20 rounded-lg border border-slate-300 px-3 py-2"
                  value={reportMonth}
                  onChange={(event) => setReportMonth(Number(event.target.value || now.getMonth() + 1))}
                />
              </label>
              <button
                type="button"
                onClick={loadAllResults}
                className="rounded-lg bg-brand-500 px-4 py-2 text-sm font-semibold text-white transition hover:bg-brand-600"
              >
                Atualizar
              </button>
            </div>
          </div>
        </section>

        {ga4Error && <section className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-rose-700">{ga4Error}</section>}

        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft md:p-6">
          <div>
            <h2 className="text-xl font-semibold text-slate-900">Resultado Geral - CRM</h2>
          </div>

          {abandonedCartNonCrmSummaryError && (
            <p className="mt-4 text-sm text-rose-700">{abandonedCartNonCrmSummaryError}</p>
          )}

          {crmResultsComparisonsError && <p className="mt-2 text-sm text-rose-700">{crmResultsComparisonsError}</p>}

          {ga4Loading || abandonedCartNonCrmSummaryLoading ? (
            <p className="mt-4 text-sm text-slate-600">Calculando resumo geral...</p>
          ) : ga4Error ? null : (
            <div className="mt-4 grid gap-4 md:grid-cols-3">
              <article className="rounded-xl border border-slate-200 p-4">
                <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-500">Receita de compras</h3>
                <p className="mt-2 text-2xl font-semibold text-slate-900">{formatCurrency(crmResultsSummary.purchaseRevenue)}</p>
              </article>
              <article className="rounded-xl border border-slate-200 p-4">
                <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-500">Carrinho abandonado nao CRM</h3>
                <p className="mt-2 text-2xl font-semibold text-slate-900">{formatCurrency(crmResultsSummary.nonCrmRevenue)}</p>
              </article>
              <article className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-500">Total consolidado</h3>
                <p className="mt-2 text-2xl font-semibold text-slate-900">{formatCurrency(crmResultsSummary.totalRevenue)}</p>
                {crmResultsComparisonsLoading ? (
                  <p className="mt-3 text-sm text-slate-600">Carregando comparativos...</p>
                ) : crmResultsComparisons ? (
                  <div className="mt-3 space-y-1 text-sm text-slate-600">
                    <p>
                      Mesmo mes do ano passado: {formatCurrency(crmResultsComparisons.lastYearSameMonth?.totalRevenue)}
                    </p>
                    <p>Mes anterior: {formatCurrency(crmResultsComparisons.previousMonth?.totalRevenue)}</p>
                  </div>
                ) : null}
              </article>
            </div>
          )}
        </section>

        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft md:p-6">
          {ga4Loading ? (
            <p className="text-sm text-slate-600">Carregando resultados do GA4...</p>
          ) : !ga4Report ? (
            <p className="text-sm text-slate-600">Selecione periodo e clique em atualizar.</p>
          ) : (
            <div className="grid gap-4 md:grid-cols-2">
              {metrics.map((metric) => (
                <article key={metric.key} className="rounded-xl border border-slate-200 p-4">
                  <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">{metric.label}</h2>
                  <p className="mt-2 text-2xl font-semibold text-slate-900">
                    {formatMetricValue(metric.key, ga4Report.current_year?.[metric.key])}
                  </p>
                  <p className="mt-1 text-sm text-slate-600">
                    Ano anterior: {formatMetricValue(metric.key, ga4Report.last_year?.[metric.key])}
                  </p>
                  <p className={`mt-1 text-sm font-semibold ${variationTextColor(ga4Report.variation?.[metric.key])}`}>
                    Variacao: {formatVariation(ga4Report.variation?.[metric.key])}
                  </p>
                </article>
              ))}
            </div>
          )}
        </section>

        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft md:p-6">
          <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
            <div>
              <h2 className="text-lg font-semibold text-slate-900">Pedidos com Cupom de Carrinho Abandonado</h2>
              <p className="text-sm text-slate-600">
                Pedidos do mes selecionado que usaram os cupons CARRINHO-100, CARRINHO-50, CARRINHO-30 ou CARRINHO-15,
                filtrados em {abandonedCartScopeLabel}.
              </p>
            </div>
            <label className="flex flex-col gap-1 text-sm text-slate-600">
              Recorte
              <select
                value={abandonedCartCrmScope}
                onChange={(event) => setAbandonedCartCrmScope(event.target.value)}
                className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900"
              >
                <option value="all">Todos</option>
                <option value="only_crm">Somente CRM</option>
                <option value="non_crm">Nao CRM</option>
              </select>
            </label>
          </div>

          {abandonedCartCouponsError && (
            <p className="mt-4 text-sm text-rose-700">{abandonedCartCouponsError}</p>
          )}

          {abandonedCartCouponsLoading ? (
            <p className="mt-4 text-sm text-slate-600">Carregando pedidos com cupom...</p>
          ) : abandonedCartCoupons ? (
            <div className="mt-4 space-y-4">
              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                <article className="rounded-xl border border-slate-200 p-4">
                  <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-500">Quantidade de transacoes</h3>
                  <p className="mt-2 text-2xl font-semibold text-slate-900">
                    {new Intl.NumberFormat('pt-BR').format(Number(abandonedCartCoupons.transactions || 0))}
                  </p>
                </article>
                <article className="rounded-xl border border-slate-200 p-4">
                  <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-500">Receita total</h3>
                  <p className="mt-2 text-2xl font-semibold text-slate-900">
                    {formatCurrency(abandonedCartCoupons.purchaseRevenue)}
                  </p>
                </article>
                <article className="rounded-xl border border-slate-200 p-4">
                  <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-500">Ticket medio</h3>
                  <p className="mt-2 text-2xl font-semibold text-slate-900">
                    {formatCurrency(abandonedCartCoupons.average_ticket)}
                  </p>
                </article>
                <article className="rounded-xl border border-slate-200 p-4">
                  <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-500">Cupom lider</h3>
                  {abandonedCartCoupons.top_coupon ? (
                    <>
                      <p className="mt-2 text-xl font-semibold text-slate-900">
                        {abandonedCartCoupons.top_coupon.coupon}
                      </p>
                      <p className="mt-1 text-sm text-slate-600">
                        {new Intl.NumberFormat('pt-BR').format(Number(abandonedCartCoupons.top_coupon.transactions || 0))}{' '}
                        pedidos ({Number(abandonedCartCoupons.top_coupon.share_of_transactions || 0).toFixed(2)}%)
                      </p>
                    </>
                  ) : (
                    <p className="mt-2 text-sm text-slate-600">Sem destaque no periodo.</p>
                  )}
                </article>
              </div>

              <div className="rounded-xl border border-slate-200">
                <div className="grid grid-cols-[minmax(0,1fr)_140px_160px] gap-3 border-b border-slate-200 px-4 py-3 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  <span>Cupom</span>
                  <span>Pedidos</span>
                  <span>Receita</span>
                </div>
                {Array.isArray(abandonedCartCoupons.by_coupon) && abandonedCartCoupons.by_coupon.length > 0 ? (
                  abandonedCartCoupons.by_coupon.map((coupon) => (
                    <div
                      key={coupon.coupon}
                      className="grid grid-cols-[minmax(0,1fr)_140px_160px] gap-3 border-b border-slate-100 px-4 py-3 text-sm last:border-b-0"
                    >
                      <span className="font-medium text-slate-900">{coupon.coupon}</span>
                      <span className="text-slate-700">
                        {new Intl.NumberFormat('pt-BR').format(Number(coupon.transactions || 0))}
                      </span>
                      <span className="text-slate-700">{formatCurrency(coupon.purchaseRevenue)}</span>
                    </div>
                  ))
                ) : (
                  <p className="px-4 py-4 text-sm text-slate-600">Nenhum pedido com esses cupons no periodo selecionado.</p>
                )}
              </div>
            </div>
          ) : (
            <p className="mt-4 text-sm text-slate-600">Sem dados para o periodo.</p>
          )}
        </section>

        <section className="grid gap-4 md:grid-cols-2">
          <article className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft">
            <h2 className="text-lg font-semibold text-slate-900">Assistencia de Conversao (CRM)</h2>
            <p className="mt-1 text-sm text-slate-600">Periodo selecionado por sessoes e usuarios CRM assistidos.</p>

            {crmAssistsError && <p className="mt-4 text-sm text-rose-700">{crmAssistsError}</p>}

            {crmAssistsLoading ? (
              <p className="mt-4 text-sm text-slate-600">Carregando assists...</p>
            ) : crmAssists ? (
              <div className="mt-4 grid gap-3 text-sm">
                <p>
                  <span className="font-semibold text-slate-900">Sessoes CRM:</span>{' '}
                  {new Intl.NumberFormat('pt-BR').format(Number(crmAssists.crm_sessions || 0))}
                </p>
                <p>
                  <span className="font-semibold text-slate-900">Usuarios CRM:</span>{' '}
                  {new Intl.NumberFormat('pt-BR').format(Number(crmAssists.crm_users || 0))}
                </p>
                <p>
                  <span className="font-semibold text-slate-900">Compras assistidas:</span>{' '}
                  {new Intl.NumberFormat('pt-BR').format(Number(crmAssists.assisted_purchases || 0))}
                </p>
                <p>
                  <span className="font-semibold text-slate-900">Receita assistida:</span>{' '}
                  {formatCurrency(crmAssists.assisted_revenue)}
                </p>
              </div>
            ) : (
              <p className="mt-4 text-sm text-slate-600">Sem dados para o periodo.</p>
            )}
          </article>

          <article className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft">
            <h2 className="text-lg font-semibold text-slate-900">LTV do CRM</h2>
            <p className="mt-1 text-sm text-slate-600">Coorte de usuarios adquiridos por CRM no periodo selecionado.</p>

            {crmLtvError && <p className="mt-4 text-sm text-rose-700">{crmLtvError}</p>}

            {crmLtvLoading ? (
              <p className="mt-4 text-sm text-slate-600">Carregando LTV...</p>
            ) : crmLtv ? (
              <div className="mt-4 grid gap-3 text-sm">
                <p>
                  <span className="font-semibold text-slate-900">Novos usuarios CRM:</span>{' '}
                  {new Intl.NumberFormat('pt-BR').format(Number(crmLtv.crm_new_users || 0))}
                </p>
                <p>
                  <span className="font-semibold text-slate-900">Receita total da coorte:</span>{' '}
                  {formatCurrency(crmLtv.total_revenue_from_crm_users)}
                </p>
                <p>
                  <span className="font-semibold text-slate-900">LTV medio CRM:</span>{' '}
                  {formatCurrency(crmLtv.crm_ltv)}
                </p>
              </div>
            ) : (
              <p className="mt-4 text-sm text-slate-600">Sem dados para o periodo.</p>
            )}
          </article>
        </section>

        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft md:p-6">
          <h2 className="text-lg font-semibold text-slate-900">Funil de Conversao CRM</h2>
          <p className="mt-1 text-sm text-slate-600">Progressao do CRM: entrada, produto, carrinho, checkout e compra.</p>

          {crmFunnelError && <p className="mt-4 text-sm text-rose-700">{crmFunnelError}</p>}

          {crmFunnelLoading ? (
            <p className="mt-4 text-sm text-slate-600">Carregando funil...</p>
          ) : crmFunnel ? (
            <div className="mt-4 grid gap-4 md:grid-cols-5">
              {[
                { label: 'Sessoes', value: crmFunnel.sessions, rate: null },
                { label: 'Produto', value: crmFunnel.product_view, rate: crmFunnel.conversion_rates?.view_rate },
                { label: 'Carrinho', value: crmFunnel.add_to_cart, rate: crmFunnel.conversion_rates?.cart_rate },
                { label: 'Checkout', value: crmFunnel.checkout, rate: crmFunnel.conversion_rates?.checkout_rate },
                { label: 'Compra', value: crmFunnel.purchase, rate: crmFunnel.conversion_rates?.purchase_rate }
              ].map((step) => (
                <article key={step.label} className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                  <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">{step.label}</h3>
                  <p className="mt-2 text-2xl font-semibold text-slate-900">
                    {new Intl.NumberFormat('pt-BR').format(Number(step.value || 0))}
                  </p>
                  {step.rate !== null && step.rate !== undefined && (
                    <p className="mt-1 text-sm text-slate-600">
                      Taxa: {(Number(step.rate) * 100).toFixed(2)}%
                    </p>
                  )}
                </article>
              ))}
            </div>
          ) : (
            <p className="mt-4 text-sm text-slate-600">Sem dados para o periodo.</p>
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
          {activeView === 'results' && renderResultsView()}
          {activeView === 'users' && userManagementEnabled && renderUsersView()}
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
          </div>
        </div>
      )}
    </main>
  )
}
