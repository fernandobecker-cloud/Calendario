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

const CATEGORIA_CONFIG = {
  marketing:    { label: 'Marketing',       bg: 'bg-emerald-50',  text: 'text-emerald-700', border: 'border-emerald-200', dot: 'bg-emerald-500' },
  transacional: { label: 'Transacional',    bg: 'bg-amber-50',    text: 'text-amber-700',   border: 'border-amber-200',   dot: 'bg-amber-400'   },
  nps:          { label: 'NPS / Pesquisa',  bg: 'bg-blue-50',     text: 'text-blue-700',    border: 'border-blue-200',    dot: 'bg-blue-400'    },
  servico:      { label: 'Serviço / AT',    bg: 'bg-slate-50',    text: 'text-slate-600',   border: 'border-slate-200',   dot: 'bg-slate-400'   },
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

      {/* Barra de composição: marketing sobre total CRM */}
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

      {/* Cards principais */}
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

      {/* Detalhamento por categoria */}
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
  const [filtroCategoria, setFiltroCategoria] = useState('todos')

  const handleAtualizar = useCallback(async () => {
    if (!startDate) return
    setLoading(true)
    setError('')
    setData(null)

    try {
      const params = new URLSearchParams({ start: startDate, ...(endDate ? { end: endDate } : {}) })
      const [discrepancia, campanha, cruzamento] = await Promise.all([
        fetchJson(`/api/open-data/emarsys/audit-discrepancia?${params}`),
        fetchJson(`/api/open-data/emarsys/audit-receita-por-campanha?${params}`),
        fetchJson(`/api/open-data/emarsys/audit-cruzamento?${params}`),
      ])

      if (!discrepancia.ok || !campanha.ok || !cruzamento.ok) {
        const msg = (!discrepancia.ok && discrepancia.error) ||
          (!campanha.ok && campanha.error) ||
          (!cruzamento.ok && cruzamento.error)
        setError(msg || 'Falha ao carregar dados de auditoria.')
        return
      }

      setData({
        discrepancia: discrepancia.data?.items ?? [],
        campanha: campanha.data?.items ?? [],
        totais: campanha.data?.totais ?? null,
        resumoPorCategoria: campanha.data?.resumo_por_categoria ?? [],
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

  const campanhaCols = [
    { key: 'categoria', label: 'Tipo', format: (v) => <CategoriaBadge categoria={v} /> },
    { key: 'canal', label: 'Canal', format: canalLabel },
    { key: 'nome_campanha', label: 'Campanha' },
    { key: 'campaign_id', label: 'ID' },
    { key: 'pedidos_atribuidos', label: 'Pedidos', right: true },
    { key: 'compradores_unicos', label: 'Compradores', right: true },
    { key: 'receita_atribuida', label: 'Receita Atribuída', right: true, format: formatCurrency },
  ]

  const campanhasFiltradas = data
    ? (filtroCategoria === 'todos' ? data.campanha : data.campanha.filter((r) => r.categoria === filtroCategoria))
    : []

  const categorias = [
    { key: 'todos', label: 'Todos' },
    { key: 'marketing', label: 'Marketing' },
    { key: 'transacional', label: 'Transacional' },
    { key: 'nps', label: 'NPS / Pesquisa' },
    { key: 'servico', label: 'Serviço / AT' },
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

          {/* Resumo comparativo */}
          {data.totais && (
            <ResumoAtribuicao totais={data.totais} resumoPorCategoria={data.resumoPorCategoria} />
          )}

          {/* Receita por Campanha */}
          <SectionCard
            title="Receita por Campanha"
            badge={data.campanha.length}
            badgeColor="bg-slate-100 text-slate-700"
            description="Receita atribuída agrupada por campanha e canal, ordenada por maior receita. Top 200."
          >
            {/* Filtro de categoria */}
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
                  {c.key !== 'todos' && data.campanha.filter((r) => r.categoria === c.key).length > 0 && (
                    <span className="ml-1 opacity-60">
                      ({data.campanha.filter((r) => r.categoria === c.key).length})
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
          </SectionCard>

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
