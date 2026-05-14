import { useState, useCallback } from 'react'
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, Cell, LabelList,
} from 'recharts'

const RFM_COLORS = {
  'Campeões': '#10b981',
  'Clientes Fiéis': '#6366f1',
  'Clientes Recentes': '#3b82f6',
  'Em Risco': '#f59e0b',
  'Inativos': '#ef4444',
  'Regulares': '#94a3b8',
}
const MATURIDADE_COLORS = ['#bfdbfe', '#60a5fa', '#3b82f6', '#1d4ed8']
const RECENCIA_COLORS = ['#10b981', '#34d399', '#fbbf24', '#f97316', '#ef4444']

function formatCurrency(v) {
  if (v == null || isNaN(Number(v))) return '—'
  return new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(Number(v))
}
function formatNum(v) {
  if (v == null) return '—'
  return new Intl.NumberFormat('pt-BR').format(Number(v))
}
function getDefaultDates() {
  const today = new Date()
  const start = new Date(today)
  start.setDate(start.getDate() - 89)
  return {
    start: start.toISOString().split('T')[0],
    end: today.toISOString().split('T')[0],
  }
}

function KpiCard({ label, value, sub }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-1 text-2xl font-bold text-slate-800">{value ?? '—'}</p>
      {sub && <p className="mt-0.5 text-xs text-slate-400">{sub}</p>}
    </div>
  )
}

function ChartCard({ title, subtitle, children }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <p className="text-sm font-semibold text-slate-700">{title}</p>
      {subtitle && <p className="mb-4 text-xs text-slate-400">{subtitle}</p>}
      {!subtitle && <div className="mb-4" />}
      {children}
    </div>
  )
}

function PctTooltip({ active, payload, total }) {
  if (!active || !payload?.length) return null
  const v = payload[0].value
  const pct = total ? ((v / total) * 100).toFixed(1) : '—'
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs shadow">
      <p className="font-semibold text-slate-700">{payload[0].payload?.faixa || payload[0].payload?.segmento || payload[0].payload?.produto}</p>
      <p className="text-slate-600">{formatNum(v)} clientes ({pct}%)</p>
    </div>
  )
}

