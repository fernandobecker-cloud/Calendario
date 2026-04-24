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

function PlaceholderView({ label }) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft">
      <p className="text-sm text-slate-500">{label} — em construção.</p>
    </section>
  )
}
