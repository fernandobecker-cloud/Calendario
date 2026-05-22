import { useState, useCallback, useMemo, useEffect } from 'react'
import {
  ResponsiveContainer, LineChart, Line,
  BarChart, Bar, LabelList,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, Cell,
} from 'recharts'

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


function shiftDateByYears(dateStr, years) {
  if (!dateStr || !/^\d{4}-\d{2}-\d{2}$/.test(dateStr)) return null
  const [y, m, d] = dateStr.split('-').map(Number)
  const base = new Date(y + years, m - 1, d)
  return base.toISOString().slice(0, 10)
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

function formatDateBR(isoDate) {
  if (!isoDate || !/^\d{4}-\d{2}-\d{2}$/.test(isoDate)) return ''
  const [y, m, d] = isoDate.split('-')
  return `${d}/${m}/${y}`
}

function dateDiffDays(start, end) {
  if (!start || !end) return null
  const s = new Date(start + 'T00:00:00')
  const e = new Date(end + 'T00:00:00')
  const diff = Math.round((e - s) / 86400000) + 1
  return diff > 0 ? diff : null
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
  { key: 'influenciada', label: 'Influenciada CRM', adminOnly: true },
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
  const totalCrm = totais.total_crm ?? 0

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft md:p-6">
      <h2 className="mb-4 text-sm font-semibold uppercase tracking-wide text-slate-500">
        Receita Emarsys
      </h2>

      <div className="mb-5 grid gap-4 sm:grid-cols-2">
        <div className="rounded-xl border border-violet-200 bg-violet-50 p-4">
          <p className="text-xs font-semibold uppercase tracking-wide text-violet-600">Total iPlace</p>
          <p className="mt-1 text-lg font-bold tabular-nums text-slate-900">{formatCurrency(totalCrm)}</p>
          <p className="mt-0.5 text-xs text-violet-600">todas as compras com CPF</p>
        </div>
        <div className="rounded-xl border border-slate-200 p-4">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Atribuída CRM</p>
          <p className="mt-1 text-lg font-bold tabular-nums text-slate-900">{formatCurrency(totais.reportado)}</p>
          <p className="mt-0.5 text-xs text-slate-400">
            {totalCrm > 0 ? `${((totais.reportado / totalCrm) * 100).toFixed(1)}% do total iPlace` : 'conforme Emarsys'}
          </p>
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

export default function ResultadoGeralPage({ currentRole }) {
  const defaults = getDefaultDates()
  const [activeView, setActiveView] = useState('executivo')
  const [startDate, setStartDate] = useState(defaults.start)
  const [endDate, setEndDate] = useState(defaults.end)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [filtroCategoria, setFiltroCategoria] = useState('todos')

  const [executivoData, setExecutivoData] = useState(null)
  const [atribuidaData, setAtribuidaData] = useState(null)
  const [atribuidaByChannel, setAtribuidaByChannel] = useState(null)
  const [diretaRefreshKey, setDiretaRefreshKey] = useState(0)
  const [influenciadaData, setInfluenciadaData] = useState(null)
  const [canalBreakdownData, setCanalBreakdownData] = useState(null)
  const [canalAtribuidaState, setCanalAtribuidaState] = useState({ data: null, loading: false, error: null })
  const [conversao7Dias, setConversao7Dias] = useState({ data: null, loading: false })

  const handleAtualizar = useCallback(async () => {
    if (!startDate) return
    setLoading(true)
    setError('')

    try {
      if (activeView === 'executivo') {
        const [year, month] = startDate.split('-').map(Number)
        const params = new URLSearchParams({ start: startDate, ...(endDate ? { end: endDate } : {}) })
        const dailyParams = new URLSearchParams({ start: startDate, ...(endDate ? { end: endDate } : {}) })
        const canalParams = new URLSearchParams({ start: startDate, end: endDate || startDate })

        // Canal e curva de conversão carregam em paralelo (podem ser lentos — não bloqueiam)
        setCanalAtribuidaState({ data: null, loading: true, error: null })
        fetch(`/api/open-data/emarsys/receita-atribuida-canal?${canalParams}`)
          .then(async res => {
            const json = await res.json().catch(() => null)
            if (!res.ok) {
              setCanalAtribuidaState({ data: null, loading: false, error: json?.detail || `Erro ${res.status}` })
            } else {
              setCanalAtribuidaState({ data: json, loading: false, error: null })
            }
          })
          .catch(err => setCanalAtribuidaState({ data: null, loading: false, error: String(err) }))

        setConversao7Dias({ data: null, loading: true })
        fetch(`/api/open-data/emarsys/conversao-7dias?${canalParams}`)
          .then(async res => {
            const json = await res.json().catch(() => null)
            setConversao7Dias({ data: res.ok ? json : null, loading: false })
          })
          .catch(() => setConversao7Dias({ data: null, loading: false }))

        const [atribuida, ga4, abandoned, daily] = await Promise.all([
          fetchJson(`/api/open-data/emarsys/monthly-revenue?${params}`),
          fetchJson(`/api/ga4/crm/monthly?year=${year}&month=${month}`),
          fetchJson(`/api/ga4/abandoned-cart-coupons?start=${startDate}&end=${endDate || startDate}&crm_scope=non_crm`),
          fetchJson(`/api/open-data/emarsys/daily-revenue?${dailyParams}`),
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
          dailyRevenue: daily.ok ? (daily.data?.items ?? []) : [],
        })
      } else if (activeView === 'atribuida') {
        const params = new URLSearchParams({ start: startDate, ...(endDate ? { end: endDate } : {}) })
        const [res, monthlyRes] = await Promise.all([
          fetchJson(`/api/open-data/emarsys/audit-receita-por-campanha?${params}`),
          fetchJson(`/api/open-data/emarsys/monthly-revenue?${params}`),
        ])
        if (!res.ok) {
          setError('Falha ao carregar dados de receita atribuída.')
          return
        }
        setAtribuidaData({
          items: res.data?.items ?? [],
          totais: res.data?.totais ?? null,
          resumoPorCategoria: res.data?.resumo_por_categoria ?? [],
        })
        setAtribuidaByChannel(monthlyRes.ok ? monthlyRes.data : null)
      } else if (activeView === 'direta') {
        setDiretaRefreshKey((k) => k + 1)
      } else if (activeView === 'influenciada') {
        const params = new URLSearchParams({ start: startDate, ...(endDate ? { end: endDate } : {}) })
        const [res, canalRes] = await Promise.all([
          fetchJson(`/api/open-data/emarsys/receita-influenciada?${params}`),
          fetchJson(`/api/open-data/base-vendas/canal-breakdown?${params}`).catch(() => ({ ok: false, data: null })),
        ])
        if (!res.ok) {
          setError('Falha ao carregar dados de receita influenciada.')
          return
        }
        setInfluenciadaData(res.data)
        setCanalBreakdownData(canalRes.ok ? canalRes.data : null)
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
            {VIEWS.filter((v) => !v.adminOnly || currentRole === 'admin').map((v) => (
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
            <ExecutivoView
              data={executivoData}
              loading={loading}
              canalAtribuida={canalAtribuidaState.data}
              canalLoading={canalAtribuidaState.loading}
              canalError={canalAtribuidaState.error}
              startDate={startDate}
              endDate={endDate}
              conversao7Dias={conversao7Dias}
            />
          )}
          {activeView === 'atribuida' && (
            <AtribuidaDetalhadaView
              data={atribuidaData}
              loading={loading}
              filtroCategoria={filtroCategoria}
              setFiltroCategoria={setFiltroCategoria}
              byChannel={atribuidaByChannel}
            />
          )}
          {activeView === 'direta' && (
            <DiretaDetalhadaView startDate={startDate} endDate={endDate} refreshKey={diretaRefreshKey} />
          )}
          {activeView === 'influenciada' && (
            <InfluenciadaView
              data={influenciadaData}
              loading={loading}
              canalBreakdown={canalBreakdownData}
              startDate={startDate}
              endDate={endDate}
            />
          )}
        </main>
      </div>
    </div>
  )
}

function fmtCurrencyShort(value) {
  const n = Number(value || 0)
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}MM`
  if (n >= 1_000) return `${Math.round(n / 1_000)}K`
  return `R$ ${Math.round(n)}`
}

function ChartTooltip({ active, payload, label }) {
  if (!active || !payload || payload.length === 0) return null
  // Garante ordem: Total iPlace primeiro, Receita Atribuída segundo
  const ordered = ['Total iPlace', 'Receita Atribuída']
    .map((key) => payload.find((p) => p.dataKey === key))
    .filter(Boolean)
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3 text-xs shadow-md">
      <p className="mb-1.5 font-semibold text-slate-700">{label}</p>
      {ordered.map((p) => (
        <p key={p.dataKey} style={{ color: p.color }} className="leading-5">
          {p.name}: {formatCurrency(p.value)}
        </p>
      ))}
    </div>
  )
}

function DailyRevenueChart({ items }) {
  if (!items || items.length === 0) return null

  const data = items.map((r) => ({
    dia: (() => {
      const m = String(r.dia || '').match(/^(\d{4})-(\d{2})-(\d{2})/)
      return m ? `${m[3]}/${m[2]}` : r.dia
    })(),
    'Total iPlace': r.total_iplace,
    'Receita Atribuída': r.receita_atribuida,
  }))

  const totalIplace = items.reduce((s, r) => s + Number(r.total_iplace || 0), 0)
  const totalAtribuida = items.reduce((s, r) => s + Number(r.receita_atribuida || 0), 0)
  const hasDots = data.length <= 31

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft md:p-6">
      <div className="mb-4 flex items-start justify-between gap-4">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
          Receita dia a dia
        </h2>
        <div className="grid grid-cols-2 gap-3">
          <div className="rounded-xl border border-indigo-100 bg-indigo-50 px-4 py-2">
            <p className="text-xs font-semibold uppercase tracking-wide text-indigo-500">Total iPlace</p>
            <p className="mt-0.5 text-base font-bold text-slate-900">{formatCurrency(totalIplace)}</p>
          </div>
          <div className="rounded-xl border border-emerald-100 bg-emerald-50 px-4 py-2">
            <p className="text-xs font-semibold uppercase tracking-wide text-emerald-600">Receita Atribuída</p>
            <p className="mt-0.5 text-base font-bold text-slate-900">{formatCurrency(totalAtribuida)}</p>
          </div>
        </div>
      </div>
      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={data} margin={{ top: 4, right: 16, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          <XAxis
            dataKey="dia"
            tick={{ fontSize: 11, fill: '#64748b' }}
            tickLine={false}
            axisLine={false}
          />
          <YAxis
            tickFormatter={fmtCurrencyShort}
            tick={{ fontSize: 11, fill: '#64748b' }}
            tickLine={false}
            axisLine={false}
            width={68}
          />
          <Tooltip content={<ChartTooltip />} />
          <Legend wrapperStyle={{ fontSize: 12, paddingTop: 12 }} />
          <Line
            type="monotone"
            dataKey="Total iPlace"
            stroke="#6366f1"
            strokeWidth={2}
            dot={hasDots}
            activeDot={{ r: 4 }}
          />
          <Line
            type="monotone"
            dataKey="Receita Atribuída"
            stroke="#10b981"
            strokeWidth={2}
            dot={hasDots}
            activeDot={{ r: 4 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </section>
  )
}

const CONVERSAO_COLORS = ['#6366f1','#818cf8','#a5b4fc','#c7d2fe','#e0e7ff','#eef2ff','#f5f3ff']

function ConversaoCurvaChart({ state }) {
  if (state.loading) {
    return (
      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft md:p-6">
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">Curva de Conversão — Janela de 7 Dias</h2>
        <p className="text-sm text-slate-400">Carregando…</p>
      </section>
    )
  }
  if (!state.data?.length) return null

  const total = state.data.reduce((s, d) => s + d.pedidos, 0)

  const dataWithPct = state.data.map((d) => ({
    ...d,
    pct: total > 0 ? ((d.pedidos / total) * 100).toFixed(0) + '%' : '—',
  }))

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft md:p-6">
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">Curva de Conversão — Janela de 7 Dias</h2>
      <ResponsiveContainer width="100%" height={240}>
        <BarChart data={dataWithPct} margin={{ top: 24, right: 16, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
          <XAxis dataKey="label" tick={{ fontSize: 12 }} axisLine={false} tickLine={false} />
          <YAxis hide />
          <Tooltip
            formatter={(v, name) => [`${((v / total) * 100).toFixed(0)}%`, name]}
            labelFormatter={(l) => l}
            contentStyle={{ fontSize: 12 }}
          />
          <Bar dataKey="pedidos" name="Pedidos" radius={[4, 4, 0, 0]}>
            {dataWithPct.map((_, i) => (
              <Cell key={i} fill={CONVERSAO_COLORS[i % CONVERSAO_COLORS.length]} />
            ))}
            <LabelList dataKey="pct" position="top" style={{ fontSize: 12, fontWeight: 600, fill: '#475569' }} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </section>
  )
}

function CanalAtribuidaCard({ data, startDate, endDate }) {
  const [expandedRegionals, setExpandedRegionals] = useState(new Set())
  const [showRegional, setShowRegional] = useState(false)
  const [exportLoading, setExportLoading] = useState(false)

  const exportSemCanal = async () => {
    if (!startDate) return
    setExportLoading(true)
    try {
      const params = new URLSearchParams({ start: startDate, end: endDate || startDate })
      const res = await fetch(`/api/open-data/emarsys/receita-atribuida-canal/sem-canal?${params}`)
      if (!res.ok) throw new Error(await res.text())
      const rows = await res.json()
      if (!rows.length) { alert('Nenhum pedido Pendente de Atribuição no período.'); return }
      const cols = ['order_id', 'contact_id', 'external_id', 'purchase_date', 'attributed_amount', 'channels', 'campaign_ids']
      const esc = v => { if (v == null) return ''; const s = String(v); return s.includes(',') || s.includes('"') || s.includes('\n') ? `"${s.replace(/"/g, '""')}"` : s }
      const csv = [cols.join(','), ...rows.map(r => cols.map(k => esc(r[k])).join(','))].join('\n')
      const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }))
      const a = document.createElement('a'); a.href = url; a.download = `sem-canal-${startDate}.csv`; a.click()
      URL.revokeObjectURL(url)
    } catch (e) { alert(`Erro: ${e.message}`) }
    finally { setExportLoading(false) }
  }

  const toggleRegional = r => setExpandedRegionals(prev => {
    const next = new Set(prev)
    next.has(r) ? next.delete(r) : next.add(r)
    return next
  })

  const totalReceita = (data.canal || []).reduce((s, c) => s + (c.receita || 0), 0)
  const maxCanalReceita = Math.max(...(data.canal || []).map(c => c.receita || 0), 1)

  const canais = (data.canal || []).map(c => ({
    ...c,
    pct: totalReceita > 0 ? (c.receita / totalReceita) * 100 : 0,
  }))

  // Filiais VAREJO com receita real
  const lojas = (data.filial || [])
    .filter(f => f.canal === 'VAREJO')
    .sort((a, b) => (b.receita || 0) - (a.receita || 0))

  // Agrupa lojas por regional usando receita real
  const regionaisMap = {}
  for (const loja of lojas) {
    const reg = loja.regional || 'Outros'
    if (!regionaisMap[reg]) regionaisMap[reg] = { regional: reg, linhas: 0, receita: 0, lojas: [] }
    regionaisMap[reg].linhas += loja.linhas || 0
    regionaisMap[reg].receita += loja.receita || 0
    regionaisMap[reg].lojas.push(loja)
  }
  const regionais = Object.values(regionaisMap).sort((a, b) => (b.receita || 0) - (a.receita || 0))
  const maxRegReceita = regionais[0]?.receita || 1

  const ChevronIcon = ({ open }) => (
    <svg className={`h-3.5 w-3.5 text-slate-400 transition-transform ${open ? 'rotate-180' : ''}`}
      viewBox="0 0 20 20" fill="currentColor">
      <path fillRule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clipRule="evenodd" />
    </svg>
  )

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft md:p-6">
      <div className="mb-1 flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
          Canal da Receita Atribuída
        </h2>
        <div className="flex items-center gap-3">
          <span className="text-xs text-slate-400">
            {(data.matched_rows || 0).toLocaleString('pt-BR')} pedidos cruzados · {(data.total_pedidos_crm || 0).toLocaleString('pt-BR')} atribuídos
          </span>
          {(data.total_pedidos_crm || 0) > (data.matched_rows || 0) && (
            <button onClick={exportSemCanal} disabled={exportLoading}
              className="rounded-md border border-slate-200 bg-white px-2 py-1 text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-50">
              {exportLoading ? '…' : `Exportar Pendente de Atribuição (${(data.total_pedidos_crm - data.matched_rows).toLocaleString('pt-BR')})`}
            </button>
          )}
        </div>
      </div>
      <p className="mb-4 text-xs text-slate-400">
        Receita real por canal — cruzamento direto por número de pedido (vendas_iplace)
      </p>

      {/* Canal summary */}
      <div className="grid gap-3 sm:grid-cols-2 mb-4">
        {canais.map(c => (
          <div key={c.canal} className="rounded-xl border border-slate-100 bg-slate-50 px-4 py-3">
            <div className="flex items-center justify-between">
              <span className="text-sm font-semibold text-slate-700">{c.canal}</span>
              <span className="text-sm font-bold text-slate-900">{formatCurrency(c.receita)}</span>
            </div>
            <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-slate-200">
              <div className="h-full rounded-full bg-indigo-500" style={{ width: `${(c.receita / maxCanalReceita) * 100}%` }} />
            </div>
            <p className="mt-1 text-xs text-slate-400">{c.pct.toFixed(1)}% · {c.linhas.toLocaleString('pt-BR')} pedidos</p>
          </div>
        ))}
      </div>

      {/* Abertura por regional / loja */}
      {regionais.length > 0 && (
        <>
          <button
            onClick={() => setShowRegional(v => !v)}
            className="flex items-center gap-2 text-sm font-medium text-indigo-600 hover:text-indigo-800 mb-3"
          >
            <svg className={`h-4 w-4 transition-transform ${showRegional ? 'rotate-180' : ''}`} viewBox="0 0 20 20" fill="currentColor">
              <path fillRule="evenodd" d="M5.22 8.22a.75.75 0 0 1 1.06 0L10 11.94l3.72-3.72a.75.75 0 1 1 1.06 1.06l-4.25 4.25a.75.75 0 0 1-1.06 0L5.22 9.28a.75.75 0 0 1 0-1.06z" clipRule="evenodd" />
            </svg>
            {showRegional ? 'Ocultar' : 'Ver'} abertura por regional ({regionais.length} regionais · {lojas.length} filiais)
          </button>
          {showRegional && (
            <div className="space-y-2">
              {regionais.map(reg => (
                <div key={reg.regional} className="rounded-lg border border-slate-200 bg-white overflow-hidden">
                  <button
                    onClick={() => toggleRegional(reg.regional)}
                    className="w-full flex items-center gap-3 px-4 py-3 hover:bg-slate-50 text-left"
                  >
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between mb-1.5">
                        <span className="text-sm font-semibold text-slate-700">{reg.regional}</span>
                        <div className="flex items-center gap-4">
                          <span className="text-xs text-slate-400">{reg.linhas.toLocaleString('pt-BR')} pedidos</span>
                          <span className="text-sm font-bold text-slate-900">{formatCurrency(reg.receita)}</span>
                          <ChevronIcon open={expandedRegionals.has(reg.regional)} />
                        </div>
                      </div>
                      <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
                        <div
                          className="h-full rounded-full bg-indigo-400"
                          style={{ width: `${(reg.receita / maxRegReceita) * 100}%` }}
                        />
                      </div>
                    </div>
                  </button>
                  {expandedRegionals.has(reg.regional) && (
                    <div className="border-t border-slate-100 divide-y divide-slate-50 bg-slate-50">
                      {reg.lojas.map(f => {
                        const maxLojaReceita = reg.lojas[0]?.receita || 1
                        return (
                          <div key={f.codigo_filial} className="flex items-center gap-3 px-6 py-2 text-xs">
                            <span className="w-16 shrink-0 font-semibold text-slate-600">
                              LJ{String(f.codigo_filial).padStart(3, '0')}
                            </span>
                            <span className="flex-1 truncate text-slate-500">{f.nome}</span>
                            <div className="w-24 flex-shrink-0">
                              <div className="h-1 overflow-hidden rounded-full bg-slate-200">
                                <div
                                  className="h-full rounded-full bg-indigo-300"
                                  style={{ width: `${((f.receita || 0) / maxLojaReceita) * 100}%` }}
                                />
                              </div>
                            </div>
                            <span className="w-10 text-right text-slate-400">{f.linhas}p</span>
                            <span className="w-28 text-right font-semibold text-slate-700">{formatCurrency(f.receita)}</span>
                          </div>
                        )
                      })}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </section>
  )
}

function ExecutivoView({ data, loading, canalAtribuida, canalLoading, canalError, startDate, endDate, conversao7Dias }) {
  if (loading) {
    return <p className="text-sm text-slate-500">Carregando...</p>
  }
  if (!data) {
    return <p className="text-sm text-slate-500">Selecione o período e clique em Atualizar.</p>
  }

  const { direta, dailyRevenue } = data

  return (
    <div className="flex flex-col gap-4">
      <DailyRevenueChart items={dailyRevenue} />

      {conversao7Dias && <ConversaoCurvaChart state={conversao7Dias} />}

      {/* Canal da Receita Atribuída */}
      {canalLoading ? (
        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft md:p-6">
          <p className="text-sm text-slate-400">Carregando canal de receita atribuída…</p>
        </section>
      ) : canalError ? (
        <section className="rounded-2xl border border-rose-200 bg-rose-50 p-5">
          <p className="text-sm text-rose-700">{canalError}</p>
        </section>
      ) : canalAtribuida?.canal?.length > 0 ? (
        <CanalAtribuidaCard data={canalAtribuida} startDate={startDate} endDate={endDate} />
      ) : null}

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

function AtribuidaDetalhadaView({ data, loading, filtroCategoria, setFiltroCategoria, byChannel }) {
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

  const monthRow = byChannel?.items?.[0] ?? null
  const channels = byChannel?.by_channel ?? []

  return (
    <div className="flex flex-col gap-4">
      {byChannel && (
        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft md:p-6">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
            Receita Atribuída
          </h2>
          <p className="text-4xl font-bold text-slate-900">
            {formatCurrency(byChannel.total_receita_atribuida)}
          </p>
          {monthRow && (
            <p className="mt-1 text-sm text-slate-500">
              {monthRow.pedidos_atribuidos.toLocaleString('pt-BR')} pedidos
              {' · '}
              {monthRow.compradores_unicos.toLocaleString('pt-BR')} compradores únicos
            </p>
          )}
          {channels.length > 0 && (
            <div className="mt-4 grid gap-3 sm:grid-cols-3">
              {channels.map((ch) => {
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
        </section>
      )}

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

function DiretaDetalhadaView({ startDate, endDate, refreshKey }) {
  const reportYear = startDate ? Number(startDate.split('-')[0]) : new Date().getFullYear()
  const reportMonth = startDate ? Number(startDate.split('-')[1]) : new Date().getMonth() + 1
  const [abandonedCartCrmScope, setAbandonedCartCrmScope] = useState('all')

  const [compStart, setCompStart] = useState('')
  const [compEnd, setCompEnd] = useState('')
  const [compData, setCompData] = useState(null)
  const [compLoading, setCompLoading] = useState(false)
  const [compError, setCompError] = useState('')

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
        const raw = payload?.detail
        const detail = typeof raw === 'string' ? raw : 'Nao foi possivel carregar resumo de resultados.'
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
    const period = (startDate && endDate) ? { start: startDate, end: endDate } : getMonthDateRange(reportYear, reportMonth)
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
  }, [endDate, reportMonth, reportYear, startDate])

  const loadCrmLtv = useCallback(async () => {
    setCrmLtvLoading(true)
    setCrmLtvError('')
    const period = (startDate && endDate) ? { start: startDate, end: endDate } : getMonthDateRange(reportYear, reportMonth)
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
  }, [endDate, reportMonth, reportYear, startDate])

  const loadAbandonedCartCoupons = useCallback(async () => {
    setAbandonedCartCouponsLoading(true)
    setAbandonedCartCouponsError('')
    const period = (startDate && endDate) ? { start: startDate, end: endDate } : getMonthDateRange(reportYear, reportMonth)
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
  }, [abandonedCartCrmScope, endDate, reportMonth, reportYear, startDate])

  const loadAbandonedCartNonCrmSummary = useCallback(async () => {
    setAbandonedCartNonCrmSummaryLoading(true)
    setAbandonedCartNonCrmSummaryError('')
    const period = (startDate && endDate) ? { start: startDate, end: endDate } : getMonthDateRange(reportYear, reportMonth)
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
  }, [endDate, reportMonth, reportYear, startDate])

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

  const loadComparison = useCallback(async (start, end) => {
    if (!start || !end) return
    setCompLoading(true)
    setCompError('')
    setCompData(null)
    try {
      const [ga4Res, nonCrmRes] = await Promise.all([
        fetch(`/api/ga4/crm/range?start=${start}&end=${end}`),
        fetch(`/api/ga4/abandoned-cart-coupons?${new URLSearchParams({ start, end, crm_scope: 'non_crm' }).toString()}`),
      ])
      let ga4Payload = null
      let nonCrmPayload = null
      try { ga4Payload = await ga4Res.json() } catch (_) { ga4Payload = null }
      try { nonCrmPayload = await nonCrmRes.json() } catch (_) { nonCrmPayload = null }
      const purchaseRevenue = ga4Res.ok ? Number(ga4Payload?.purchaseRevenue || 0) : 0
      const nonCrmRevenue = nonCrmRes.ok ? Number(nonCrmPayload?.purchaseRevenue || 0) : 0
      setCompData({ purchaseRevenue, nonCrmRevenue, totalRevenue: purchaseRevenue + nonCrmRevenue })
    } catch (err) {
      setCompError(err instanceof Error ? err.message : 'Falha ao carregar comparativo.')
    } finally {
      setCompLoading(false)
    }
  }, [])

  // Auto-preenche datas de comparação com YoY quando o período principal muda
  useEffect(() => {
    if (!startDate || !endDate) return
    setCompStart(shiftDateByYears(startDate, -1))
    setCompEnd(shiftDateByYears(endDate, -1))
    setCompData(null)
  }, [startDate, endDate])

  const loadAllResults = useCallback(async () => {
    await Promise.all([
      loadGa4MonthlyReport(),
      loadCrmAssists(),
      loadCrmLtv(),
      loadAbandonedCartCoupons(),
      loadAbandonedCartNonCrmSummary(),
      loadCrmFunnel(),
    ])
  }, [
    loadGa4MonthlyReport,
    loadCrmAssists,
    loadCrmLtv,
    loadAbandonedCartCoupons,
    loadAbandonedCartNonCrmSummary,
    loadCrmFunnel,
  ])

  useEffect(() => {
    if (refreshKey > 0) loadAllResults()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshKey]) // eslint-disable-line react-hooks/exhaustive-deps

  if (refreshKey === 0) {
    return <p className="text-sm text-slate-500">Selecione o período e clique em Atualizar.</p>
  }

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

      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-soft">
        {/* Header */}
        <div>
          <h2 className="text-xl font-semibold text-slate-900">Receita GA4</h2>
          {startDate && endDate && (
            <p className="mt-0.5 text-sm text-slate-500">
              {formatDateBR(startDate)} → {formatDateBR(endDate)}
              {dateDiffDays(startDate, endDate) && (
                <span className="ml-2 text-slate-400">· {dateDiffDays(startDate, endDate)} dias</span>
              )}
            </p>
          )}
        </div>

        {/* Erros */}
        {abandonedCartNonCrmSummaryError && (
          <p className="mt-3 text-sm text-rose-700">{abandonedCartNonCrmSummaryError}</p>
        )}

        {/* Valor principal */}
        {ga4Loading || abandonedCartNonCrmSummaryLoading ? (
          <p className="mt-5 text-sm text-slate-500">Calculando receita...</p>
        ) : ga4Error ? null : (
          <>
            <p className="mt-5 text-4xl font-bold tracking-tight text-slate-900">
              {formatCurrency(crmResultsSummary.totalRevenue)}
            </p>
            <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-xs text-slate-500">
              <span>Compras GA4: {formatCurrency(crmResultsSummary.purchaseRevenue)}</span>
              <span>Carrinho nao-CRM: {formatCurrency(crmResultsSummary.nonCrmRevenue)}</span>
            </div>
          </>
        )}

        <hr className="my-5 border-slate-100" />

        {/* Comparação */}
        <div>
          <p className="mb-2 text-sm font-medium text-slate-600">Comparar com</p>
          <div className="flex flex-wrap items-center gap-2">
            <input
              type="date" value={compStart}
              onChange={e => { setCompStart(e.target.value); setCompData(null) }}
              className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm text-slate-700 focus:outline-none focus:ring-2 focus:ring-slate-300"
            />
            <span className="text-slate-400">→</span>
            <input
              type="date" value={compEnd}
              onChange={e => { setCompEnd(e.target.value); setCompData(null) }}
              className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm text-slate-700 focus:outline-none focus:ring-2 focus:ring-slate-300"
            />
            <button
              onClick={() => loadComparison(compStart, compEnd)}
              disabled={!compStart || !compEnd || compLoading}
              className="rounded-lg bg-slate-900 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-40 hover:bg-slate-700 transition-colors"
            >
              {compLoading ? 'Carregando...' : 'Comparar'}
            </button>
          </div>

          {compError && <p className="mt-2 text-sm text-rose-600">{compError}</p>}

          {compData && (() => {
            const base = crmResultsSummary.totalRevenue
            const comp = compData.totalRevenue
            const pct = comp ? ((base - comp) / comp) * 100 : null
            const diff = base - comp
            const isUp = diff >= 0
            const compDays = dateDiffDays(compStart, compEnd)
            return (
              <div className="mt-4 rounded-xl border border-slate-100 bg-slate-50 p-4">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">período comparado</p>
                  <p className="text-xs text-slate-400">
                    {formatDateBR(compStart)} → {formatDateBR(compEnd)}
                    {compDays && <span className="ml-1.5">· {compDays} dias</span>}
                  </p>
                </div>
                <p className="mt-2 text-xl font-semibold text-slate-700">{formatCurrency(comp)}</p>
                <div className="mt-1 text-xs text-slate-400">
                  <span>Compras GA4: {formatCurrency(compData.purchaseRevenue)}</span>
                  <span className="ml-4">Carrinho não-CRM: {formatCurrency(compData.nonCrmRevenue)}</span>
                </div>
                <div className="mt-3 flex flex-wrap items-center gap-3">
                  <span className={`text-lg font-bold ${isUp ? 'text-emerald-600' : 'text-rose-600'}`}>
                    {isUp ? '▲' : '▼'} {pct != null ? `${Math.abs(pct).toFixed(2)}%` : '—'}
                  </span>
                  <span className={`text-sm font-medium ${isUp ? 'text-emerald-600' : 'text-rose-600'}`}>
                    {isUp ? '+' : ''}{formatCurrency(diff)}
                  </span>
                </div>
              </div>
            )
          })()}
        </div>
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

function downloadCsv(rows, filename) {
  if (!rows.length) return
  const headers = Object.keys(rows[0])
  const lines = [
    headers.join(';'),
    ...rows.map(r => headers.map(h => {
      const v = r[h] ?? ''
      return String(v).includes(';') || String(v).includes('"') ? `"${String(v).replace(/"/g, '""')}"` : String(v)
    }).join(';')),
  ]
  const blob = new Blob(['﻿' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

function InfluenciadaView({ data, loading, canalBreakdown, startDate, endDate }) {
  const [expandedCanal, setExpandedCanal] = useState(null)
  const [gapDownloading, setGapDownloading] = useState(false)
  const [gapDownloadError, setGapDownloadError] = useState('')
  const [atribuidaDownloading, setAtribuidaDownloading] = useState(false)
  const [atribuidaDownloadError, setAtribuidaDownloadError] = useState('')

  const handleDownloadAtribuida = async () => {
    setAtribuidaDownloading(true)
    setAtribuidaDownloadError('')
    try {
      const params = new URLSearchParams({ ...(startDate ? { start: startDate } : {}), ...(endDate ? { end: endDate } : {}) })
      const res = await fetch(`/api/open-data/emarsys/atribuida-orders?${params}`)
      let payload = null
      try { payload = await res.json() } catch (_) {}
      if (!res.ok) throw new Error(payload?.detail || `Erro ${res.status} ao buscar pedidos atribuídos.`)
      if (!payload) throw new Error('Resposta vazia do servidor.')
      const rows = (payload.items || []).map(item => ({
        order_id: item.order_id,
        contact_id: item.contact_id,
        external_id: item.external_id,
        data_compra: item.purchase_date || '',
        valor_pedido: String(item.valor_pedido).replace('.', ','),
        valor_atribuido: String(item.valor_atribuido).replace('.', ','),
        campanha: item.nome_campanha || '',
        tipo_toque: item.tipo_toque || '',
        data_toque: item.data_toque || '',
      }))
      downloadCsv(rows, `atribuida_pedidos_${startDate || 'periodo'}_${endDate || ''}.csv`)
    } catch (err) {
      setAtribuidaDownloadError(err instanceof Error ? err.message : 'Erro ao baixar.')
    } finally {
      setAtribuidaDownloading(false)
    }
  }

  const handleDownloadGap = async () => {
    setGapDownloading(true)
    setGapDownloadError('')
    try {
      const params = new URLSearchParams({ ...(startDate ? { start: startDate } : {}), ...(endDate ? { end: endDate } : {}) })
      const res = await fetch(`/api/open-data/emarsys/gap-orders?${params}`)
      let payload = null
      try { payload = await res.json() } catch (_) {}
      if (!res.ok) throw new Error(payload?.detail || `Erro ${res.status} ao buscar pedidos do gap.`)
      if (!payload) throw new Error('Resposta vazia do servidor.')
      const rows = (payload.items || []).map(item => ({
        order_id: item.order_id,
        contact_id: item.contact_id,
        external_id: item.external_id,
        data_compra: item.purchase_date || '',
        valor_pedido: String(item.valor_pedido).replace('.', ','),
        campanha: item.nome_campanha || '',
        tipo_toque: item.tipo_toque || '',
        data_toque: item.data_toque || '',
      }))
      downloadCsv(rows, `gap_pedidos_${startDate || 'periodo'}_${endDate || ''}.csv`)
    } catch (err) {
      setGapDownloadError(err instanceof Error ? err.message : 'Erro ao baixar.')
    } finally {
      setGapDownloading(false)
    }
  }

  if (loading) return <p className="text-sm text-slate-500">Carregando...</p>
  if (!data) return <p className="text-sm text-slate-500">Selecione o período e clique em Atualizar.</p>

  const total = data.total_receita || 0
  const atribuidaFullPct = total > 0 ? (data.atribuida_full_receita / total) * 100 : 0
  const gapPct = total > 0 ? (data.gap_receita / total) * 100 : 0
  const influenciadaPct = total > 0 ? (data.influenciada_receita / total) * 100 : 0
  const transacionalPct = total > 0 ? (data.transacional_receita / total) * 100 : 0
  const receitaFinalPct = total > 0 ? (data.receita_final / total) * 100 : 0

  const hasRevenue = canalBreakdown?.revenue_column != null
  const canalList = canalBreakdown?.canal ?? []
  const filialList = canalBreakdown?.filial ?? []
  const totalCanalReceita = canalList.reduce((s, c) => s + (c.receita || 0), 0)
  const totalCanalLinhas = canalList.reduce((s, c) => s + (c.linhas || 0), 0)

  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="rounded-xl border border-violet-200 bg-violet-50 p-5">
          <p className="text-xs font-semibold uppercase tracking-wide text-violet-600">Total iPlace</p>
          <p className="mt-2 text-3xl font-bold text-slate-900">{formatCurrency(data.total_receita)}</p>
          <p className="mt-1 text-xs text-violet-600">
            {(data.total_pedidos ?? 0).toLocaleString('pt-BR')} pedidos no período
          </p>
        </div>

        <div className="rounded-xl border border-blue-200 bg-blue-50 p-5">
          <div className="flex items-start justify-between gap-2">
            <p className="text-xs font-semibold uppercase tracking-wide text-blue-700">Atribuída pelo Emarsys</p>
            <button
              onClick={handleDownloadAtribuida}
              disabled={atribuidaDownloading}
              title="Baixar pedidos atribuídos (CSV)"
              className="flex-shrink-0 flex items-center gap-1 rounded-md border border-blue-300 bg-white px-2 py-1 text-xs font-medium text-blue-700 hover:bg-blue-100 disabled:opacity-50"
            >
              {atribuidaDownloading ? (
                <svg className="h-3.5 w-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
                </svg>
              ) : (
                <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v2a2 2 0 002 2h12a2 2 0 002-2v-2M7 10l5 5 5-5M12 15V3" />
                </svg>
              )}
              <span>{atribuidaDownloading ? 'Baixando…' : 'Baixar'}</span>
            </button>
          </div>
          <p className="mt-2 text-3xl font-bold text-slate-900">{formatCurrency(data.atribuida_receita)}</p>
          <p className="mt-1 text-xs text-blue-600">
            {atribuidaFullPct.toFixed(1)}% do total · {(data.atribuida_pedidos ?? 0).toLocaleString('pt-BR')} pedidos
          </p>
          {atribuidaDownloadError && <p className="mt-1 text-xs text-rose-600">{atribuidaDownloadError}</p>}
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-5">
          <p className="text-xs font-semibold uppercase tracking-wide text-emerald-700">Receita de Pedidos</p>
          <p className="mt-2 text-2xl font-bold text-slate-900">{formatCurrency(data.influenciada_receita)}</p>
          <p className="mt-1 text-xs text-emerald-700">
            {influenciadaPct.toFixed(1)}% do total · {(data.influenciada_pedidos ?? 0).toLocaleString('pt-BR')} pedidos
          </p>
        </div>

        <div className="rounded-xl border border-amber-200 bg-amber-50 p-5">
          <div className="flex items-start justify-between gap-2">
            <p className="text-xs font-semibold uppercase tracking-wide text-amber-700">Gap de Atribuição CRM</p>
            <button
              onClick={handleDownloadGap}
              disabled={gapDownloading}
              title="Baixar pedidos do Gap (CSV)"
              className="flex-shrink-0 flex items-center gap-1 rounded-md border border-amber-300 bg-white px-2 py-1 text-xs font-medium text-amber-700 hover:bg-amber-100 disabled:opacity-50"
            >
              {gapDownloading ? (
                <svg className="h-3.5 w-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
                </svg>
              ) : (
                <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v2a2 2 0 002 2h12a2 2 0 002-2v-2M7 10l5 5 5-5M12 15V3" />
                </svg>
              )}
              <span>{gapDownloading ? 'Baixando…' : 'Baixar'}</span>
            </button>
          </div>
          <p className="mt-2 text-2xl font-bold text-slate-900">{formatCurrency(data.gap_receita)}</p>
          <p className="mt-1 text-xs text-amber-600">
            {gapPct.toFixed(1)}% do total · {(data.gap_pedidos ?? 0).toLocaleString('pt-BR')} pedidos sem atribuição com toque marketing
          </p>
          {gapDownloadError && <p className="mt-1 text-xs text-rose-600">{gapDownloadError}</p>}
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <div className="rounded-xl border border-rose-200 bg-rose-50 p-5">
          <p className="text-xs font-semibold uppercase tracking-wide text-rose-700">Receita Transacional</p>
          <p className="mt-2 text-2xl font-bold text-slate-900">{formatCurrency(data.transacional_receita)}</p>
          <p className="mt-1 text-xs text-rose-600">
            {transacionalPct.toFixed(1)}% do total · {(data.transacional_pedidos ?? 0).toLocaleString('pt-BR')} pedidos sem interação de marketing
          </p>
        </div>

        <div className="rounded-xl border border-teal-200 bg-teal-50 p-5">
          <p className="text-xs font-semibold uppercase tracking-wide text-teal-700">Receita Final</p>
          <p className="mt-2 text-2xl font-bold text-slate-900">{formatCurrency(data.receita_final)}</p>
          <p className="mt-1 text-xs text-teal-600">
            {receitaFinalPct.toFixed(1)}% do total · Pedidos total + Gap − Transacional
          </p>
        </div>
      </div>

      {canalList.length > 0 && (
        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Receita por Canal
              {!hasRevenue && <span className="ml-1 font-normal normal-case text-slate-400">(registros)</span>}
            </h3>
            <span className="text-xs text-slate-400">Base Vendas · {(canalBreakdown?.period_rows ?? 0).toLocaleString('pt-BR')} registros no período</span>
          </div>

          <div className="divide-y divide-slate-100">
            {canalList.map(item => {
              const pct = hasRevenue
                ? (totalCanalReceita > 0 ? (item.receita / totalCanalReceita) * 100 : 0)
                : (totalCanalLinhas > 0 ? (item.linhas / totalCanalLinhas) * 100 : 0)
              const subItems = filialList.filter(f => f.canal === item.canal)
              const isExpanded = expandedCanal === item.canal

              return (
                <div key={item.canal}>
                  <button
                    className="flex w-full items-center gap-3 py-2.5 text-left hover:bg-slate-50"
                    onClick={() => setExpandedCanal(isExpanded ? null : item.canal)}
                  >
                    <span className="w-4 text-slate-400 text-xs">{subItems.length > 0 ? (isExpanded ? '▾' : '▸') : ' '}</span>
                    <span className="flex-1 text-sm font-medium text-slate-700">{item.canal}</span>
                    <span className="text-xs text-slate-500">{item.linhas.toLocaleString('pt-BR')} reg.</span>
                    <span className="w-28 text-right text-sm font-semibold text-slate-800">
                      {hasRevenue ? formatCurrency(item.receita) : `${item.linhas.toLocaleString('pt-BR')}`}
                    </span>
                    <span className="w-12 text-right text-xs text-slate-400">{pct.toFixed(1)}%</span>
                  </button>

                  {isExpanded && subItems.length > 0 && (
                    <div className="mb-1 ml-7 rounded-lg bg-slate-50 px-3 py-1">
                      <table className="w-full text-xs">
                        <thead>
                          <tr className="text-slate-400">
                            <th className="py-1 text-left font-normal">Filial</th>
                            <th className="py-1 text-right font-normal">Registros</th>
                            {hasRevenue && <th className="py-1 text-right font-normal">Receita</th>}
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-100">
                          {subItems.map(f => (
                            <tr key={f.codigo_filial} className="text-slate-600">
                              <td className="py-1">{f.codigo_filial || '—'}</td>
                              <td className="py-1 text-right">{f.linhas.toLocaleString('pt-BR')}</td>
                              {hasRevenue && <td className="py-1 text-right font-medium">{formatCurrency(f.receita)}</td>}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </section>
      )}

      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft">
        <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-500">
          Composição da Receita de Pedidos
        </h3>
        <div className="flex h-4 overflow-hidden rounded-full bg-slate-100">
          <div
            className="h-full bg-blue-400 transition-all"
            style={{ width: `${atribuidaFullPct}%` }}
            title={`Atribuída (pedidos completos): ${atribuidaFullPct.toFixed(1)}%`}
          />
          <div
            className="h-full bg-amber-400 transition-all"
            style={{ width: `${gapPct}%` }}
            title={`Gap: ${gapPct.toFixed(1)}%`}
          />
        </div>
        <div className="mt-3 flex flex-wrap gap-5 text-xs text-slate-600">
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-2.5 w-2.5 rounded-sm bg-blue-400" />
            Atribuída (pedidos): {atribuidaFullPct.toFixed(1)}% — {formatCurrency(data.atribuida_full_receita)}
          </span>
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-2.5 w-2.5 rounded-sm bg-amber-400" />
            Gap: {gapPct.toFixed(1)}% — {formatCurrency(data.gap_receita)}
          </span>
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-2.5 w-2.5 rounded-sm bg-slate-200" />
            Não influenciada: {(100 - influenciadaPct).toFixed(1)}% — {formatCurrency(total - data.influenciada_receita)}
          </span>
        </div>
      </section>
    </div>
  )
}
