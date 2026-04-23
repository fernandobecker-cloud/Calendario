import { useState, useCallback } from 'react'

function formatCurrency(value) {
  if (value == null) return '-'
  return new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(value)
}

function getDefaultDates() {
  const today = new Date()
  const firstOfMonth = new Date(today.getFullYear(), today.getMonth(), 1)
  return {
    start: firstOfMonth.toISOString().split('T')[0],
    end: today.toISOString().split('T')[0],
  }
}

const CHANNEL_CONFIG = {
  email: {
    label: 'Email',
    color: 'text-blue-600',
    bg: 'bg-blue-50',
    border: 'border-blue-200',
  },
  sms: {
    label: 'SMS',
    color: 'text-orange-600',
    bg: 'bg-orange-50',
    border: 'border-orange-200',
  },
  whatsapp: {
    label: 'WhatsApp',
    color: 'text-emerald-600',
    bg: 'bg-emerald-50',
    border: 'border-emerald-200',
  },
}

export default function ResultadoGeralPage() {
  const defaults = getDefaultDates()
  const [startDate, setStartDate] = useState(defaults.start)
  const [endDate, setEndDate] = useState(defaults.end)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handleAtualizar = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const params = new URLSearchParams()
      if (startDate) params.set('start', startDate)
      if (endDate) params.set('end', endDate)
      const response = await fetch(`/api/open-data/emarsys/monthly-revenue?${params.toString()}`)
      let payload = null
      try { payload = await response.json() } catch (_) {}
      if (!response.ok) {
        throw new Error(payload?.detail || 'Erro ao carregar receita atribuída.')
      }
      setData(payload)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Falha ao carregar dados.')
      setData(null)
    } finally {
      setLoading(false)
    }
  }, [startDate, endDate])

  const monthRow = data?.items?.[0] ?? null
  const byChannel = data?.by_channel ?? []

  return (
    <div className="mx-auto max-w-7xl px-4 py-8 md:px-6 lg:px-8">
      <h1 className="mb-6 text-xl font-bold text-slate-900">Resultado Geral CRM iPlace</h1>

      {/* Filtros */}
      <section className="mb-6 rounded-2xl border border-slate-200 bg-white p-5 shadow-soft">
        <div className="flex flex-wrap items-end gap-4">
          <label className="flex flex-col gap-1 text-sm text-slate-600">
            Data inicial
            <input
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className="rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm text-slate-600">
            Data final
            <input
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              className="rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900"
            />
          </label>
          <button
            onClick={handleAtualizar}
            disabled={loading}
            className="rounded-lg bg-slate-900 px-5 py-2 text-sm font-semibold text-white transition hover:bg-slate-700 disabled:opacity-50"
          >
            {loading ? 'Carregando...' : 'Atualizar'}
          </button>
        </div>
      </section>

      {error && (
        <p className="mb-4 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          {error}
        </p>
      )}

      {!data && !loading && !error && (
        <p className="text-sm text-slate-500">Selecione o período e clique em Atualizar.</p>
      )}

      {/* Card Receita Atribuída */}
      {data && (
        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft md:p-6">
          <h2 className="mb-4 text-sm font-semibold uppercase tracking-wide text-slate-500">
            Receita Atribuída
          </h2>

          <p className="text-4xl font-bold text-slate-900">
            {formatCurrency(data.total_receita_atribuida)}
          </p>

          {monthRow && (
            <p className="mt-1 text-sm text-slate-500">
              {data.start_date} até {data.end_date}
              {' · '}
              {monthRow.pedidos_atribuidos.toLocaleString('pt-BR')} pedidos
              {' · '}
              {monthRow.compradores_unicos.toLocaleString('pt-BR')} compradores únicos
            </p>
          )}

          {byChannel.length > 0 && (
            <div className="mt-5 grid gap-3 sm:grid-cols-3">
              {byChannel.map((ch) => {
                const cfg = CHANNEL_CONFIG[ch.canal] ?? {
                  label: ch.canal,
                  color: 'text-slate-600',
                  bg: 'bg-slate-50',
                  border: 'border-slate-200',
                }
                return (
                  <article
                    key={ch.canal}
                    className={`rounded-xl border ${cfg.border} ${cfg.bg} p-4`}
                  >
                    <h3 className={`text-xs font-semibold uppercase tracking-wide ${cfg.color}`}>
                      {cfg.label}
                    </h3>
                    <p className="mt-2 text-2xl font-bold text-slate-900">
                      {formatCurrency(ch.receita_atribuida)}
                    </p>
                    <p className="mt-1 text-xs text-slate-500">
                      {ch.pedidos_atribuidos.toLocaleString('pt-BR')} pedidos
                      {' · '}
                      {ch.compradores_unicos.toLocaleString('pt-BR')} compradores únicos
                    </p>
                  </article>
                )
              })}
            </div>
          )}
        </section>
      )}
    </div>
  )
}
