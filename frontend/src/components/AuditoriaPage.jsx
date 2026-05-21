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

function fmt(v) { return v == null ? '—' : Number(v).toLocaleString('pt-BR') }
function fmtPct(v) { return v == null ? '—' : `${Number(v).toLocaleString('pt-BR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%` }
function fmtCur(v) { return v == null ? '—' : new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(Number(v)) }

function SemTreatmentDiagnostico() {
  const [state, setState] = useState({ data: null, loading: false, error: '' })

  const handleCarregar = async () => {
    setState({ data: null, loading: true, error: '' })
    try {
      const res = await fetchJson('/api/open-data/emarsys/audit-sem-treatment')
      if (!res.ok) { setState({ data: null, loading: false, error: res.error || 'Erro.' }); return }
      setState({ data: res.data, loading: false, error: '' })
    } catch (e) {
      setState({ data: null, loading: false, error: e.message || 'Erro.' })
    }
  }

  const { data, loading, error } = state
  const est = data?.estados || {}
  const cron = data?.cronologia || {}
  const sip = data?.si_purchases || {}
  const errs = data?.errors || {}

  // Derived conclusion
  const pctAmbos = Number(est.pct_aparece_nas_duas || 0)
  const pctSemAntes = Number(cron.pct_sem_antes || 0)
  const pctNaoEncontrado = sip.total_apenas_sem_treatment > 0
    ? (100 - Number(sip.pct_em_si_purchases || 0)).toFixed(1)
    : null

  let conclusao = null
  if (data && !errs.estados && !errs.cronologia) {
    if (pctAmbos < 5 && pctSemAntes < 20) {
      conclusao = {
        tipo: 'nao-crm',
        texto: 'Os 91% sem treatment são pedidos PERMANENTEMENTE sem atribuição CRM — compradores que não interagiram com nenhuma campanha na janela de atribuição. Não é processamento pendente.',
        cor: 'border-slate-300 bg-slate-50 text-slate-700',
      }
    } else if (pctSemAntes > 60) {
      conclusao = {
        tipo: 'pendente',
        texto: `${cron.pct_sem_antes}% das ordens aparecem sem treatment ANTES de receber treatment — são registros intermediários de processamento (estado "pendente" que depois recebe atribuição). O dado final é o com treatment.`,
        cor: 'border-amber-300 bg-amber-50 text-amber-800',
      }
    } else {
      conclusao = {
        tipo: 'misto',
        texto: 'Resultado misto: parte é processamento pendente, parte é pedido sem atribuição CRM permanente. Ver métricas abaixo para dimensionar cada grupo.',
        cor: 'border-blue-200 bg-blue-50 text-blue-800',
      }
    }
  }

  return (
    <section className="rounded-2xl border border-slate-300 bg-white p-5 shadow-soft md:p-6">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-600">
            Diagnóstico — Orders sem Treatments em revenue_attribution
          </h2>
          <p className="mt-1 text-xs text-slate-400">
            Três queries (últimos 90 dias): distribuição de estados, ordem cronológica e
            sobreposição com si_purchases. Responde se são pedidos pendentes ou não-CRM permanentes.
          </p>
        </div>
        <button
          onClick={handleCarregar}
          disabled={loading}
          className="rounded-lg bg-slate-700 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-900 disabled:opacity-50"
        >
          {loading ? 'Consultando BQ...' : data ? 'Rerodar' : 'Rodar diagnóstico'}
        </button>
      </div>

      {error && <p className="mb-4 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</p>}
      {!data && !loading && <p className="text-sm text-slate-500">Clique em "Rodar diagnóstico" — 3 queries em paralelo (~30–60 s).</p>}

      {data && (
        <div className="space-y-5">

          {/* Conclusão automática */}
          {conclusao && (
            <div className={`rounded-xl border px-4 py-3 text-sm font-medium ${conclusao.cor}`}>
              {conclusao.texto}
            </div>
          )}

          {/* Bloco 1 — estados */}
          <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
            <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-600">
              1 — Distribuição de estados por order_id (90 dias)
            </p>
            {errs.estados
              ? <p className="text-xs text-rose-600">{errs.estados}</p>
              : (
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
                  {[
                    { label: 'order_ids únicos', value: fmt(est.total_order_ids) },
                    { label: 'APENAS sem treatment', value: fmt(est.apenas_sem_treatment), pct: est.pct_apenas_sem, hi: Number(est.pct_apenas_sem) > 50 },
                    { label: 'APENAS com treatment', value: fmt(est.apenas_com_treatment), pct: est.pct_apenas_com },
                    { label: 'Aparece nas DUAS situações', value: fmt(est.aparece_nas_duas_situacoes), pct: est.pct_aparece_nas_duas, hi: Number(est.pct_aparece_nas_duas) > 10, good: true },
                  ].map((s) => (
                    <div key={s.label} className={`rounded-lg border p-3 ${s.hi ? (s.good ? 'border-amber-200 bg-amber-50' : 'border-rose-200 bg-rose-50') : 'border-slate-200 bg-white'}`}>
                      <p className="text-xs text-slate-500">{s.label}</p>
                      <p className="mt-0.5 text-xl font-bold text-slate-900">{s.value}</p>
                      {s.pct != null && <p className="text-xs text-slate-400">{fmtPct(s.pct)}</p>}
                    </div>
                  ))}
                </div>
              )
            }
            <p className="mt-2 text-xs text-slate-400">
              Se "aparece nas duas" for {'<'} 5% → os sem-treatment são grupo separado (não CRM). Se {'>'} 30% → muitos são estados intermediários de processamento.
            </p>
          </div>

          {/* Bloco 2 — cronologia */}
          <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
            <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-600">
              2 — Cronologia: order_ids que aparecem nas duas situações (sem → com treatment)
            </p>
            {errs.cronologia
              ? <p className="text-xs text-rose-600">{errs.cronologia}</p>
              : (
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  {[
                    { label: 'Total com ambas situações', value: fmt(cron.total_ambos) },
                    { label: 'Sem aparece ANTES do com', value: fmt(cron.sem_aparece_antes_do_com), pct: cron.pct_sem_antes, hi: Number(cron.pct_sem_antes) > 60 },
                    { label: 'Sem e com na MESMA partição', value: fmt(cron.sem_e_com_mesma_particao), pct: cron.pct_mesma_particao },
                    { label: 'Sem aparece DEPOIS do com', value: fmt(cron.sem_aparece_depois_do_com) },
                    { label: 'Média de dias até receber treatment', value: cron.media_dias_ate_receber_treatment != null ? `${Number(cron.media_dias_ate_receber_treatment).toLocaleString('pt-BR', { maximumFractionDigits: 1 })} dias` : '—' },
                  ].map((s) => (
                    <div key={s.label} className={`rounded-lg border p-3 ${s.hi ? 'border-amber-200 bg-amber-50' : 'border-slate-200 bg-white'}`}>
                      <p className="text-xs text-slate-500">{s.label}</p>
                      <p className="mt-0.5 text-xl font-bold text-slate-900">{s.value}</p>
                      {s.pct != null && <p className="text-xs text-slate-400">{fmtPct(s.pct)}</p>}
                    </div>
                  ))}
                </div>
              )
            }
            <p className="mt-2 text-xs text-slate-400">
              Se "sem aparece antes" {'>'} 80% e média de dias for {'>'} 0 → o registro sem-treatment é estado intermediário (processamento pendente). Se for 0 dias ou mesma partição → co-existência permanente.
            </p>
          </div>

          {/* Bloco 3 — si_purchases overlap */}
          <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
            <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-600">
              3 — Orders APENAS sem treatment: existem em si_purchases? (30 dias)
            </p>
            {errs.si_purchases
              ? <p className="text-xs text-rose-600">{errs.si_purchases}</p>
              : (
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  {[
                    { label: 'Total apenas sem treatment', value: fmt(sip.total_apenas_sem_treatment) },
                    { label: 'Encontrados em si_purchases', value: fmt(sip.encontrados_em_si_purchases), pct: sip.pct_em_si_purchases },
                    { label: 'NÃO encontrados em si_purchases', value: fmt(sip.nao_encontrados_em_si_purchases), hi: Number(sip.nao_encontrados_em_si_purchases) > 0, pct: pctNaoEncontrado },
                  ].map((s) => (
                    <div key={s.label} className={`rounded-lg border p-3 ${s.hi ? 'border-amber-200 bg-amber-50' : 'border-slate-200 bg-white'}`}>
                      <p className="text-xs text-slate-500">{s.label}</p>
                      <p className="mt-0.5 text-xl font-bold text-slate-900">{s.value}</p>
                      {s.pct != null && <p className="text-xs text-slate-400">{fmtPct(s.pct)}</p>}
                    </div>
                  ))}
                </div>
              )
            }
            <p className="mt-2 text-xs text-slate-400">
              Se {'>'} 95% estão em si_purchases → são compras reais (pedidos genuínos sem touchpoint CRM).
              Se muitos NÃO estão em si_purchases → podem ser registros de teste, cancelamentos ou pedidos de outras fontes.
            </p>
          </div>

        </div>
      )}
    </section>
  )
}

function SchemaDiagnostico() {
  const [state, setState] = useState({ data: null, loading: false, error: '' })

  const handleCarregar = async () => {
    setState({ data: null, loading: true, error: '' })
    try {
      const res = await fetchJson('/api/open-data/emarsys/schema-diagnostico')
      if (!res.ok) { setState({ data: null, loading: false, error: res.error || 'Erro.' }); return }
      setState({ data: res.data, loading: false, error: '' })
    } catch (e) {
      setState({ data: null, loading: false, error: e.message || 'Erro.' })
    }
  }

  const { data, loading, error } = state
  const c = data?.contact_id_diagnostico || {}
  const o = data?.order_id_diagnostico || {}
  const a = data?.attributed_diagnostico || {}
  const errs = data?.errors || {}

  return (
    <section className="rounded-2xl border border-violet-200 bg-white p-5 shadow-soft md:p-6">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wide text-violet-700">
            Diagnóstico de Schema
          </h2>
          <p className="mt-1 text-xs text-slate-400">
            Valida 3 hipóteses sobre a estrutura das tabelas Emarsys: contact_id nulo em si_contacts,
            unicidade de order_id em revenue_attribution e relação attributed_amount vs sales_amount.
          </p>
        </div>
        <button
          onClick={handleCarregar}
          disabled={loading}
          className="rounded-lg bg-violet-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-violet-700 disabled:opacity-50"
        >
          {loading ? 'Consultando BQ...' : data ? 'Rerodar' : 'Rodar diagnóstico'}
        </button>
      </div>

      {error && <p className="mb-4 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</p>}
      {!data && !loading && <p className="text-sm text-slate-500">Clique em "Rodar diagnóstico" — as 3 queries rodam em paralelo (~30–60 s).</p>}

      {data && (
        <div className="space-y-6">

          {/* Pergunta 1 — contact_id nulo em si_contacts */}
          <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
            <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-600">
              Pergunta 1 — contact_id nulo em si_contacts
            </p>
            {errs.contact_id
              ? <p className="text-xs text-rose-600">{errs.contact_id}</p>
              : (
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  {[
                    { label: 'Total de linhas',          value: fmt(c.total_rows) },
                    { label: 'contact_id NULO',          value: fmt(c.contact_id_null), highlight: Number(c.contact_id_null) > 0 },
                    { label: 'contact_id preenchido',    value: fmt(c.contact_id_preenchido) },
                    { label: '% nulo',                   value: fmtPct(c.pct_null), highlight: Number(c.pct_null) > 0 },
                    { label: 'Nulo mas tem external_id', value: fmt(c.null_mas_tem_external_id) },
                    { label: 'Nulo e sem external_id',   value: fmt(c.null_e_sem_external_id), highlight: Number(c.null_e_sem_external_id) > 0 },
                    { label: 'si_contact_ids distintos sem contact_id', value: fmt(c.distinct_si_contact_sem_contact_id) },
                  ].map((s) => (
                    <div key={s.label} className={`rounded-lg border p-3 ${s.highlight ? 'border-amber-200 bg-amber-50' : 'border-slate-200 bg-white'}`}>
                      <p className="text-xs text-slate-500">{s.label}</p>
                      <p className={`mt-0.5 text-lg font-bold ${s.highlight ? 'text-amber-800' : 'text-slate-900'}`}>{s.value}</p>
                    </div>
                  ))}
                </div>
              )
            }
            <div className="mt-3 rounded-lg bg-white border border-slate-200 p-3 text-xs text-slate-500 leading-relaxed">
              <strong className="text-slate-700">Interpretação:</strong>{' '}
              Se <em>% nulo {'>'} 0</em> e <em>nulo mas tem external_id {'>'} 0</em> → esses contatos existem no Emarsys
              mas o campo <code>contact_id</code> não foi populado na tabela Open Data; o join
              <code> revenue_attribution.contact_id → si_contacts.contact_id</code> não vai encontrá-los.
              Se <em>nulo e sem external_id {'>'} 0</em> → não há outra chave disponível para cruzamento.
            </div>
          </div>

          {/* Pergunta 2 — unicidade order_id em revenue_attribution */}
          <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
            <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-600">
              Pergunta 2 — unicidade de order_id em revenue_attribution (últimos 30 dias)
            </p>
            {errs.order_id
              ? <p className="text-xs text-rose-600">{errs.order_id}</p>
              : (
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  {[
                    { label: 'order_ids distintos',           value: fmt(o.distinct_order_ids) },
                    { label: 'Com 1 linha (único)',           value: fmt(o.orders_uma_linha) },
                    { label: 'Com múltiplas linhas',          value: fmt(o.orders_multiplas_linhas), highlight: Number(o.orders_multiplas_linhas) > 0 },
                    { label: 'Máx linhas por order_id',       value: fmt(o.max_linhas_por_order), highlight: Number(o.max_linhas_por_order) > 1 },
                    { label: 'Com múltiplos treatments',      value: fmt(o.orders_com_multiplos_treatments) },
                    { label: 'Máx treatments por order',      value: fmt(o.max_treatments_por_order) },
                    { label: 'Média treatments por order',    value: fmt(o.media_treatments_por_order) },
                  ].map((s) => (
                    <div key={s.label} className={`rounded-lg border p-3 ${s.highlight ? 'border-amber-200 bg-amber-50' : 'border-slate-200 bg-white'}`}>
                      <p className="text-xs text-slate-500">{s.label}</p>
                      <p className={`mt-0.5 text-lg font-bold ${s.highlight ? 'text-amber-800' : 'text-slate-900'}`}>{s.value}</p>
                    </div>
                  ))}
                </div>
              )
            }
            <div className="mt-3 rounded-lg bg-white border border-slate-200 p-3 text-xs text-slate-500 leading-relaxed">
              <strong className="text-slate-700">Interpretação:</strong>{' '}
              Se <em>com múltiplas linhas {'>'} 0</em> → o mesmo order_id aparece em mais de uma partição (re-processamento);
              o <code>GROUP BY order_id</code> atual com <code>MAX()</code> já trata isso.
              <em> Treatments</em> dentro do array são as campanhas que contribuíram para aquele pedido —
              múltiplos treatments = atribuição multi-campanha no mesmo pedido.
            </div>
          </div>

          {/* Pergunta 3 — attributed_amount vs sales_amount */}
          <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
            <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-600">
              Pergunta 3 — attributed_amount vs SUM(sales_amount) por order_id (últimos 30 dias)
            </p>
            {errs.attributed
              ? <p className="text-xs text-rose-600">{errs.attributed}</p>
              : (
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  {[
                    { label: 'Total orders comparados',          value: fmt(a.total_orders) },
                    { label: 'attributed == total (Δ < R$0,02)', value: fmt(a.attributed_igual_total) },
                    { label: 'attributed parcial (até 5%)',       value: fmt(a.attributed_parcial_ate_5pct), highlight: Number(a.attributed_parcial_ate_5pct) > 0 },
                    { label: 'attributed difere > 5%',           value: fmt(a.attributed_difere_mais_5pct), highlight: Number(a.attributed_difere_mais_5pct) > 0 },
                    { label: 'Orders multi-campanha',            value: fmt(a.orders_multi_campanha) },
                    { label: 'Máx campanhas por order',          value: fmt(a.max_campanhas_por_order) },
                    { label: 'Média % atribuído vs total',       value: fmtPct(a.media_pct_atribuido_vs_total) },
                    { label: 'Média valor atribuído',            value: fmtCur(a.media_valor_atribuido) },
                    { label: 'Média valor total (si_purchases)', value: fmtCur(a.media_valor_total) },
                    { label: 'Orders sem si_purchases',          value: fmt(a.orders_sem_si_purchases), highlight: Number(a.orders_sem_si_purchases) > 0 },
                  ].map((s) => (
                    <div key={s.label} className={`rounded-lg border p-3 ${s.highlight ? 'border-amber-200 bg-amber-50' : 'border-slate-200 bg-white'}`}>
                      <p className="text-xs text-slate-500">{s.label}</p>
                      <p className={`mt-0.5 text-lg font-bold ${s.highlight ? 'text-amber-800' : 'text-slate-900'}`}>{s.value}</p>
                    </div>
                  ))}
                </div>
              )
            }
            <div className="mt-3 rounded-lg bg-white border border-slate-200 p-3 text-xs text-slate-500 leading-relaxed">
              <strong className="text-slate-700">Interpretação:</strong>{' '}
              Se <em>attributed == total</em> = maioria → o Emarsys atribui o valor integral do pedido
              (não uma fração da campanha). Se <em>difere {'>'} 5%</em> for significativo →
              <code>attributed_amount</code> é uma fração — usar <code>SUM(sales_amount)</code>
              de si_purchases para o valor real do pedido.
              <em> Multi-campanha</em> = pedido contabilizado em mais de um treatment.
            </div>
          </div>

        </div>
      )}
    </section>
  )
}

function CruzamentoOrderId({ startDate, endDate }) {
  const [state, setState] = useState({ data: null, loading: false, error: '' })
  const [limit, setLimit] = useState(1000)

  const handleCarregar = async () => {
    setState({ data: null, loading: true, error: '' })
    try {
      const params = new URLSearchParams({ start: startDate, end: endDate, limit: String(limit) })
      const res = await fetchJson(`/api/open-data/emarsys/audit-order-cruzamento?${params}`)
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
    const fmtNum = (v) =>
      v == null ? '' : new Intl.NumberFormat('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(Number(v))
    const cols = [
      { key: 'order_id',        label: 'Numero Pedido' },
      { key: 'data_atribuicao', label: 'Data Atribuicao' },
      { key: 'data_compra',     label: 'Data Compra' },
      { key: 'canal',           label: 'Canal' },
      { key: 'status_pedido',   label: 'Status Pedido' },
      { key: 'valor_atribuido', label: 'Valor Atribuido (R$)', fmt: fmtNum },
      { key: 'valor_total',     label: 'Valor Pedido Total (R$)', fmt: fmtNum },
      { key: 'vlr_captados',    label: 'Vlr Pedidos Captados (R$)', fmt: fmtNum },
      { key: 'cruzado',         label: 'Cruzado vendas_iplace', fmt: (v) => v ? 'Sim' : 'Nao' },
    ]
    const esc = (v) => {
      if (v == null) return ''
      const s = String(v)
      return s.includes(',') || s.includes('"') || s.includes('\n') ? `"${s.replace(/"/g, '""')}"` : s
    }
    const csv = '﻿' + [
      cols.map((c) => c.label).join(','),
      ...items.map((r) => cols.map((c) => esc(c.fmt ? c.fmt(r[c.key]) : r[c.key])).join(',')),
    ].join('\n')
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `cruzamento-order-id-${startDate}-${endDate}.csv`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  const { data, loading, error } = state

  return (
    <section className="rounded-2xl border border-indigo-200 bg-white p-5 shadow-soft md:p-6">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wide text-indigo-700">
            Cruzamento order_id × Número Pedido
          </h2>
          <p className="mt-1 text-xs text-slate-400">
            Pedidos atribuídos pelo Emarsys (revenue_attribution) cruzados com vendas_iplace —
            compara valor atribuído, valor total (si_purchases) e Vlr_Pedidos_Captados.
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <label className="flex items-center gap-1 text-xs text-slate-500">
            Limite
            <select
              value={limit}
              onChange={(e) => setLimit(Number(e.target.value))}
              className="rounded-md border border-slate-300 px-2 py-1 text-xs text-slate-800"
            >
              {[500, 1000, 2000, 5000].map((v) => (
                <option key={v} value={v}>{v.toLocaleString('pt-BR')}</option>
              ))}
            </select>
          </label>
          <button
            onClick={handleCarregar}
            disabled={loading}
            className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-indigo-700 disabled:opacity-50"
          >
            {loading ? 'Carregando...' : data ? 'Recarregar' : 'Carregar cruzamento'}
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
        <p className="text-sm text-slate-500">Clique em "Carregar cruzamento" para ver os dados.</p>
      )}

      {data && (
        <>
          {/* Resumo */}
          <div className="mb-5 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
            {[
              { label: 'Pedidos atribuídos', value: data.total?.toLocaleString('pt-BR'), sub: `${data.cruzados} cruzados com vendas_iplace` },
              { label: 'Valor Atribuído', value: formatCurrency(data.total_valor_atribuido), sub: 'revenue_attribution' },
              { label: 'Valor Total Pedido', value: formatCurrency(data.total_valor_total), sub: 'si_purchases' },
              { label: 'Vlr Captados', value: formatCurrency(data.total_vlr_captados), sub: 'vendas_iplace' },
              {
                label: 'Δ Atribuído vs Total',
                value: formatCurrency(data.total_valor_total - data.total_valor_atribuido),
                sub: 'diferença por pedido',
                highlight: true,
              },
            ].map((s) => (
              <div key={s.label} className={`rounded-xl border p-3 ${s.highlight ? 'border-amber-200 bg-amber-50' : 'border-slate-200 bg-slate-50'}`}>
                <p className="text-xs text-slate-500">{s.label}</p>
                <p className={`mt-0.5 text-lg font-bold ${s.highlight ? 'text-amber-800' : 'text-slate-900'}`}>{s.value}</p>
                <p className="text-xs text-slate-400">{s.sub}</p>
              </div>
            ))}
          </div>

          {/* Tabela */}
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200">
                  {[
                    { label: 'Número Pedido', right: false },
                    { label: 'Data Atrib.', right: false },
                    { label: 'Data Compra', right: false },
                    { label: 'Canal', right: false },
                    { label: 'Status', right: false },
                    { label: 'Vlr Atribuído', right: true },
                    { label: 'Vlr Total Pedido', right: true },
                    { label: 'Vlr Captados', right: true },
                    { label: 'Δ Atrib. vs Total', right: true },
                  ].map((col, i) => (
                    <th key={i} className={`whitespace-nowrap px-3 py-2 text-xs font-semibold uppercase tracking-wide text-slate-500 ${col.right ? 'text-right' : 'text-left'}`}>
                      {col.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.items.map((row, i) => {
                  const delta = (row.valor_total || 0) - (row.valor_atribuido || 0)
                  return (
                    <tr key={i} className={i % 2 === 0 ? 'bg-white' : 'bg-slate-50'}>
                      <td className="whitespace-nowrap px-3 py-2 font-mono text-xs text-slate-600">
                        {row.order_id || '-'}
                        {!row.cruzado && <span className="ml-1 rounded bg-slate-100 px-1 py-0.5 text-xs text-slate-400">sem cruzamento</span>}
                      </td>
                      <td className="whitespace-nowrap px-3 py-2 text-slate-600">{row.data_atribuicao || '-'}</td>
                      <td className="whitespace-nowrap px-3 py-2 text-slate-600">{row.data_compra || '-'}</td>
                      <td className="whitespace-nowrap px-3 py-2 text-slate-600">{row.canal || '-'}</td>
                      <td className="whitespace-nowrap px-3 py-2 text-slate-500 text-xs">{row.status_pedido || '-'}</td>
                      <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums font-medium text-indigo-700">{formatCurrency(row.valor_atribuido)}</td>
                      <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums font-medium text-slate-900">{formatCurrency(row.valor_total)}</td>
                      <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums text-slate-700">{row.vlr_captados ? formatCurrency(row.vlr_captados) : '-'}</td>
                      <td className={`whitespace-nowrap px-3 py-2 text-right tabular-nums font-semibold ${delta > 0 ? 'text-emerald-700' : delta < 0 ? 'text-rose-700' : 'text-slate-500'}`}>
                        {formatCurrency(delta)}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          {data.total >= limit && (
            <p className="mt-3 text-xs text-slate-400">
              Exibindo os {limit.toLocaleString('pt-BR')} pedidos de maior valor atribuído — aumente o limite ou use a exportação para ver todos.
            </p>
          )}
        </>
      )}
    </section>
  )
}

function AttributionByDayChart({ items }) {
  if (!items || items.length === 0) return null

  const totalPedidos = items.reduce((s, r) => s + Number(r.pedidos || 0), 0)
  const totalReceita = items.reduce((s, r) => s + Number(r.receita || 0), 0)
  const maxPctPedidos = Math.max(...items.map((r) => (Number(r.pedidos) / totalPedidos) * 100))

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft md:p-6">
      <h2 className="mb-1 text-sm font-semibold uppercase tracking-wide text-slate-500">
        Distribuição da Atribuição por Dia
      </h2>
      <p className="mb-6 text-xs text-slate-400">
        % dos pedidos atribuídos pelo Emarsys por dia após o touchpoint (email open / SMS send) · Janela 0–7 dias
      </p>

      <div className="space-y-3">
        {items.map((row) => {
          const dia = Number(row.dia)
          const pedidos = Number(row.pedidos || 0)
          const receita = Number(row.receita || 0)
          const pctPedidos = totalPedidos > 0 ? (pedidos / totalPedidos) * 100 : 0
          const pctReceita = totalReceita > 0 ? (receita / totalReceita) * 100 : 0
          const barWidth = maxPctPedidos > 0 ? (pctPedidos / maxPctPedidos) * 100 : 0

          return (
            <div key={dia} className="flex items-center gap-3">
              <div className="w-20 shrink-0 text-right text-xs font-semibold text-slate-500">
                {dia === 0 ? 'Mesmo dia' : `Dia ${dia}`}
              </div>
              <div className="flex-1">
                <div className="relative h-7 overflow-hidden rounded-lg bg-slate-100">
                  <div
                    className="flex h-full items-center rounded-lg bg-emerald-500 px-2 transition-all duration-500"
                    style={{ width: `${Math.max(barWidth, 2)}%` }}
                  >
                    {barWidth > 18 && (
                      <span className="text-xs font-semibold text-white">{pctPedidos.toFixed(1)}%</span>
                    )}
                  </div>
                  {barWidth <= 18 && (
                    <span className="absolute left-2 top-1/2 -translate-y-1/2 text-xs font-semibold text-slate-600">
                      {pctPedidos.toFixed(1)}%
                    </span>
                  )}
                </div>
              </div>
              <div className="w-28 shrink-0 text-right text-xs text-slate-500">
                {pedidos.toLocaleString('pt-BR')} pedidos
              </div>
              <div className="w-24 shrink-0 text-right text-xs text-slate-400">
                {pctReceita.toFixed(1)}% receita
              </div>
            </div>
          )
        })}
      </div>

      <div className="mt-5 flex flex-wrap gap-6 border-t border-slate-100 pt-4">
        <div>
          <p className="text-xs text-slate-400">Total pedidos atribuídos</p>
          <p className="text-sm font-semibold text-slate-800">{totalPedidos.toLocaleString('pt-BR')}</p>
        </div>
        <div>
          <p className="text-xs text-slate-400">Total receita atribuída</p>
          <p className="text-sm font-semibold text-slate-800">{formatCurrency(totalReceita)}</p>
        </div>
      </div>
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
      const [discrepancia, cruzamento, atribuicaoPorDia] = await Promise.all([
        fetchJson(`/api/open-data/emarsys/audit-discrepancia?${params}`),
        fetchJson(`/api/open-data/emarsys/audit-cruzamento?${params}`),
        fetchJson(`/api/open-data/emarsys/audit-attribution-by-day?${params}`),
      ])

      if (!discrepancia.ok || !cruzamento.ok) {
        const msg = (!discrepancia.ok && discrepancia.error) || (!cruzamento.ok && cruzamento.error)
        setError(msg || 'Falha ao carregar dados de auditoria.')
        return
      }

      setData({
        discrepancia: discrepancia.data?.items ?? [],
        cruzamento: cruzamento.data?.totais ?? null,
        atribuicaoPorDia: atribuicaoPorDia.data?.items ?? [],
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

          {data.atribuicaoPorDia?.length > 0 && (
            <AttributionByDayChart items={data.atribuicaoPorDia} />
          )}

          {/* Detalhamento lazy dos pedidos que deveriam ter sido atribuídos */}
          {data.cruzamento && (
            <DetalheDeviaAtribuir startDate={startDate} endDate={endDate} />
          )}

          {/* Cruzamento order_id × Número Pedido (vendas_iplace) */}
          <CruzamentoOrderId startDate={startDate} endDate={endDate} />

          {/* Diagnóstico de schema das 3 tabelas */}
          <SchemaDiagnostico />

          {/* Diagnóstico — orders sem treatments */}
          <SemTreatmentDiagnostico />

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
