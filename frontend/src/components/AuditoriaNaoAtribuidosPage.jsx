import { useState, useMemo, useCallback } from 'react'
import {
  BarChart, Bar,
  PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from 'recharts'

const STATUS_CONFIG = {
  nao_atribuido_sms:   { label: 'Não Atribuído — SMS',    bg: 'bg-red-100',    text: 'text-red-700',    color: '#EF4444' },
  nao_atribuido_email: { label: 'Não Atribuído — E-mail', bg: 'bg-orange-100', text: 'text-orange-700', color: '#F97316' },
  sem_vinculo:         { label: 'Sem Vínculo',            bg: 'bg-amber-100',  text: 'text-amber-700',  color: '#F59E0B' },
  ausente_revenue:     { label: 'Ausente em Receita',     bg: 'bg-purple-100', text: 'text-purple-700', color: '#8B5CF6' },
}

const PAGE_SIZE = 100
const PIE_COLORS = ['#3B82F6', '#F97316', '#22C55E', '#F59E0B', '#8B5CF6']

function fmtDate(v) {
  if (!v) return '-'
  const s = String(v).slice(0, 10)
  const parts = s.split('-')
  return parts.length === 3 ? `${parts[2]}/${parts[1]}/${parts[0]}` : v
}

function fmtDateShort(v) {
  if (!v) return ''
  const parts = String(v).slice(0, 10).split('-')
  return parts.length === 3 ? `${parts[2]}/${parts[1]}` : v
}

function fmtCur(v) {
  if (v == null || isNaN(Number(v))) return '-'
  return new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(Number(v))
}

function fmtPct(v) {
  if (v == null) return '-'
  return `${Number(v).toLocaleString('pt-BR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`
}

function StatusBadge({ status }) {
  const cfg = STATUS_CONFIG[status] || { label: status, bg: 'bg-slate-100', text: 'text-slate-600' }
  return (
    <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-semibold ${cfg.bg} ${cfg.text}`}>
      {cfg.label}
    </span>
  )
}

function MetricCard({ label, value, sub, highlight, critical }) {
  const border = critical ? 'border-purple-200 bg-purple-50' : highlight ? 'border-red-200 bg-red-50' : 'border-slate-200 bg-slate-50'
  const textColor = critical ? 'text-purple-900' : highlight ? 'text-red-800' : 'text-slate-900'
  return (
    <div className={`rounded-xl border p-3 ${border}`}>
      <p className="text-xs text-slate-500">{label}</p>
      <p className={`mt-0.5 text-lg font-bold ${textColor}`}>{value}</p>
      {sub && <p className="text-xs text-slate-400 mt-0.5">{sub}</p>}
    </div>
  )
}

function exportCsv(items, startDate, endDate) {
  if (!items?.length) return
  const cols = [
    { key: 'order_id',             label: 'Pedido' },
    { key: 'purchase_date',        label: 'Data Compra' },
    { key: 'contact_id',           label: 'ID Contato' },
    { key: 'valor_real',           label: 'Valor Real (R$)' },
    { key: 'canal_last_touch',     label: 'Canal Last Touch' },
    { key: 'data_gatilho',         label: 'Data Gatilho' },
    { key: 'dias_gatilho_compra',  label: 'Dias Gatilho→Compra' },
    { key: 'campaign_id_gatilho',  label: 'Campaign ID Gatilho' },
    { key: 'multi_gatilho',        label: 'Multi Gatilho' },
    { key: 'em_revenue_attribution', label: 'Em Revenue Attribution' },
    { key: 'status',               label: 'Status' },
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
  a.download = `auditoria-nao-atribuidos-${startDate || 'dados'}-${endDate || ''}.csv`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

function todayIso() {
  return new Date().toISOString().slice(0, 10)
}

function firstOfMonthIso() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-01`
}

export default function AuditoriaNaoAtribuidosPage() {
  const [localStart, setLocalStart] = useState(firstOfMonthIso)
  const [localEnd,   setLocalEnd]   = useState(todayIso)

  const [data, setData]       = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState('')

  const [filtroStatus,  setFiltroStatus]  = useState([])
  const [filtroCanal,   setFiltroCanal]   = useState('')
  const [filtroValorMin, setFiltroValorMin] = useState(0)
  const [filtroCampaign, setFiltroCampaign] = useState('')
  const [pagina, setPagina] = useState(0)
  const [tabelaAberta, setTabelaAberta] = useState(false)

  const handleCarregar = useCallback(async () => {
    setLoading(true)
    setError('')
    setData(null)
    setPagina(0)
    setTabelaAberta(false)
    try {
      const params = new URLSearchParams({ start: localStart, end: localEnd })
      const res = await fetch(`/api/open-data/emarsys/auditoria-nao-atribuidos?${params}`)
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
  }, [localStart, localEnd])

  const allStatuses = Object.keys(STATUS_CONFIG)

  const itemsFiltrados = useMemo(() => {
    if (!data?.items) return []
    return data.items.filter((it) => {
      if (filtroStatus.length > 0 && !filtroStatus.includes(it.status)) return false
      if (filtroCanal) {
        const canal = (it.canal_last_touch || '').toUpperCase()
        if (!canal.includes(filtroCanal.toUpperCase())) return false
      }
      if (filtroValorMin > 0 && (Number(it.valor_real) || 0) < filtroValorMin) return false
      if (filtroCampaign.trim()) {
        const cid = String(it.campaign_id_gatilho || '')
        if (!cid.toLowerCase().includes(filtroCampaign.trim().toLowerCase())) return false
      }
      return true
    })
  }, [data, filtroStatus, filtroCanal, filtroValorMin, filtroCampaign])

  const itensPagina = useMemo(() => {
    const start = pagina * PAGE_SIZE
    return itemsFiltrados.slice(start, start + PAGE_SIZE)
  }, [itemsFiltrados, pagina])

  const totalPaginas = Math.max(1, Math.ceil(itemsFiltrados.length / PAGE_SIZE))

  const toggleStatus = (s) => {
    setPagina(0)
    setFiltroStatus((prev) => prev.includes(s) ? prev.filter((x) => x !== s) : [...prev, s])
  }

  const limparFiltros = () => {
    setFiltroStatus([])
    setFiltroCanal('')
    setFiltroValorMin(0)
    setFiltroCampaign('')
    setPagina(0)
  }

  const totals    = data?.totals    || {}
  const byDay     = data?.by_day    || []
  const byCanal   = data?.by_canal  || []
  const byCampaign = data?.by_campaign || []

  return (
    <div className="space-y-6">

      {/* Controles de data */}
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-xs text-slate-500">
          De
          <input type="date" value={localStart} onChange={(e) => setLocalStart(e.target.value)}
            className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm text-slate-900" />
        </label>
        <label className="flex flex-col gap-1 text-xs text-slate-500">
          Até
          <input type="date" value={localEnd} onChange={(e) => setLocalEnd(e.target.value)}
            className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm text-slate-900" />
        </label>
        <button
          onClick={handleCarregar}
          disabled={loading}
          className="rounded-lg bg-indigo-600 px-5 py-2 text-sm font-semibold text-white transition hover:bg-indigo-700 disabled:opacity-50"
        >
          {loading ? 'Carregando...' : data ? 'Recarregar' : 'Consultar'}
        </button>
        {data && (
          <span className="text-xs text-slate-400">
            {totals.total_eligible?.toLocaleString('pt-BR')} elegíveis · {totals.total_nao_atribuidos?.toLocaleString('pt-BR')} não atribuídos
          </span>
        )}
      </div>

      {error && (
        <p className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</p>
      )}

      {!data && !loading && !error && (
        <p className="text-sm text-slate-500">
          Selecione o período e clique em "Consultar" para identificar pedidos que deveriam ter sido atribuídos ao CRM mas não foram.
        </p>
      )}

      {data && (
        <>
          {/* Cards de métricas */}
          <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft">
            <h2 className="mb-4 text-sm font-semibold uppercase tracking-wide text-slate-500">Resumo</h2>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
              <MetricCard label="Pedidos elegíveis" value={(totals.total_eligible || 0).toLocaleString('pt-BR')} sub="com gatilho válido" />
              <MetricCard label="Não atribuídos" value={(totals.total_nao_atribuidos || 0).toLocaleString('pt-BR')} highlight />
              <MetricCard label="% não atribuição" value={fmtPct(totals.pct_nao_atribuicao)} highlight />
              <MetricCard label="Receita não atribuída" value={fmtCur(totals.receita_nao_atribuida)} sub="soma valor_real" highlight />
              <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
                <p className="text-xs text-slate-500">Por Canal</p>
                <div className="mt-1 flex flex-col gap-1">
                  <span className="text-xs font-semibold text-slate-700">SMS: {(totals.count_sms || 0).toLocaleString('pt-BR')}</span>
                  <span className="text-xs font-semibold text-slate-700">E-mail: {(totals.count_email || 0).toLocaleString('pt-BR')}</span>
                </div>
              </div>
              <MetricCard
                label="Ausentes em Receita"
                value={(totals.count_ausentes_revenue || 0).toLocaleString('pt-BR')}
                sub="nunca chegaram ao pipeline"
                critical={(totals.count_ausentes_revenue || 0) > 0}
              />
            </div>
          </section>

          {/* Filtros */}
          <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft">
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">Filtros</h2>
            <div className="flex flex-wrap items-end gap-4">
              <div className="flex flex-col gap-1">
                <p className="text-xs text-slate-500">Status</p>
                <div className="flex flex-wrap gap-1.5">
                  {allStatuses.map((s) => {
                    const cfg = STATUS_CONFIG[s]
                    const active = filtroStatus.includes(s)
                    return (
                      <button key={s} onClick={() => toggleStatus(s)}
                        className={`rounded-full border px-2.5 py-0.5 text-xs font-semibold transition ${
                          active ? `${cfg.bg} ${cfg.text} border-transparent` : 'border-slate-200 bg-white text-slate-500 hover:bg-slate-50'
                        }`}>
                        {cfg.label}
                      </button>
                    )
                  })}
                </div>
              </div>
              <label className="flex flex-col gap-1 text-xs text-slate-500">
                Canal
                <select value={filtroCanal} onChange={(e) => { setFiltroCanal(e.target.value); setPagina(0) }}
                  className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm text-slate-900 w-32">
                  <option value="">Todos</option>
                  <option value="SMS">SMS</option>
                  <option value="EMAIL">E-mail</option>
                </select>
              </label>
              <label className="flex flex-col gap-1 text-xs text-slate-500">
                Valor mín. (R$)
                <input type="number" min="0" value={filtroValorMin}
                  onChange={(e) => { setFiltroValorMin(Number(e.target.value) || 0); setPagina(0) }}
                  className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm text-slate-900 w-32" />
              </label>
              <label className="flex flex-col gap-1 text-xs text-slate-500">
                Campaign ID
                <input type="text" value={filtroCampaign} placeholder="ex: 434999"
                  onChange={(e) => { setFiltroCampaign(e.target.value); setPagina(0) }}
                  className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm text-slate-900 w-32" />
              </label>
              <button onClick={limparFiltros}
                className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-600 transition hover:bg-slate-50">
                Limpar
              </button>
              <button onClick={() => exportCsv(itemsFiltrados, data.start_date, data.end_date)}
                disabled={!itemsFiltrados.length}
                className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-600 transition hover:bg-slate-50 disabled:opacity-50">
                Exportar CSV
              </button>
              <span className="text-xs text-slate-400">{itemsFiltrados.length.toLocaleString('pt-BR')} registros</span>
            </div>
          </section>

          {/* Gráficos */}
          <div className="grid gap-5 lg:grid-cols-3">
            {/* Stacked bar — eligible vs nao_atribuidos por dia */}
            <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft lg:col-span-2">
              <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">Elegíveis vs Não Atribuídos por Dia</h2>
              {byDay.length > 0 ? (
                <ResponsiveContainer width="100%" height={220}>
                  <BarChart data={byDay} margin={{ top: 4, right: 8, left: 0, bottom: 4 }}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                    <XAxis dataKey="purchase_date" tick={{ fontSize: 9 }} tickFormatter={fmtDateShort} interval="preserveStartEnd" />
                    <YAxis tick={{ fontSize: 10 }} />
                    <Tooltip labelFormatter={fmtDate} />
                    <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 11 }} />
                    <Bar dataKey="elegiveis"       name="Elegíveis"       fill="#94A3B8" radius={[2,2,0,0]} stackId="a" />
                    <Bar dataKey="nao_atribuidos"  name="Não Atribuídos"  fill="#EF4444" radius={[2,2,0,0]} stackId="a" />
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <p className="text-xs text-slate-400">Sem dados.</p>
              )}
            </section>

            {/* Donut — by_canal */}
            <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft">
              <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">Por Canal (Não Atribuídos)</h2>
              {byCanal.length > 0 ? (
                <ResponsiveContainer width="100%" height={220}>
                  <PieChart>
                    <Pie data={byCanal} dataKey="count" nameKey="canal"
                      cx="50%" cy="50%" innerRadius={50} outerRadius={75}
                      label={({ canal, percent }) => `${canal} ${(percent * 100).toFixed(0)}%`}
                      labelLine={false}>
                      {byCanal.map((entry, i) => (
                        <Cell key={entry.canal} fill={PIE_COLORS[i % PIE_COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip formatter={(v) => v.toLocaleString('pt-BR')} />
                  </PieChart>
                </ResponsiveContainer>
              ) : (
                <p className="text-xs text-slate-400">Sem dados de canal.</p>
              )}
            </section>
          </div>

          {/* Top 10 campaigns */}
          {byCampaign.length > 0 && (
            <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft">
              <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">Top 10 Campanhas — Receita Não Atribuída</h2>
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={byCampaign} layout="vertical" margin={{ top: 4, right: 40, left: 80, bottom: 4 }}>
                  <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="#e2e8f0" />
                  <XAxis type="number" tick={{ fontSize: 10 }} tickFormatter={(v) => `R$${(v/1000).toFixed(0)}k`} />
                  <YAxis type="category" dataKey="campaign_id" tick={{ fontSize: 10 }} width={80} />
                  <Tooltip formatter={(v) => fmtCur(v)} />
                  <Bar dataKey="valor_real" name="Receita não atribuída" fill="#8B5CF6" radius={[0,4,4,0]} />
                </BarChart>
              </ResponsiveContainer>
            </section>
          )}

          {/* Tabela colapsável */}
          <section className="rounded-2xl border border-slate-200 bg-white shadow-soft">
            <button type="button" onClick={() => setTabelaAberta((v) => !v)}
              className="flex w-full items-center justify-between px-5 py-4 text-left">
              <span className="text-sm font-semibold uppercase tracking-wide text-slate-500">
                Detalhamento por Pedido
                <span className="ml-2 text-xs font-normal normal-case text-slate-400">
                  ({itemsFiltrados.length.toLocaleString('pt-BR')} registros)
                </span>
              </span>
              <svg className={`h-4 w-4 text-slate-400 transition-transform ${tabelaAberta ? 'rotate-180' : ''}`}
                fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
              </svg>
            </button>

            {tabelaAberta && (
              <div className="border-t border-slate-100 px-5 pb-5 pt-4">
                {itensPagina.length === 0 ? (
                  <p className="text-sm text-slate-500">Nenhum registro com os filtros selecionados.</p>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="min-w-full text-sm">
                      <thead>
                        <tr className="border-b border-slate-200">
                          {[
                            { label: 'Pedido',              right: false },
                            { label: 'Data Compra',         right: false },
                            { label: 'ID Contato',          right: false },
                            { label: 'Valor Real',          right: true  },
                            { label: 'Canal',               right: false },
                            { label: 'Data Gatilho',        right: false },
                            { label: 'Dias',                right: true  },
                            { label: 'Campaign ID',         right: false },
                            { label: 'Multi',               right: true  },
                            { label: 'Em Rev. Attrib.',     right: true  },
                            { label: 'Status',              right: false },
                          ].map((col, i) => (
                            <th key={i}
                              className={`whitespace-nowrap px-3 py-2 text-xs font-semibold uppercase tracking-wide text-slate-500 ${col.right ? 'text-right' : 'text-left'}`}>
                              {col.label}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {itensPagina.map((row, i) => (
                          <tr key={i} className={i % 2 === 0 ? 'bg-white' : 'bg-slate-50'}>
                            <td className="whitespace-nowrap px-3 py-2 font-mono text-xs text-slate-600">{row.order_id ?? '-'}</td>
                            <td className="whitespace-nowrap px-3 py-2 text-slate-600">{fmtDate(row.purchase_date)}</td>
                            <td className="whitespace-nowrap px-3 py-2 font-mono text-xs text-slate-500">{row.contact_id ?? '-'}</td>
                            <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums font-medium text-slate-900">{fmtCur(row.valor_real)}</td>
                            <td className="whitespace-nowrap px-3 py-2 text-xs font-semibold text-slate-700">{row.canal_last_touch ?? '-'}</td>
                            <td className="whitespace-nowrap px-3 py-2 text-xs text-slate-600">{fmtDate(row.data_gatilho)}</td>
                            <td className="whitespace-nowrap px-3 py-2 text-right text-xs text-slate-600">
                              {row.dias_gatilho_compra != null ? `${row.dias_gatilho_compra}d` : '-'}
                            </td>
                            <td className="whitespace-nowrap px-3 py-2 text-xs text-slate-500">{row.campaign_id_gatilho ?? '-'}</td>
                            <td className="whitespace-nowrap px-3 py-2 text-right text-xs">
                              {row.multi_gatilho
                                ? <span className="inline-block rounded-full bg-blue-100 px-2 py-0.5 text-xs font-semibold text-blue-700">sim</span>
                                : <span className="text-slate-400">—</span>}
                            </td>
                            <td className="whitespace-nowrap px-3 py-2 text-right text-xs">
                              {row.em_revenue_attribution
                                ? <span className="text-slate-500">sim</span>
                                : <span className="font-semibold text-purple-700">não</span>}
                            </td>
                            <td className="whitespace-nowrap px-3 py-2"><StatusBadge status={row.status} /></td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
                <div className="mt-4 flex items-center justify-between gap-3">
                  <button onClick={() => setPagina((p) => Math.max(0, p - 1))} disabled={pagina === 0}
                    className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 transition hover:bg-slate-50 disabled:opacity-40">
                    Anterior
                  </button>
                  <span className="text-xs text-slate-500">
                    Página {pagina + 1} de {totalPaginas} · {pagina * PAGE_SIZE + 1}–{Math.min((pagina + 1) * PAGE_SIZE, itemsFiltrados.length)}
                  </span>
                  <button onClick={() => setPagina((p) => Math.min(totalPaginas - 1, p + 1))} disabled={pagina >= totalPaginas - 1}
                    className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 transition hover:bg-slate-50 disabled:opacity-40">
                    Próxima
                  </button>
                </div>
              </div>
            )}
          </section>
        </>
      )}
    </div>
  )
}
