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
  const [events, setEvents] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [selectedChannel, setSelectedChannel] = useState('all')
  const [selectedEvent, setSelectedEvent] = useState(null)

  const loadEvents = useCallback(async () => {
    setLoading(true)
    setError('')

    try {
      const response = await fetch('/api/events')
      if (!response.ok) throw new Error('Falha ao carregar campanhas')

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

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-7xl flex-col gap-5 px-4 py-6 md:px-6 lg:px-8">
      <section className="rounded-2xl bg-gradient-to-r from-brand-500 to-brand-600 p-6 text-white shadow-soft md:p-8">
        <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight md:text-4xl">CRM Campaign Planner</h1>
            <p className="mt-2 text-sm text-blue-100 md:text-base">Calendário editorial de campanhas</p>
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
          Risco de saturação de comunicação: há {saturationDays.length} dia(s) com 3+ campanhas.
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
              month: 'Mês',
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
                ✕
              </button>
            </div>

            <div className="space-y-3 text-sm text-slate-700">
              <p>
                <span className="font-semibold text-slate-900">Data:</span>{' '}
                {selectedEvent.extendedProps?.data_original || formatDate(selectedEvent.startStr)}
              </p>
              <p>
                <span className="font-semibold text-slate-900">Canal:</span>{' '}
                {selectedEvent.extendedProps?.canal || 'Não informado'}
              </p>
              <p>
                <span className="font-semibold text-slate-900">Produto:</span>{' '}
                {selectedEvent.extendedProps?.produto || 'Não informado'}
              </p>
              <p>
                <span className="font-semibold text-slate-900">Observação:</span>{' '}
                {selectedEvent.extendedProps?.observacao || 'Sem observação'}
              </p>
            </div>
          </div>
        </div>
      )}
    </main>
  )
}
