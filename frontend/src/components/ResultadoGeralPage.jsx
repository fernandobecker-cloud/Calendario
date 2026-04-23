import { useState, useCallback } from 'react'

function formatCurrency(value) {
  if (value == null || isNaN(Number(value))) return '-'
  return new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(Number(value))
}

function getDefaultDates() {
  const today = new Date()
  const firstOfMonth = new Date(today.getFullYear(), today.getMonth(), 1)
  return {
    start: firstOfMonth.toISOString().split('T')[0],
    end: today.toISOString().split('T')[0],
  }
}

const VIEWS = [
  { key: 'executivo', label: 'Executivo' },
  { key: 'atribuida', label: 'Atribuída Detalhada' },
  { key: 'direta', label: 'Direta Detalhada' },
]

const CHANNEL_CONFIG = {
  email: { label: 'Email', color: 'text-blue-600', bg: 'bg-blue-50', border: 'border-blue-200' },
  sms: { label: 'SMS', color: 'text-orange-600', bg: 'bg-orange-50', border: 'border-orange-200' },
  whatsapp: { label: 'WhatsApp', color: 'text-emerald-600', bg: 'bg-emerald-50', border: 'border-emerald-200' },
}

async function fetchJson(url) {
  const res = await fetch(url)
  const json = await res.json().catch(() => null)
  if (!res.ok) return { ok: false, data: null }
  return { ok: true, data: json }
}

export default function ResultadoGeralPage() {
  const defaults = getDefaultDates()
  const [activeView, setActiveView] = useState('executivo')
  const [startDate, setStartDate] = useState(defaults.start)
  const [endDate, setEndDate] = useState(defaults.end)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const [executivoData, setExecutivoData] = useState(null)

  const handleAtualizar = useCallback(async () => {
    if (!startDate) return
    setLoading(true)
    setError('')

    try {
      if (activeView === 'executivo') {
        const [year, month] = startDate.split('-').map(Number)
        const params = new URLSearchParams({ start: startDate, ...(endDate ? { end: endDate } : {}) })

        const [atribuida, ga4, abandoned] = await Promise.all([
          fetchJson(`/api/open-data/emarsys/monthly-revenue?${params}`),
          fetchJson(`/api/ga4/crm/monthly?year=${year}&month=${month}`),
          fetchJson(`/api/ga4/abandoned-cart-coupons?start=${startDate}&end=${endDate || startDate}&crm_scope=non_crm`),
        ])

        const purchaseCrm = Number(ga4.data?.current_year?.purchaseRevenue || 0)
        const purchaseNonCrm = Number(abandoned.data?.purchaseRevenue || 0)

        setExecutivoData({
          atribuida: atribuida.ok ? atribuida.data : null,
          direta: {
            totalConsolidado: purchaseCrm + purchaseNonCrm,
            purchaseCrm,
            purchaseNonCrm,
          },
        })
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Falha ao carregar dados.')
    } finally {
      setLoading(false)
    }
  }, [activeView, startDate, endDate])

  return (
    <div className="mx-auto max-w-7xl px-4 py-8 md:px-6 lg:px-8">
      <h1 className="mb-6 text-xl font-bold text-slate-900">Resultado Geral</h1>

      <div className="flex gap-6">
        {/* Sidebar */}
        <aside className="w-52 shrink-0">
          <nav className="flex flex-col gap-1">
            {VIEWS.map((v) => (
              <button
                key={v.key}
                onClick={() => setActiveView(v.key)}
                className={`rounded-lg px-4 py-2.5 text-left text-sm font-semibold transition ${
                  activeView === v.key
                    ? 'bg-slate-900 text-white'
                    : 'text-slate-700 hover:bg-slate-100'
                }`}
              >
                {v.label}
              </button>
            ))}
          </nav>
        </aside>

        {/* Conteúdo */}
        <main className="min-w-0 flex-1">
          {/* Filtro de datas */}
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

          {activeView === 'executivo' && (
            <ExecutivoView data={executivoData} loading={loading} />
          )}
          {activeView === 'atribuida' && <PlaceholderView label="Atribuída Detalhada" />}
          {activeView === 'direta' && <PlaceholderView label="Direta Detalhada" />}
        </main>
      </div>
    </div>
  )
}

function ExecutivoView({ data, loading }) {
  if (loading) {
    return <p className="text-sm text-slate-500">Carregando...</p>
  }
  if (!data) {
    return <p className="text-sm text-slate-500">Selecione o período e clique em Atualizar.</p>
  }

  const { atribuida, direta } = data
  const monthRow = atribuida?.items?.[0] ?? null
  const byChannel = atribuida?.by_channel ?? []

  return (
    <div className="flex flex-col gap-4">
      {/* Receita Atribuída */}
      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft md:p-6">
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
          Receita Atribuída
        </h2>

        {atribuida ? (
          <>
            <p className="text-4xl font-bold text-slate-900">
              {formatCurrency(atribuida.total_receita_atribuida)}
            </p>
            {monthRow && (
              <p className="mt-1 text-sm text-slate-500">
                {monthRow.pedidos_atribuidos.toLocaleString('pt-BR')} pedidos
                {' · '}
                {monthRow.compradores_unicos.toLocaleString('pt-BR')} compradores únicos
              </p>
            )}
            {byChannel.length > 0 && (
              <div className="mt-4 grid gap-3 sm:grid-cols-3">
                {byChannel.map((ch) => {
                  const cfg = CHANNEL_CONFIG[ch.canal] ?? {
                    label: ch.canal,
                    color: 'text-slate-600',
                    bg: 'bg-slate-50',
                    border: 'border-slate-200',
                  }
                  return (
                    <article key={ch.canal} className={`rounded-xl border ${cfg.border} ${cfg.bg} p-4`}>
                      <h3 className={`text-xs font-semibold uppercase tracking-wide ${cfg.color}`}>
                        {cfg.label}
                      </h3>
                      <p className="mt-2 text-xl font-bold text-slate-900">
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
          </>
        ) : (
          <p className="text-sm text-slate-500">Dados não disponíveis.</p>
        )}
      </section>

      {/* Receita Direta */}
      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft md:p-6">
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
          Receita Direta
        </h2>

        <p className="text-4xl font-bold text-slate-900">
          {formatCurrency(direta.totalConsolidado)}
        </p>

        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <article className="rounded-xl border border-slate-200 p-4">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Receita CRM
            </h3>
            <p className="mt-2 text-xl font-bold text-slate-900">
              {formatCurrency(direta.purchaseCrm)}
            </p>
          </article>
          <article className="rounded-xl border border-slate-200 p-4">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Carrinho Abandonado (não CRM)
            </h3>
            <p className="mt-2 text-xl font-bold text-slate-900">
              {formatCurrency(direta.purchaseNonCrm)}
            </p>
          </article>
        </div>
      </section>
    </div>
  )
}

function PlaceholderView({ label }) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft">
      <p className="text-sm text-slate-500">{label} — em construção.</p>
    </section>
  )
}
