import { useState, useCallback, useMemo, useEffect } from 'react'

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

function getMonthDateRange(year, month) {
  const y = Number(year)
  const m = Number(month)
  const safeMonth = Math.min(Math.max(m, 1), 12)
  const lastDay = new Date(y, safeMonth, 0).getDate()
  const monthText = String(safeMonth).padStart(2, '0')
  return {
    start: `${y}-${monthText}-01`,
    end: `${y}-${monthText}-${String(lastDay).padStart(2, '0')}`,
  }
}

function getRelativeMonth(year, month, offset) {
  const baseDate = new Date(Number(year), Number(month) - 1 + Number(offset), 1)
  return { year: baseDate.getFullYear(), month: baseDate.getMonth() + 1 }
}

function isGa4NoDataError(detail) {
  return String(detail || '').toLowerCase().includes('future currency exchange rate not exist')
}

function formatMetricValue(key, value) {
  if (key === 'purchaseRevenue') {
    return new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL', minimumFractionDigits: 2 }).format(Number(value || 0))
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

const VIEWS = [
  { key: 'executivo', label: 'Executivo' },
  { key: 'atribuida', label: 'Atribuída Detalhada' },
  { key: 'direta', label: 'Direta Detalhada' },
]

const CHANNEL_CONFIG = {
  email:    { label: 'Email',    color: 'text-blue-600',    bg: 'bg-blue-50',    border: 'border-blue-200'    },
  sms:      { label: 'SMS',      color: 'text-orange-600',  bg: 'bg-orange-50',  border: 'border-orange-200'  },
  whatsapp: { label: 'WhatsApp', color: 'text-emerald-600', bg: 'bg-emerald-50', border: 'border-emerald-200' },
}

const CATEGORIA_CONFIG = {
  marketing:    { label: 'Marketing',      bg: 'bg-emerald-50', text: 'text-emerald-700', border: 'border-emerald-200', dot: 'bg-emerald-500' },
  transacional: { label: 'Transacional',   bg: 'bg-amber-50',   text: 'text-amber-700',   border: 'border-amber-200',   dot: 'bg-amber-400'   },
  nps:          { label: 'NPS / Pesquisa', bg: 'bg-blue-50',    text: 'text-blue-700',    border: 'border-blue-200',    dot: 'bg-blue-400'    },
  servico:      { label: 'Serviço / AT',   bg: 'bg-slate-50',   text: 'text-slate-600',   border: 'border-slate-200',   dot: 'bg-slate-400'   },
}

const CANAL_LABELS = { email: 'Email', sms: 'SMS', whatsapp: 'WhatsApp' }

async function fetchJson(url) {
  const res = await fetch(url)
  const json = await res.json().catch(() => null)
  if (!res.ok) return { ok: false, data: null }
  return { ok: true, data: json }
}

function CategoriaBadge({ categoria }) {
  const cfg = CATEGORIA_CONFIG[categoria] ?? CATEGORIA_CONFIG.marketing
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${cfg.bg} ${cfg.text}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${cfg.dot}`} />
      {cfg.label}
    </span>
  )
}

function Table({ columns, rows, emptyText = 'Nenhum resultado.' }) {
  if (!rows || rows.length === 0) {
    return <p className="text-sm text-slate-500">{emptyText}</p>
  }
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-sm">
        <thead>
          <tr className="border-b border-slate-200">
            {columns.map((col) => (
              <th
                key={col.key}
                className={`whitespace-nowrap px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-slate-500 ${col.right ? 'text-right' : ''}`}
              >
                {col.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className={i % 2 === 0 ? 'bg-white' : 'bg-slate-50'}>
              {columns.map((col) => (
                <td
                  key={col.key}
                  className={`whitespace-nowrap px-3 py-2 text-slate-700 ${col.right ? 'text-right tabular-nums' : ''}`}
                >
                  {col.format ? col.format(row[col.key], row) : (row[col.key] ?? '-')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function ResumoAtribuicao({ totais, resumoPorCategoria }) {
  const ruido = totais.ruido
  const totalCrm = totais.total_crm ?? 0
  const pctRuido = totais.reportado > 0 ? (ruido / totais.reportado) * 100 : 0
  const pctMarketing = totais.reportado > 0 ? (totais.marketing / totais.reportado) * 100 : 0
  const pctCobertura = totalCrm > 0 ? (totais.marketing / totalCrm) * 100 : 0

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft md:p-6">
      <h2 className="mb-4 text-sm font-semibold uppercase tracking-wide text-slate-500">
        Receita Atribuída — Reportado vs. Real vs. Total CRM
      </h2>

      <div className="mb-1 h-3 w-full overflow-hidden rounded-full bg-slate-100">
        <div className="relative h-full w-full">
          {totalCrm > 0 && (
            <div
              className="absolute h-full rounded-full bg-slate-300 transition-all"
              style={{ width: `${Math.min((totais.reportado / totalCrm) * 100, 100).toFixed(1)}%` }}
            />
          )}
          {totalCrm > 0 && (
            <div
              className="absolute h-full rounded-full bg-emerald-500 transition-all"
              style={{ width: `${Math.min(pctCobertura, 100).toFixed(1)}%` }}
            />
          )}
        </div>
      </div>
      <p className="mb-5 text-xs text-slate-400">
        Verde = marketing real · Cinza = atribuída reportada · Base = total CRM (si_purchases)
      </p>

      <div className="mb-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div className="rounded-xl border border-violet-200 bg-violet-50 p-4">
          <p className="text-xs font-semibold uppercase tracking-wide text-violet-600">Total CRM</p>
          <p className="mt-1 text-2xl font-bold text-slate-900">{formatCurrency(totalCrm)}</p>
          <p className="mt-0.5 text-xs text-violet-600">todas as compras de clientes Emarsys</p>
        </div>
        <div className="rounded-xl border border-slate-200 p-4">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Atribuída Reportada</p>
          <p className="mt-1 text-2xl font-bold text-slate-900">{formatCurrency(totais.reportado)}</p>
          <p className="mt-0.5 text-xs text-slate-400">
            {totalCrm > 0 ? `${((totais.reportado / totalCrm) * 100).toFixed(1)}% do total CRM` : 'conforme Emarsys'}
          </p>
        </div>
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4">
          <p className="text-xs font-semibold uppercase tracking-wide text-emerald-600">Receita Real (Marketing)</p>
          <p className="mt-1 text-2xl font-bold text-slate-900">{formatCurrency(totais.marketing)}</p>
          <p className="mt-0.5 text-xs text-emerald-600">
            {totalCrm > 0 ? `${pctCobertura.toFixed(1)}% do total CRM` : `${pctMarketing.toFixed(1)}% da atribuída`}
          </p>
        </div>
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
          <p className="text-xs font-semibold uppercase tracking-wide text-amber-600">Ruído de Atribuição</p>
          <p className="mt-1 text-2xl font-bold text-slate-900">{formatCurrency(ruido)}</p>
          <p className="mt-0.5 text-xs text-amber-600">{pctRuido.toFixed(1)}% da atribuída</p>
        </div>
      </div>

      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        {resumoPorCategoria.map((r) => {
          const cfg = CATEGORIA_CONFIG[r.categoria] ?? CATEGORIA_CONFIG.marketing
          return (
            <div key={r.categoria} className={`rounded-lg border ${cfg.border} ${cfg.bg} px-3 py-2.5`}>
              <div className="flex items-center gap-1.5">
                <span className={`h-2 w-2 rounded-full ${cfg.dot}`} />
                <p className={`text-xs font-semibold ${cfg.text}`}>{cfg.label}</p>
              </div>
              <p className="mt-1 text-sm font-bold text-slate-800">{formatCurrency(r.receita_total)}</p>
              <p className="text-xs text-slate-400">{r.num_campanhas} campanhas</p>
            </div>
          )
        })}
      </div>
    </section>
  )
}

export default function ResultadoGeralPage() {
  const defaults = getDefaultDates()
  const [activeView, setActiveView] = useState('executivo')
  const [startDate, setStartDate] = useState(defaults.start)
  const [endDate, setEndDate] = useState(defaults.end)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [filtroCategoria, setFiltroCategoria] = useState('todos')

  const [executivoData, setExecutivoData] = useState(null)
  const [atribuidaData, setAtribuidaData] = useState(null)
  const [diretaRefreshKey, setDiretaRefreshKey] = useState(0)

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
      } else if (activeView === 'atribuida') {
        const params = new URLSearchParams({ start: startDate, ...(endDate ? { end: endDate } : {}) })
        const res = await fetchJson(`/api/open-data/emarsys/audit-receita-por-campanha?${params}`)
        if (!res.ok) {
          setError('Falha ao carregar dados de receita atribuída.')
          return
        }
        setAtribuidaData({
          items: res.data?.items ?? [],
          totais: res.data?.totais ?? null,
          resumoPorCategoria: res.data?.resumo_por_categoria ?? [],
        })
      } else if (activeView === 'direta') {
        setDiretaRefreshKey((k) => k + 1)
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
          {activeView === 'atribuida' && (
            <AtribuidaDetalhadaView
              data={atribuidaData}
              loading={loading}
              filtroCategoria={filtroCategoria}
              setFiltroCategoria={setFiltroCategoria}
            />
          )}
          {activeView === 'direta' && (
            <DiretaDetalhadaView startDate={startDate} endDate={endDate} refreshKey={diretaRefreshKey} />
          )}
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

function AtribuidaDetalhadaView({ data, loading, filtroCategoria, setFiltroCategoria }) {
  if (loading) {
    return <p className="text-sm text-slate-500">Carregando...</p>
  }
  if (!data) {
    return <p className="text-sm text-slate-500">Selecione o período e clique em Atualizar.</p>
  }

  const { items, totais, resumoPorCategoria } = data
  const canalLabel = (v) => CANAL_LABELS[v] ?? v ?? '-'

  const campanhaCols = [
    { key: 'categoria',          label: 'Tipo',              format: (v) => <CategoriaBadge categoria={v} /> },
    { key: 'canal',              label: 'Canal',             format: canalLabel },
    { key: 'nome_campanha',      label: 'Campanha' },
    { key: 'campaign_id',        label: 'ID' },
    { key: 'pedidos_atribuidos', label: 'Pedidos',           right: true },
    { key: 'compradores_unicos', label: 'Compradores',       right: true },
    { key: 'receita_atribuida',  label: 'Receita Atribuída', right: true, format: formatCurrency },
  ]

  const categorias = [
    { key: 'todos',       label: 'Todos' },
    { key: 'marketing',   label: 'Marketing' },
    { key: 'transacional', label: 'Transacional' },
    { key: 'nps',         label: 'NPS / Pesquisa' },
    { key: 'servico',     label: 'Serviço / AT' },
  ]

  const campanhasFiltradas = filtroCategoria === 'todos'
    ? items
    : items.filter((r) => r.categoria === filtroCategoria)

  return (
    <div className="flex flex-col gap-4">
      {totais && (
        <ResumoAtribuicao totais={totais} resumoPorCategoria={resumoPorCategoria} />
      )}

      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft md:p-6">
        <div className="mb-3 flex items-center gap-3">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
            Receita por Campanha
          </h2>
          <span className="rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-semibold text-slate-700">
            {items.length}
          </span>
        </div>
        <p className="mb-4 text-xs text-slate-400">
          Receita atribuída agrupada por campanha e canal, ordenada por maior receita. Top 200.
        </p>

        <div className="mb-4 flex flex-wrap gap-2">
          {categorias.map((c) => (
            <button
              key={c.key}
              onClick={() => setFiltroCategoria(c.key)}
              className={`rounded-full px-3 py-1 text-xs font-semibold transition ${
                filtroCategoria === c.key
                  ? 'bg-slate-900 text-white'
                  : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
              }`}
            >
              {c.label}
              {c.key !== 'todos' && items.filter((r) => r.categoria === c.key).length > 0 && (
                <span className="ml-1 opacity-60">
                  ({items.filter((r) => r.categoria === c.key).length})
                </span>
              )}
            </button>
          ))}
        </div>

        <Table
          columns={campanhaCols}
          rows={campanhasFiltradas}
          emptyText="Nenhuma campanha com receita atribuída no período."
        />
      </section>
    </div>
  )
}

function DiretaDetalhadaView({ startDate, refreshKey }) {
  const reportYear = startDate ? Number(startDate.split('-')[0]) : new Date().getFullYear()
  const reportMonth = startDate ? Number(startDate.split('-')[1]) : new Date().getMonth() + 1
  const [abandonedCartCrmScope, setAbandonedCartCrmScope] = useState('all')

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

  const [crmFunnel, setCrmFunnel] = useState(null)
  const [crmFunnelLoading, setCrmFunnelLoading] = useState(false)
  const [crmFunnelError, setCrmFunnelError] = useState('')

  const abandonedCartScopeLabel = useMemo(() => {
    if (abandonedCartCrmScope === 'only_crm') return 'somente CRM'
    if (abandonedCartCrmScope === 'non_crm') return 'nao CRM'
    return 'todos os canais'
  }, [abandonedCartCrmScope])

  const crmResultsSummary = useMemo(() => {
    const purchaseRevenue = Number(ga4Report?.current_year?.purchaseRevenue || 0)
    const nonCrmRevenue = Number(abandonedCartNonCrmSummary?.purchaseRevenue || 0)
    return { purchaseRevenue, nonCrmRevenue, totalRevenue: purchaseRevenue + nonCrmRevenue }
  }, [abandonedCartNonCrmSummary?.purchaseRevenue, ga4Report?.current_year?.purchaseRevenue])

  const loadGa4MonthlyReport = useCallback(async () => {
    setGa4Loading(true)
    setGa4Error('')
    try {
      const response = await fetch(`/api/ga4/crm/monthly?year=${reportYear}&month=${reportMonth}`)
      let payload = null
      try { payload = await response.json() } catch (_) { payload = null }
      if (!response.ok) {
        const detail = payload?.detail || 'Nao foi possivel carregar resumo de resultados.'
        if (isGa4NoDataError(detail)) { setGa4Report(null); setGa4Error(''); return }
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
      try { payload = await response.json() } catch (_) { payload = null }
      if (!response.ok) {
        const detail = payload?.detail || 'Nao foi possivel carregar assists de CRM.'
        if (isGa4NoDataError(detail)) { setCrmAssists(null); setCrmAssistsError(''); return }
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
      try { payload = await response.json() } catch (_) { payload = null }
      if (!response.ok) {
        const detail = payload?.detail || 'Nao foi possivel carregar LTV de CRM.'
        if (isGa4NoDataError(detail)) { setCrmLtv(null); setCrmLtvError(''); return }
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
      const params = new URLSearchParams({ start: period.start, end: period.end, crm_scope: abandonedCartCrmScope })
      const response = await fetch(`/api/ga4/abandoned-cart-coupons?${params.toString()}`)
      let payload = null
      try { payload = await response.json() } catch (_) { payload = null }
      if (!response.ok) {
        const detail = payload?.detail || 'Nao foi possivel carregar pedidos com cupons de carrinho abandonado.'
        if (isGa4NoDataError(detail)) { setAbandonedCartCoupons(null); setAbandonedCartCouponsError(''); return }
        throw new Error(detail)
      }
      setAbandonedCartCoupons(payload)
    } catch (err) {
      setAbandonedCartCoupons(null)
      setAbandonedCartCouponsError(err instanceof Error ? err.message : 'Falha ao carregar pedidos com cupons de carrinho abandonado.')
    } finally {
      setAbandonedCartCouponsLoading(false)
    }
  }, [abandonedCartCrmScope, reportMonth, reportYear])

  const loadAbandonedCartNonCrmSummary = useCallback(async () => {
    setAbandonedCartNonCrmSummaryLoading(true)
    setAbandonedCartNonCrmSummaryError('')
    const period = getMonthDateRange(reportYear, reportMonth)
    try {
      const params = new URLSearchParams({ start: period.start, end: period.end, crm_scope: 'non_crm' })
      const response = await fetch(`/api/ga4/abandoned-cart-coupons?${params.toString()}`)
      let payload = null
      try { payload = await response.json() } catch (_) { payload = null }
      if (!response.ok) {
        const detail = payload?.detail || 'Nao foi possivel carregar o resumo de carrinho abandonado nao CRM.'
        if (isGa4NoDataError(detail)) { setAbandonedCartNonCrmSummary(null); setAbandonedCartNonCrmSummaryError(''); return }
        throw new Error(detail)
      }
      setAbandonedCartNonCrmSummary(payload)
    } catch (err) {
      setAbandonedCartNonCrmSummary(null)
      setAbandonedCartNonCrmSummaryError(err instanceof Error ? err.message : 'Falha ao carregar o resumo de carrinho abandonado nao CRM.')
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
        fetch(`/api/ga4/abandoned-cart-coupons?${new URLSearchParams({ start: period.start, end: period.end, crm_scope: 'non_crm' }).toString()}`),
      ])
      let ga4Payload = null
      let nonCrmPayload = null
      try { ga4Payload = await ga4Response.json() } catch (_) { ga4Payload = null }
      try { nonCrmPayload = await nonCrmResponse.json() } catch (_) { nonCrmPayload = null }
      if (!ga4Response.ok) {
        const detail = ga4Payload?.detail || 'Nao foi possivel carregar comparativo de resultados.'
        if (isGa4NoDataError(detail)) return { totalRevenue: 0, purchaseRevenue: 0, nonCrmRevenue: 0 }
        throw new Error(detail)
      }
      if (!nonCrmResponse.ok) {
        const detail = nonCrmPayload?.detail || 'Nao foi possivel carregar comparativo de carrinho abandonado nao CRM.'
        if (isGa4NoDataError(detail)) {
          return {
            totalRevenue: Number(ga4Payload?.current_year?.purchaseRevenue || 0),
            purchaseRevenue: Number(ga4Payload?.current_year?.purchaseRevenue || 0),
            nonCrmRevenue: 0,
          }
        }
        throw new Error(detail)
      }
      const purchaseRevenue = Number(ga4Payload?.current_year?.purchaseRevenue || 0)
      const nonCrmRevenue = Number(nonCrmPayload?.purchaseRevenue || 0)
      return { totalRevenue: purchaseRevenue + nonCrmRevenue, purchaseRevenue, nonCrmRevenue }
    }

    try {
      const [lastYearSummary, previousMonthSummary] = await Promise.all([
        loadComparisonSummary(sameMonthLastYear),
        loadComparisonSummary(previousMonth),
      ])
      setCrmResultsComparisons({ lastYearSameMonth: lastYearSummary, previousMonth: previousMonthSummary })
    } catch (err) {
      setCrmResultsComparisons(null)
      setCrmResultsComparisonsError(err instanceof Error ? err.message : 'Falha ao carregar comparativos do resultado geral CRM.')
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
      try { payload = await response.json() } catch (_) { payload = null }
      if (!response.ok) {
        const detail = payload?.detail || 'Nao foi possivel carregar funil de CRM.'
        if (isGa4NoDataError(detail)) { setCrmFunnel(null); setCrmFunnelError(''); return }
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
      loadCrmFunnel(),
    ])
  }, [
    loadGa4MonthlyReport,
    loadCrmAssists,
    loadCrmLtv,
    loadAbandonedCartCoupons,
    loadAbandonedCartNonCrmSummary,
    loadCrmResultsComparisons,
    loadCrmFunnel,
  ])

  useEffect(() => {
    if (refreshKey > 0) loadAllResults()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshKey])

  const metrics = [
    { key: 'sessions', label: 'Sessoes' },
    { key: 'totalUsers', label: 'Usuarios' },
    { key: 'transactions', label: 'Transacoes' },
    { key: 'purchaseRevenue', label: 'Receita de compras' },
  ]

  return (
    <section className="space-y-5">
      {ga4Error && (
        <section className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-rose-700">{ga4Error}</section>
      )}

      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft md:p-6">
        <h2 className="text-xl font-semibold text-slate-900">Resultado Geral - CRM</h2>
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
                  <p>Mesmo mes do ano passado: {formatCurrency(crmResultsComparisons.lastYearSameMonth?.totalRevenue)}</p>
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
              onChange={(e) => setAbandonedCartCrmScope(e.target.value)}
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
              { label: 'Compra', value: crmFunnel.purchase, rate: crmFunnel.conversion_rates?.purchase_rate },
            ].map((step) => (
              <article key={step.label} className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">{step.label}</h3>
                <p className="mt-2 text-2xl font-semibold text-slate-900">
                  {new Intl.NumberFormat('pt-BR').format(Number(step.value || 0))}
                </p>
                {step.rate !== null && step.rate !== undefined && (
                  <p className="mt-1 text-sm text-slate-600">Taxa: {(Number(step.rate) * 100).toFixed(2)}%</p>
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
