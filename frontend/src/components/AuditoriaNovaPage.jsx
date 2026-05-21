import { useState, useMemo, useCallback } from 'react'
import {
  BarChart, Bar,
  LineChart, Line,
  PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from 'recharts'

// ---------------------------------------------------------------------------
// Constantes
// ---------------------------------------------------------------------------

const STATUS_CONFIG = {
  atribuicao_parcial: { label: 'Atribuição Parcial', bg: 'bg-blue-100',   text: 'text-blue-700',   color: '#3B82F6' },
  atribuicao_total:   { label: 'Atribuição Total',   bg: 'bg-green-100',  text: 'text-green-700',  color: '#22C55E' },
  sobreatribuido:     { label: 'Sobreatribuído',      bg: 'bg-red-100',    text: 'text-red-700',    color: '#EF4444' },
  sem_vinculo:        { label: 'Sem Vínculo',          bg: 'bg-amber-100',  text: 'text-amber-700',  color: '#F59E0B' },
  sem_purchase:       { label: 'Sem Purchase',         bg: 'bg-slate-100',  text: 'text-slate-600',  color: '#94A3B8' },
}

const PAGE_SIZE = 100

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatCurrency(v) {
  if (v == null || isNaN(Number(v))) return '-'
  return new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(Number(v))
}

function fmtPct(v) {
  if (v == null || isNaN(Number(v))) return '-'
  return `${Number(v).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}%`
}

function fmtDate(v) {
  if (!v) return '-'
  const parts = String(v).split('-')
  if (parts.length !== 3) return v
  return `${parts[2]}/${parts[1]}/${parts[0]}`
}

function fmtDateTick(v) {
  if (!v) return ''
  const parts = String(v).split('-')
  if (parts.length !== 3) return v
  return `${parts[2]}/${parts[1]}`
}

// ---------------------------------------------------------------------------
// StatusBadge
// ---------------------------------------------------------------------------

function StatusBadge({ status }) {
  const cfg = STATUS_CONFIG[status] || { label: status, bg: 'bg-slate-100', text: 'text-slate-600' }
  return (
    <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-semibold ${cfg.bg} ${cfg.text}`}>
      {cfg.label}
    </span>
  )
}

// ---------------------------------------------------------------------------
// MetricCard
// ---------------------------------------------------------------------------

function MetricCard({ label, value, sub, highlight, badge }) {
  return (
    <div className={`rounded-xl border p-3 ${highlight ? 'border-amber-200 bg-amber-50' : 'border-slate-200 bg-slate-50'}`}>
      <p className="text-xs text-slate-500">{label}</p>
      <p className={`mt-0.5 text-lg font-bold ${highlight ? 'text-amber-800' : 'text-slate-900'}`}>{value}</p>
      {sub && <p className="text-xs text-slate-400">{sub}</p>}
      {badge != null && badge > 0 && (
        <span className="mt-1 inline-block rounded-full bg-red-100 px-2 py-0.5 text-xs font-semibold text-red-700">
          {badge}
        </span>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Export CSV helper
// ---------------------------------------------------------------------------

function exportCsv(items, startDate, endDate) {
  if (!items || !items.length) return
  const cols = [
    { key: 'order_id',         label: 'Pedido' },
    { key: 'purchase_date',    label: 'Data Compra' },
    { key: 'contact_id',       label: 'ID Contato' },
    { key: 'valor_real',       label: 'Valor Real (R$)' },
    { key: 'valor_atribuido',  label: 'Valor Atribuído (R$)' },
    { key: 'delta_valor',      label: 'Delta Valor (R$)' },
    { key: 'delta_pct',        label: 'Delta (%)' },
    { key: 'canais',           label: 'Canais' },
    { key: 'campaign_ids',     label: 'Campaign IDs' },
    { key: 'qtd_treatments',   label: 'Qtd Treatments' },
    { key: 'status',           label: 'Status' },
    { key: 'sem_vinculo',      label: 'Sem Vínculo' },
  ]
  const esc = (v) => {
    if (v == null) return ''
    const s = String(v)
    return s.includes(',') || s.includes('"') || s.includes('\n') ? `"${s.replace(/"/g, '""')}"` : s
  }
  const csv = '﻿' + [
    cols.map((c) => c.label).join(','),
    ...items.map((r) => cols.map((c) => esc(r[c.key])).join(',')),
  ].join('\n')
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `auditoria-receita-crm-${startDate || 'dados'}-${endDate || ''}.csv`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function AuditoriaNovaPage({ startDate, endDate }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  // Filtros
  const [filtroStatus, setFiltroStatus] = useState([])
  const [filtroCanal, setFiltroCanal] = useState('')
  const [filtroDeltatMin, setFiltroDeltatMin] = useState(0)
  const [pagina, setPagina] = useState(0)

  // ---- Fetch ----

  const handleCarregar = useCallback(async () => {
    setLoading(true)
    setError('')
    setData(null)
    setPagina(0)
    try {
      const params = new URLSearchParams()
      if (startDate) params.set('start', startDate)
      if (endDate) params.set('end', endDate)
      const res = await fetch(`/api/open-data/emarsys/auditoria-receita-crm?${params}`)
      const json = await res.json().catch(() => null)
      if (!res.ok) {
        setError(json?.detail || 'Erro ao carregar dados.')
        setLoading(false)
        return
      }
      setData(json)
    } catch (e) {
      setError(e.message || 'Erro ao carregar dados.')
    } finally {
      setLoading(false)
    }
  }, [startDate, endDate])

  // ---- Filtros derivados ----

  const allStatuses = useMemo(() => Object.keys(STATUS_CONFIG), [])

  const itemsFiltrados = useMemo(() => {
    if (!data?.items) return []
    return data.items.filter((it) => {
      if (filtroStatus.length > 0 && !filtroStatus.includes(it.status)) return false
      if (filtroCanal.trim()) {
        const canal = (it.canais || '').toUpperCase()
        if (!canal.includes(filtroCanal.trim().toUpperCase())) return false
      }
      if (filtroDeltatMin > 0) {
        const dp = it.delta_pct == null ? 0 : Math.abs(Number(it.delta_pct))
        if (dp < filtroDeltatMin) return false
      }
      return true
    })
  }, [data, filtroStatus, filtroCanal, filtroDeltatMin])

  const itensPagina = useMemo(() => {
    const start = pagina * PAGE_SIZE
    return itemsFiltrados.slice(start, start + PAGE_SIZE)
  }, [itemsFiltrados, pagina])

  const totalPaginas = Math.max(1, Math.ceil(itemsFiltrados.length / PAGE_SIZE))

  // ---- Toggle status ----

  const toggleStatus = (s) => {
    setPagina(0)
    setFiltroStatus((prev) =>
      prev.includes(s) ? prev.filter((x) => x !== s) : [...prev, s],
    )
  }

  const limparFiltros = () => {
    setFiltroStatus([])
    setFiltroCanal('')
    setFiltroDeltatMin(0)
    setPagina(0)
  }

  // ---- Render ----

  const totals = data?.totals
  const byStatus = data?.by_status || []
  const byCanal = data?.by_canal || []
  const byDay = data?.by_day || []

  return (
    <div className="space-y-6">

      {/* Botão carregar */}
      <div className="flex flex-wrap items-center gap-3">
        <button
          onClick={handleCarregar}
          disabled={loading}
          className="rounded-lg bg-indigo-600 px-5 py-2 text-sm font-semibold text-white transition hover:bg-indigo-700 disabled:opacity-50"
        >
          {loading ? 'Carregando...' : data ? 'Recarregar' : 'Carregar auditoria'}
        </button>
        {data && (
          <span className="text-xs text-slate-400">
            Período: {fmtDate(data.start_date)} – {fmtDate(data.end_date)} · {(data.items || []).length.toLocaleString('pt-BR')} registros
          </span>
        )}
      </div>

      {/* Erro */}
      {error && (
        <p className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</p>
      )}

      {/* Estado vazio */}
      {!data && !loading && !error && (
        <p className="text-sm text-slate-500">Clique em "Carregar auditoria" para consultar os dados do período.</p>
      )}

      {data && (
        <>
          {/* ---- Cards de métricas ---- */}
          <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft">
            <h2 className="mb-4 text-sm font-semibold uppercase tracking-wide text-slate-500">Resumo</h2>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
              <MetricCard label="Total pedidos CRM" value={(totals?.total_orders || 0).toLocaleString('pt-BR')} />
              <MetricCard label="Soma valor real" value={formatCurrency(totals?.soma_valor_real)} sub="si_purchases" />
              <MetricCard label="Soma valor atribuído" value={formatCurrency(totals?.soma_valor_atribuido)} sub="revenue_attribution" />
              <MetricCard label="Delta total (R$)" value={formatCurrency(totals?.delta_total)} highlight />
              <MetricCard label="Delta médio (%)" value={fmtPct(totals?.delta_medio_pct)} />
              <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
                <p className="text-xs text-slate-500">Alertas</p>
                <div className="mt-1 flex flex-col gap-1">
                  {(totals?.count_sobreatribuidos || 0) > 0 && (
                    <span className="inline-block rounded-full bg-red-100 px-2 py-0.5 text-xs font-semibold text-red-700">
                      {totals.count_sobreatribuidos} sobreatribuídos
                    </span>
                  )}
                  {(totals?.count_sem_vinculo || 0) > 0 && (
                    <span className="inline-block rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-700">
                      {totals.count_sem_vinculo} sem vínculo
                    </span>
                  )}
                  {(totals?.count_sem_purchase || 0) > 0 && (
                    <span className="inline-block rounded-full bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-600">
                      {totals.count_sem_purchase} sem purchase
                    </span>
                  )}
                  {(totals?.count_sobreatribuidos || 0) === 0 &&
                   (totals?.count_sem_vinculo || 0) === 0 &&
                   (totals?.count_sem_purchase || 0) === 0 && (
                    <span className="text-xs text-slate-400">Nenhum alerta</span>
                  )}
                </div>
              </div>
            </div>
          </section>

          {/* ---- Filtros ---- */}
          <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft">
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">Filtros</h2>
            <div className="flex flex-wrap items-end gap-4">
              {/* Status toggles */}
              <div className="flex flex-col gap-1">
                <p className="text-xs text-slate-500">Status</p>
                <div className="flex flex-wrap gap-1.5">
                  {allStatuses.map((s) => {
                    const cfg = STATUS_CONFIG[s]
                    const active = filtroStatus.includes(s)
                    return (
                      <button
                        key={s}
                        onClick={() => toggleStatus(s)}
                        className={`rounded-full border px-2.5 py-0.5 text-xs font-semibold transition ${
                          active
                            ? `${cfg.bg} ${cfg.text} border-transparent`
                            : 'border-slate-200 bg-white text-slate-500 hover:bg-slate-50'
                        }`}
                      >
                        {cfg.label}
                      </button>
                    )
                  })}
                </div>
              </div>

              {/* Canal */}
              <label className="flex flex-col gap-1 text-xs text-slate-500">
                Canal
                <input
                  type="text"
                  value={filtroCanal}
                  onChange={(e) => { setFiltroCanal(e.target.value); setPagina(0) }}
                  placeholder="ex: EMAIL"
                  className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm text-slate-900 w-32"
                />
              </label>

              {/* Delta mín */}
              <label className="flex flex-col gap-1 text-xs text-slate-500">
                Delta mín. (%)
                <input
                  type="number"
                  min="0"
                  max="100"
                  value={filtroDeltatMin}
                  onChange={(e) => { setFiltroDeltatMin(Number(e.target.value) || 0); setPagina(0) }}
                  className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm text-slate-900 w-24"
                />
              </label>

              {/* Limpar */}
              <button
                onClick={limparFiltros}
                className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-600 transition hover:bg-slate-50"
              >
                Limpar filtros
              </button>

              {/* Export */}
              <button
                onClick={() => exportCsv(itemsFiltrados, data.start_date, data.end_date)}
                disabled={!itemsFiltrados.length}
                className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-600 transition hover:bg-slate-50 disabled:opacity-50"
              >
                Exportar CSV
              </button>

              <span className="text-xs text-slate-400">
                {itemsFiltrados.length.toLocaleString('pt-BR')} registros filtrados
              </span>
            </div>
          </section>

          {/* ---- Gráficos ---- */}
          <div className="grid gap-5 lg:grid-cols-3">

            {/* Bar — by_status */}
            <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft">
              <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">Por Status</h2>
              {byStatus.length > 0 ? (
                <ResponsiveContainer width="100%" height={220}>
                  <BarChart data={byStatus} margin={{ top: 4, right: 8, left: 0, bottom: 4 }}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                    <XAxis
                      dataKey="status"
                      tick={{ fontSize: 10 }}
                      tickFormatter={(v) => STATUS_CONFIG[v]?.label || v}
                    />
                    <YAxis tick={{ fontSize: 10 }} />
                    <Tooltip
                      formatter={(value, name) => [value.toLocaleString('pt-BR'), name]}
                      labelFormatter={(v) => STATUS_CONFIG[v]?.label || v}
                    />
                    <Bar dataKey="count" name="Pedidos" radius={[4, 4, 0, 0]}>
                      {byStatus.map((entry) => (
                        <Cell key={entry.status} fill={STATUS_CONFIG[entry.status]?.color || '#94A3B8'} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <p className="text-xs text-slate-400">Sem dados.</p>
              )}
            </section>

            {/* Line — by_day */}
            <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft">
              <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">Evolução Diária</h2>
              {byDay.length > 0 ? (
                <ResponsiveContainer width="100%" height={220}>
                  <LineChart data={byDay} margin={{ top: 4, right: 8, left: 0, bottom: 4 }}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                    <XAxis
                      dataKey="purchase_date"
                      tick={{ fontSize: 9 }}
                      tickFormatter={fmtDateTick}
                      interval="preserveStartEnd"
                    />
                    <YAxis tick={{ fontSize: 10 }} tickFormatter={(v) => `R$${(v / 1000).toFixed(0)}k`} />
                    <Tooltip
                      formatter={(value) => formatCurrency(value)}
                      labelFormatter={fmtDate}
                    />
                    <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 11 }} />
                    <Line
                      type="monotone"
                      dataKey="valor_real"
                      name="Valor Real"
                      stroke="#22C55E"
                      strokeWidth={2}
                      dot={false}
                    />
                    <Line
                      type="monotone"
                      dataKey="valor_atribuido"
                      name="Valor Atribuído"
                      stroke="#3B82F6"
                      strokeWidth={2}
                      dot={false}
                    />
                  </LineChart>
                </ResponsiveContainer>
              ) : (
                <p className="text-xs text-slate-400">Sem dados com datas.</p>
              )}
            </section>

            {/* Pie — by_canal */}
            <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft">
              <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">Por Canal</h2>
              {byCanal.length > 0 ? (
                <ResponsiveContainer width="100%" height={220}>
                  <PieChart>
                    <Pie
                      data={byCanal}
                      dataKey="valor_atribuido"
                      nameKey="canal"
                      cx="50%"
                      cy="50%"
                      outerRadius={70}
                      label={({ canal, percent }) =>
                        `${canal} ${(percent * 100).toFixed(0)}%`
                      }
                      labelLine={false}
                    >
                      {byCanal.map((entry, index) => {
                        const COLORS = ['#3B82F6', '#22C55E', '#F59E0B', '#EF4444', '#8B5CF6', '#94A3B8']
                        return <Cell key={entry.canal} fill={COLORS[index % COLORS.length]} />
                      })}
                    </Pie>
                    <Tooltip formatter={(value) => formatCurrency(value)} />
                  </PieChart>
                </ResponsiveContainer>
              ) : (
                <p className="text-xs text-slate-400">Sem dados de canal.</p>
              )}
            </section>
          </div>

          {/* ---- Tabela paginada ---- */}
          <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
                Detalhamento por Pedido
              </h2>
              <span className="text-xs text-slate-400">
                {pagina * PAGE_SIZE + 1}–{Math.min((pagina + 1) * PAGE_SIZE, itemsFiltrados.length)} de{' '}
                {itemsFiltrados.length.toLocaleString('pt-BR')} registros
              </span>
            </div>

            {itensPagina.length === 0 ? (
              <p className="text-sm text-slate-500">Nenhum registro com os filtros selecionados.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="min-w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-200">
                      {[
                        { label: 'Pedido',           right: false },
                        { label: 'Data Compra',      right: false },
                        { label: 'ID Contato',       right: false },
                        { label: 'Valor Real',       right: true  },
                        { label: 'Valor Atribuído',  right: true  },
                        { label: 'Delta (%)',        right: true  },
                        { label: 'Canal',            right: false },
                        { label: 'Campaign IDs',     right: false },
                        { label: 'Treatments',       right: true  },
                        { label: 'Status',           right: false },
                      ].map((col, i) => (
                        <th
                          key={i}
                          className={`whitespace-nowrap px-3 py-2 text-xs font-semibold uppercase tracking-wide text-slate-500 ${col.right ? 'text-right' : 'text-left'}`}
                        >
                          {col.label}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {itensPagina.map((row, i) => (
                      <tr key={i} className={i % 2 === 0 ? 'bg-white' : 'bg-slate-50'}>
                        <td className="whitespace-nowrap px-3 py-2 font-mono text-xs text-slate-600">
                          {row.order_id ?? '-'}
                        </td>
                        <td className="whitespace-nowrap px-3 py-2 text-slate-600">
                          {fmtDate(row.purchase_date)}
                        </td>
                        <td className="whitespace-nowrap px-3 py-2 font-mono text-xs text-slate-500">
                          {row.contact_id ?? '-'}
                        </td>
                        <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums font-medium text-slate-900">
                          {formatCurrency(row.valor_real)}
                        </td>
                        <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums font-medium text-indigo-700">
                          {formatCurrency(row.valor_atribuido)}
                        </td>
                        <td
                          className={`whitespace-nowrap px-3 py-2 text-right tabular-nums font-semibold ${
                            row.delta_pct == null
                              ? 'text-slate-400'
                              : Number(row.delta_pct) < 0
                              ? 'text-red-600'
                              : 'text-emerald-700'
                          }`}
                        >
                          {fmtPct(row.delta_pct)}
                        </td>
                        <td className="whitespace-nowrap px-3 py-2 text-xs text-slate-600">
                          {row.canais ?? '-'}
                        </td>
                        <td
                          className="max-w-xs truncate px-3 py-2 text-xs text-slate-500"
                          title={row.campaign_ids ?? undefined}
                        >
                          {row.campaign_ids ?? '-'}
                        </td>
                        <td className="whitespace-nowrap px-3 py-2 text-right text-xs">
                          {Number(row.qtd_treatments) > 1 ? (
                            <span className="inline-flex items-center gap-0.5">
                              <span className="inline-block h-2 w-2 rounded-full bg-purple-500" title="Multi-campanha" />
                              <span className="text-purple-700 font-semibold">{row.qtd_treatments}</span>
                            </span>
                          ) : (
                            <span className="text-slate-500">{row.qtd_treatments ?? '-'}</span>
                          )}
                        </td>
                        <td className="whitespace-nowrap px-3 py-2">
                          <StatusBadge status={row.status} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {/* Paginação */}
            <div className="mt-4 flex items-center justify-between gap-3">
              <button
                onClick={() => setPagina((p) => Math.max(0, p - 1))}
                disabled={pagina === 0}
                className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 transition hover:bg-slate-50 disabled:opacity-40"
              >
                Anterior
              </button>
              <span className="text-xs text-slate-500">
                Página {pagina + 1} de {totalPaginas}
              </span>
              <button
                onClick={() => setPagina((p) => Math.min(totalPaginas - 1, p + 1))}
                disabled={pagina >= totalPaginas - 1}
                className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 transition hover:bg-slate-50 disabled:opacity-40"
              >
                Próxima
              </button>
            </div>
          </section>
        </>
      )}
    </div>
  )
}
