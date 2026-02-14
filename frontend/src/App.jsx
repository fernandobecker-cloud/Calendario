import { useCallback, useMemo, useState } from 'react'
import FullCalendar from '@fullcalendar/react'
import dayGridPlugin from '@fullcalendar/daygrid'
import interactionPlugin from '@fullcalendar/interaction'

const CHANNEL_COLORS = {
  email: '#0071E3',
  whatsapp: '#25D366',
  sms: '#FF9F0A',
  other: '#8E8E93'
}

const MENU_ITEMS = [
  { key: 'calendar', label: 'Calendario CRM' },
  { key: 'utm', label: 'Gerador de Tags UTM' },
  { key: 'future-1', label: 'Resumo de Resultados', disabled: true },
  { key: 'future-2', label: 'Checklist de Campanha', disabled: true }
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

  const loadEvents = useCallback(async () => {
    setLoading(true)
    setError('')

    try {
      const response = await fetch('/api/events')
      if (!response.ok) throw new Error('Falha ao carregar campanhas')
      const contentType = response.headers.get('content-type') || ''
      if (!contentType.includes('application/json')) {
        throw new Error('API respondeu em formato inesperado. Verifique se o backend FastAPI esta rodando na porta 8000.')
      }

      const payload = await response.json()
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

  const filteredEvents = useMemo(() => {
    if (selectedChannel === 'all') return events
    return events.filter((event) => event?.extendedProps?.channelKey === selectedChannel)
  }, [events, selectedChannel])

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

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-7xl flex-col gap-5 px-4 py-6 md:px-6 lg:px-8">
      <div className="grid gap-4 md:grid-cols-[260px_1fr]">
        <aside className="h-fit rounded-2xl border border-slate-200 bg-white p-3 shadow-soft">
          <p className="px-2 pb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Ferramentas CRM</p>
          <nav className="space-y-1">
            {MENU_ITEMS.map((item) => (
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

        <div className="space-y-5">{activeView === 'calendar' ? renderCalendarView() : renderUtmView()}</div>
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