export default function PerfilClientePage() {
  const defaults = getDefaultDates()
  const [startDate, setStartDate] = useState(defaults.start)
  const [endDate, setEndDate] = useState(defaults.end)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handleAtualizar = useCallback(async () => {
    if (!startDate || !endDate) return
    setLoading(true)
    setError('')
    try {
      const params = new URLSearchParams({ start: startDate, end: endDate })
      const res = await fetch(`/api/open-data/perfil-cliente?${params}`)
      const text = await res.text()
      let payload = null
      try { payload = text ? JSON.parse(text) : null } catch (_) {}
      if (!res.ok || !payload) throw new Error(payload?.detail || `HTTP ${res.status}`)
      setData(payload)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erro ao carregar perfil.')
    } finally {
      setLoading(false)
    }
  }, [startDate, endDate])

  const total = data?.resumo?.total_clientes || 1

  return (
    <section className="space-y-5">
      <section className="rounded-2xl bg-gradient-to-r from-violet-700 to-purple-600 p-6 text-white shadow-soft md:p-8">
        <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight md:text-4xl">Perfil do Cliente</h1>
            <p className="mt-2 text-sm text-violet-100 md:text-base">
              Visão macro da base — maturidade, recência, RFM e preferências de produto.
            </p>
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <label className="flex flex-col gap-1 text-sm text-white/90">
              Início
              <input type="date" value={startDate} onChange={e => setStartDate(e.target.value)}
                className="rounded-lg border border-white/40 bg-white/95 px-3 py-2 text-sm text-slate-900" />
            </label>
            <label className="flex flex-col gap-1 text-sm text-white/90">
              Fim
              <input type="date" value={endDate} onChange={e => setEndDate(e.target.value)}
                className="rounded-lg border border-white/40 bg-white/95 px-3 py-2 text-sm text-slate-900" />
            </label>
            <button onClick={handleAtualizar} disabled={loading}
              className="rounded-xl bg-white px-5 py-2.5 text-sm font-semibold text-violet-700 shadow hover:bg-violet-50 disabled:opacity-60">
              {loading ? 'Carregando…' : 'Atualizar'}
            </button>
          </div>
        </div>
      </section>

      {error && (
        <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div>
      )}

      {loading && (
        <div className="flex items-center gap-3 text-sm text-slate-500">
          <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none">
            <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" className="opacity-25" />
            <path d="M4 12a8 8 0 018-8" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
          </svg>
          Consultando BigQuery — pode levar alguns segundos…
        </div>
      )}

      {!data && !loading && !error && (
        <p className="text-sm text-slate-500">Selecione o período e clique em Atualizar.</p>
      )}

      {data && (
        <>
          {/* KPIs */}
          <div className="grid grid-cols-2 gap-4 md:grid-cols-5">
            <KpiCard label="Clientes únicos" value={formatNum(data.resumo?.total_clientes)} />
            <KpiCard label="Novos clientes" value={formatNum(data.resumo?.novos_clientes)} sub="1ª compra no período" />
            <KpiCard label="Recorrentes" value={formatNum(data.resumo?.recorrentes)} />
            <KpiCard label="Ticket médio" value={formatCurrency(data.resumo?.ticket_medio)} />
            <KpiCard label="Pedidos por cliente" value={(data.resumo?.freq_media || 0).toFixed(1)} sub="média no período" />
          </div>

          {/* Maturidade + Recência */}
          <div className="grid gap-4 md:grid-cols-2">
            <ChartCard title="Maturidade da Base" subtitle="Tempo desde a 1ª compra (histórico)">
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={data.maturidade} layout="vertical" margin={{ left: 0, right: 50, top: 0, bottom: 0 }}>
                  <XAxis type="number" hide />
                  <YAxis type="category" dataKey="faixa" width={110} tick={{ fontSize: 12, fill: '#475569' }} />
                  <Tooltip content={<PctTooltip total={total} />} />
                  <Bar dataKey="qtd" radius={4}>
                    {data.maturidade.map((_, i) => (
                      <Cell key={i} fill={MATURIDADE_COLORS[i] || '#3b82f6'} />
                    ))}
                    <LabelList dataKey="qtd" position="right" style={{ fontSize: 11, fill: '#64748b' }}
                      formatter={v => formatNum(v)} />
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </ChartCard>

            <ChartCard title="Recência" subtitle="Dias desde a última compra no período">
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={data.recencia} layout="vertical" margin={{ left: 0, right: 50, top: 0, bottom: 0 }}>
                  <XAxis type="number" hide />
                  <YAxis type="category" dataKey="faixa" width={110} tick={{ fontSize: 12, fill: '#475569' }} />
                  <Tooltip content={<PctTooltip total={total} />} />
                  <Bar dataKey="qtd" radius={4}>
                    {data.recencia.map((_, i) => (
                      <Cell key={i} fill={RECENCIA_COLORS[i] || '#6366f1'} />
                    ))}
                    <LabelList dataKey="qtd" position="right" style={{ fontSize: 11, fill: '#64748b' }}
                      formatter={v => formatNum(v)} />
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </ChartCard>
          </div>

          {/* RFM */}
          <ChartCard title="Segmentação RFM" subtitle="Recência × Frequência × Valor — quintis calculados sobre os clientes do período">
            <ResponsiveContainer width="100%" height={230}>
              <BarChart data={data.rfm} layout="vertical" margin={{ left: 0, right: 60, top: 0, bottom: 0 }}>
                <XAxis type="number" hide />
                <YAxis type="category" dataKey="segmento" width={140} tick={{ fontSize: 12, fill: '#475569' }} />
                <Tooltip content={<PctTooltip total={total} />} />
                <Bar dataKey="qtd" radius={4}>
                  {data.rfm.map((entry, i) => (
                    <Cell key={i} fill={RFM_COLORS[entry.segmento] || '#94a3b8'} />
                  ))}
                  <LabelList dataKey="qtd" position="right" style={{ fontSize: 11, fill: '#64748b' }}
                    formatter={v => formatNum(v)} />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
            <div className="mt-3 flex flex-wrap gap-3 border-t border-slate-100 pt-3">
              {[
                { seg: 'Campeões', desc: 'R=5 F≥4 — compraram recentemente, com alta frequência' },
                { seg: 'Clientes Fiéis', desc: 'F≥4 R≥3 — compram com frequência' },
                { seg: 'Clientes Recentes', desc: 'R=5 F≤2 — novos ou voltando' },
                { seg: 'Em Risco', desc: 'R≤2 F≥3 M≥3 — eram bons, sumiram' },
                { seg: 'Inativos', desc: 'R=1 — não compram há muito tempo' },
                { seg: 'Regulares', desc: 'Demais combinações de R/F/M' },
              ].map(({ seg, desc }) => (
                <span key={seg} className="flex items-start gap-1.5 text-xs text-slate-500" title={desc}>
                  <span className="mt-0.5 h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: RFM_COLORS[seg] }} />
                  <span><strong className="text-slate-700">{seg}</strong> — {desc}</span>
                </span>
              ))}
            </div>
          </ChartCard>

          {/* Top Produtos — receita (chart) + quantidade (tabela) */}
          {(data.top_produtos?.length > 0 || data.top_produtos_quantidade?.length > 0) && (
            <div className="grid gap-4 md:grid-cols-2">
              {data.top_produtos?.length > 0 && (
                <ChartCard title="Top Produtos — Receita" subtitle="Por receita no período (top 15)">
                  <ResponsiveContainer width="100%" height={Math.max(320, data.top_produtos.length * 28)}>
                    <BarChart data={data.top_produtos} layout="vertical" margin={{ left: 0, right: 90, top: 0, bottom: 0 }}>
                      <XAxis type="number" hide />
                      <YAxis type="category" dataKey="produto" width={200} tick={{ fontSize: 11, fill: '#475569' }} />
                      <Tooltip formatter={(v, name) =>
                        name === 'receita' ? [formatCurrency(v), 'Receita'] : [formatNum(v), 'Pedidos']
                      } />
                      <Bar dataKey="receita" fill="#6366f1" radius={3}>
                        <LabelList dataKey="receita" position="right" style={{ fontSize: 10, fill: '#64748b' }}
                          formatter={v => formatCurrency(v)} />
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </ChartCard>
              )}

              {data.top_produtos_quantidade?.length > 0 && (
                <ChartCard title="Top Produtos — Quantidade" subtitle="Por nº de pedidos no período (top 15)">
                  <div className="overflow-auto">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="border-b border-slate-100 text-left text-slate-500">
                          <th className="pb-2 pr-3 font-medium">#</th>
                          <th className="pb-2 pr-3 font-medium">Produto</th>
                          <th className="pb-2 text-right font-medium">Pedidos</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.top_produtos_quantidade.map((row, i) => (
                          <tr key={i} className="border-b border-slate-50 hover:bg-slate-50">
                            <td className="py-1.5 pr-3 text-slate-400">{i + 1}</td>
                            <td className="py-1.5 pr-3 text-slate-700">{row.produto}</td>
                            <td className="py-1.5 text-right font-semibold text-slate-800">{formatNum(row.pedidos)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </ChartCard>
              )}
            </div>
          )}

          {/* Top Categorias */}
          {data.top_categorias?.length > 0 && (
            <div className="grid gap-4 md:grid-cols-2">
              <ChartCard title="Top Categorias — Receita" subtitle="Por receita no período">
                <ResponsiveContainer width="100%" height={Math.max(240, data.top_categorias.length * 36)}>
                  <BarChart data={data.top_categorias} layout="vertical" margin={{ left: 0, right: 90, top: 0, bottom: 0 }}>
                    <XAxis type="number" hide />
                    <YAxis type="category" dataKey="categoria" width={160} tick={{ fontSize: 12, fill: '#475569' }} />
                    <Tooltip formatter={(v, name) =>
                      name === 'receita' ? [formatCurrency(v), 'Receita'] : [formatNum(v), 'Pedidos']
                    } />
                    <Bar dataKey="receita" fill="#8b5cf6" radius={4}>
                      <LabelList dataKey="receita" position="right" style={{ fontSize: 10, fill: '#64748b' }}
                        formatter={v => formatCurrency(v)} />
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </ChartCard>

              <ChartCard title="Top Categorias — Quantidade" subtitle="Por nº de pedidos no período">
                <ResponsiveContainer width="100%" height={Math.max(240, data.top_categorias.length * 36)}>
                  <BarChart
                    data={[...data.top_categorias].sort((a, b) => b.pedidos - a.pedidos)}
                    layout="vertical"
                    margin={{ left: 0, right: 70, top: 0, bottom: 0 }}
                  >
                    <XAxis type="number" hide />
                    <YAxis type="category" dataKey="categoria" width={160} tick={{ fontSize: 12, fill: '#475569' }} />
                    <Tooltip formatter={(v, name) =>
                      name === 'pedidos' ? [formatNum(v), 'Pedidos'] : [formatCurrency(v), 'Receita']
                    } />
                    <Bar dataKey="pedidos" fill="#06b6d4" radius={4}>
                      <LabelList dataKey="pedidos" position="right" style={{ fontSize: 10, fill: '#64748b' }}
                        formatter={v => formatNum(v)} />
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </ChartCard>
            </div>
          )}
        </>
      )}
    </section>
  )
}
