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

async function fetchJson(url) {
  const res = await fetch(url)
  const json = await res.json().catch(() => null)
  if (!res.ok) return { ok: false, data: null, error: json?.detail || 'Erro desconhecido' }
  return { ok: true, data: json }
}

const CANAL_LABELS = { email: 'Email', sms: 'SMS', whatsapp: 'WhatsApp' }

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

function SectionCard({ title, badge, badgeColor = 'bg-rose-100 text-rose-700', description, children }) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft md:p-6">
      <div className="mb-3 flex items-center gap-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">{title}</h2>
        {badge != null && (
          <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${badgeColor}`}>
            {badge}
          </span>
        )}
      </div>
      {description && <p className="mb-4 text-xs text-slate-400">{description}</p>}
      {children}
    </section>
  )
}

function DetalheDeviaAtribuir({ startDate, endDate }) {
  const [state, setState] = useState({ data: null, loading: false, error: '' })

  const handleCarregar = async () => {
    setState({ data: null, loading: true, error: '' })
    try {
      const params = new URLSearchParams({ start: startDate, ...(endDate ? { end: endDate } : {}) })
      const res = await fetchJson(`/api/open-data/emarsys/audit-deveria-atribuir?${params}`)
      if (!res.ok) {
        setState({ data: null, loading: false, error: res.error || 'Erro ao carregar.' })
        return
      }
      setState({ data: res.data, loading: false, error: '' })
    } catch (e) {
      setState({ data: null, loading: false, error: e.message || 'Erro.' })
    }
  }

  const handleExport = () => {
    const items = state.data?.items
    if (!items?.length) return
    const fmtBRL = (v) =>
      v == null ? '' : new Intl.NumberFormat('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(Number(v))
    const cols = [
      { key: 'contact_id',               label: 'ID Contato' },
      { key: 'order_id',                 label: 'Pedido' },
      { key: 'data_compra',              label: 'Data Compra' },
      { key: 'valor_pedido',             label: 'Valor Pedido (R$)', fmt: fmtBRL },
      { key: 'email_open_date',          label: 'Data Abertura Email' },
      { key: 'email_campanha',           label: 'Campanha Email' },
      { key: 'sms_send_date',            label: 'Data Envio SMS' },
      { key: 'sms_campanha',             label: 'Campanha SMS' },
      { key: 'canal_deveria_atribuir',   label: 'Canal Deveria Atribuir' },
      { key: 'campanha_deveria_atribuir', label: 'Campanha Deveria Atribuir' },
    ]
    const escape = (v) => {
      if (v == null) return ''
      const s = String(v)
      return s.includes(',') || s.includes('"') || s.includes('\n') ? `"${s.replace(/"/g, '""')}"` : s
    }
    const csv = '﻿' + [
      cols.map((c) => c.label).join(','),
      ...items.map((r) => cols.map((c) => escape(c.fmt ? c.fmt(r[c.key]) : r[c.key])).join(',')),
    ].join('\n')
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `deveria-atribuir-${startDate}-${endDate || startDate}.csv`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  const { data, loading, error } = state

  const CANAL_BADGE = {
    email: 'bg-blue-50 text-blue-700',
    sms:   'bg-orange-50 text-orange-700',
  }

  return (
    <section className="rounded-2xl border border-amber-200 bg-white p-5 shadow-soft md:p-6">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wide text-amber-700">
            Detalhamento — Deveria ter Atribuído
          </h2>
          <p className="mt-1 text-xs text-slate-400">
            Pedidos não atribuídos com touchpoint CRM nos 7 dias anteriores à compra. Top 1.000 por valor.
          </p>
        </div>
        <div className="flex shrink-0 gap-2">
          <button
            onClick={handleCarregar}
            disabled={loading}
            className="rounded-lg bg-amber-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-amber-700 disabled:opacity-50"
          >
            {loading ? 'Carregando...' : data ? 'Recarregar' : 'Carregar detalhes'}
          </button>
          {data?.items?.length > 0 && (
            <button
              onClick={handleExport}
              className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-50"
            >
              Exportar CSV
            </button>
          )}
        </div>
      </div>

      {error && (
        <p className="mb-4 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</p>
      )}

      {!data && !loading && (
        <p className="text-sm text-slate-500">Clique em "Carregar detalhes" para ver os pedidos.</p>
      )}

      {data && (
        <>
          <p className="mb-3 text-xs text-slate-500">
            {data.total.toLocaleString('pt-BR')} pedido{data.total !== 1 ? 's' : ''} encontrado{data.total !== 1 ? 's' : ''}
            {data.total >= 1000 && ' (limitado a 1.000 — use a exportação para ver todos)'}
          </p>
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200">
                  {[
                    { label: 'ID Contato',    right: false },
                    { label: 'Pedido',        right: false },
                    { label: 'Data Compra',   right: false },
                    { label: 'Valor',         right: true  },
                    { label: 'Abertura Email',right: false },
                    { label: 'Envio SMS',     right: false },
                    { label: 'Canal',         right: false },
                    { label: 'Campanha Deveria Atribuir', right: false },
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
                {data.items.map((row, i) => (
                  <tr key={i} className={i % 2 === 0 ? 'bg-white' : 'bg-slate-50'}>
                    <td className="whitespace-nowrap px-3 py-2 font-mono text-xs text-slate-500">{row.contact_id ?? '-'}</td>
                    <td className="whitespace-nowrap px-3 py-2 font-mono text-xs text-slate-500">{row.order_id ?? '-'}</td>
                    <td className="whitespace-nowrap px-3 py-2 text-slate-700">{row.data_compra ?? '-'}</td>
                    <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums font-medium text-slate-900">
                      {formatCurrency(row.valor_pedido)}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-slate-600">{row.email_open_date ?? '-'}</td>
                    <td className="whitespace-nowrap px-3 py-2 text-slate-600">{row.sms_send_date ?? '-'}</td>
                    <td className="whitespace-nowrap px-3 py-2">
                      {row.canal_deveria_atribuir ? (
                        <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${CANAL_BADGE[row.canal_deveria_atribuir] ?? 'bg-slate-100 text-slate-600'}`}>
                          {row.canal_deveria_atribuir === 'email' ? 'Email' : 'SMS'}
                        </span>
                      ) : '-'}
                    </td>
                    <td
                      className="max-w-xs truncate px-3 py-2 text-xs text-slate-600"
                      title={row.campanha_deveria_atribuir ?? undefined}
                    >
                      {row.campanha_deveria_atribuir ?? '-'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  )
}

function AuditoriaCruzamento({ cruzamento }) {
  const {
    total_iplace, total_pedidos_iplace,
    atribuida_receita, atribuida_pedidos_valor, atribuida_pedidos,
    deveria_atribuir, deveria_atribuir_pedidos,
    nao_crm, nao_crm_pedidos,
  } = cruzamento

  const pctAtribuida = total_iplace > 0 ? ((atribuida_receita / total_iplace) * 100).toFixed(1) : '0.0'
  const pctDeveria = total_iplace > 0 ? ((deveria_atribuir / total_iplace) * 100).toFixed(1) : '0.0'
  const pctNaoCrm = total_iplace > 0 ? ((nao_crm / total_iplace) * 100).toFixed(1) : '0.0'

  const boxes = [
    {
      num: '1',
      title: 'Total iPlace',
      desc: 'Todas as vendas do período (si_purchases)',
      valor: total_iplace,
      pedidos: total_pedidos_iplace,
      pct: null,
      border: 'border-slate-300',
      bg: 'bg-slate-50',
      text: 'text-slate-600',
      sub: null,
    },
    {
      num: '2',
      title: 'Atribuída pelo Emarsys',
      desc: 'attributed_amount > 0 em revenue_attribution',
      valor: atribuida_receita,
      pedidos: atribuida_pedidos,
      pct: pctAtribuida,
      border: 'border-emerald-200',
      bg: 'bg-emerald-50',
      text: 'text-emerald-700',
      sub: `Valor dos pedidos: ${formatCurrency(atribuida_pedidos_valor)}`,
    },
    {
      num: '3',
      title: 'Deveria ter atribuído',
      desc: 'Sem atribuição, mas contato teve email open ou SMS send nos 7 dias anteriores à compra',
      valor: deveria_atribuir,
      pedidos: deveria_atribuir_pedidos,
      pct: pctDeveria,
      border: 'border-amber-200',
      bg: 'bg-amber-50',
      text: 'text-amber-700',
      sub: 'Valor dos pedidos — gap potencial de atribuição',
    },
    {
      num: '4',
      title: 'Não CRM',
      desc: 'Sem touchpoint CRM na janela de 7 dias — receita genuinamente não gerada por CRM',
      valor: nao_crm,
      pedidos: nao_crm_pedidos,
      pct: pctNaoCrm,
      border: 'border-slate-200',
      bg: 'bg-white',
      text: 'text-slate-500',
      sub: 'Valor dos pedidos',
    },
  ]

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft md:p-6">
      <h2 className="mb-1 text-sm font-semibold uppercase tracking-wide text-slate-500">
        Cruzamento de Atribuição — Visão Geral
      </h2>
      <p className="mb-5 text-xs text-slate-400">
        Caixa 2: receita creditada pelo Emarsys (attributed_amount). Caixas 3 e 4: valor bruto dos pedidos de si_purchases.
        Janela: 7 dias antes da compra · Touchpoints: email open + SMS send.
      </p>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {boxes.map((box) => (
          <div key={box.num} className={`rounded-xl border ${box.border} ${box.bg} p-4`}>
            <div className="mb-2 flex items-center gap-2">
              <span className={`flex h-5 w-5 items-center justify-center rounded-full text-xs font-bold ${box.bg} border ${box.border} ${box.text}`}>
                {box.num}
              </span>
              <p className={`text-xs font-semibold uppercase tracking-wide ${box.text}`}>{box.title}</p>
            </div>
            <p className="text-xl font-bold text-slate-900">{formatCurrency(box.valor)}</p>
            <p className={`mt-0.5 text-xs ${box.text}`}>
              {box.pedidos.toLocaleString('pt-BR')} pedidos
              {box.pct != null && ` · ${box.pct}% do total`}
            </p>
            {box.sub && <p className="mt-1.5 text-xs text-slate-400">{box.sub}</p>}
            <p className="mt-2 text-xs leading-snug text-slate-400">{box.desc}</p>
          </div>
        ))}
      </div>
    </section>
  )
}

export default function AuditoriaPage() {
  const defaults = getDefaultDates()
  const [startDate, setStartDate] = useState(defaults.start)
  const [endDate, setEndDate] = useState(defaults.end)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [data, setData] = useState(null)

  const handleAtualizar = useCallback(async () => {
    if (!startDate) return
    setLoading(true)
    setError('')
    setData(null)

    try {
      const params = new URLSearchParams({ start: startDate, ...(endDate ? { end: endDate } : {}) })
      const [discrepancia, cruzamento] = await Promise.all([
        fetchJson(`/api/open-data/emarsys/audit-discrepancia?${params}`),
        fetchJson(`/api/open-data/emarsys/audit-cruzamento?${params}`),
      ])

      if (!discrepancia.ok || !cruzamento.ok) {
        const msg = (!discrepancia.ok && discrepancia.error) || (!cruzamento.ok && cruzamento.error)
        setError(msg || 'Falha ao carregar dados de auditoria.')
        return
      }

      setData({
        discrepancia: discrepancia.data?.items ?? [],
        cruzamento: cruzamento.data?.totais ?? null,
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Falha ao carregar dados.')
    } finally {
      setLoading(false)
    }
  }, [startDate, endDate])

  const canalLabel = (v) => CANAL_LABELS[v] ?? v ?? '-'

  const discrepanciaCols = [
    { key: 'data_pedido', label: 'Data' },
    { key: 'canal', label: 'Canal', format: canalLabel },
    { key: 'campaign_id', label: 'Campanha ID' },
    { key: 'tipo_engajamento', label: 'Engajamento' },
    { key: 'valor_pedido', label: 'Valor Pedido', right: true, format: formatCurrency },
    { key: 'valor_atribuido', label: 'Valor Atribuído', right: true, format: formatCurrency },
  ]

  return (
    <div className="mx-auto max-w-7xl px-4 py-8 md:px-6 lg:px-8">
      <h1 className="mb-6 text-xl font-bold text-slate-900">Auditoria</h1>

      {/* Filtro de período */}
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

      {!data && !loading && (
        <p className="text-sm text-slate-500">Selecione o período e clique em Atualizar.</p>
      )}

      {data && (
        <div className="flex flex-col gap-6">
          {/* Cruzamento geral si_purchases × revenue_attribution */}
          {data.cruzamento && (
            <AuditoriaCruzamento cruzamento={data.cruzamento} />
          )}

          {/* Detalhamento lazy dos pedidos que deveriam ter sido atribuídos */}
          {data.cruzamento && (
            <DetalheDeviaAtribuir startDate={startDate} endDate={endDate} />
          )}

          <SectionCard
            title="Atribuição sem Valor"
            badge={data.discrepancia.length}
            description="Pedidos com tratamento registrado pelo Emarsys mas com valor atribuído igual a zero. Podem indicar registros incompletos ou falha de atribuição."
          >
            <Table
              columns={discrepanciaCols}
              rows={data.discrepancia}
              emptyText="Nenhum caso encontrado no período."
            />
          </SectionCard>
        </div>
      )}
    </div>
  )
}
