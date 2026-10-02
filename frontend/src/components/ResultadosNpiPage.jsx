import { useCallback, useEffect, useState } from 'react'

function formatCurrency(value) {
  if (value == null || isNaN(Number(value))) return '-'
  return new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(Number(value))
}

function extrairDetalheErro(payload) {
  const detail = payload?.detail
  if (!detail) return ''
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map((d) => d?.msg || JSON.stringify(d)).join('; ')
  return JSON.stringify(detail)
}

function formatarPeriodo(p) {
  const fmt = (d) => {
    const m = String(d || '').match(/^(\d{4})-(\d{2})-(\d{2})/)
    return m ? `${m[3]}/${m[2]}` : d
  }
  return `${fmt(p.start_date)} a ${fmt(p.end_date)}`
}

function CelulaValor({ isAdmin, valor, onSalvar }) {
  const [editando, setEditando] = useState(false)
  const [texto, setTexto] = useState(String(valor ?? 0))
  const [salvando, setSalvando] = useState(false)

  useEffect(() => {
    setTexto(String(valor ?? 0))
  }, [valor])

  if (!isAdmin) {
    return <td className="whitespace-nowrap px-4 py-2 text-right text-sm text-slate-700">{formatCurrency(valor ?? 0)}</td>
  }

  if (!editando) {
    return (
      <td
        onClick={() => setEditando(true)}
        title="Clique para editar"
        className="cursor-pointer whitespace-nowrap px-4 py-2 text-right text-sm text-slate-700 hover:bg-slate-100"
      >
        {formatCurrency(valor ?? 0)}
      </td>
    )
  }

  const confirmar = async () => {
    setSalvando(true)
    const novoValor = Number(String(texto).replace(',', '.')) || 0
    await onSalvar(novoValor)
    setSalvando(false)
    setEditando(false)
  }

  return (
    <td className="whitespace-nowrap px-2 py-1.5 text-right">
      <input
        autoFocus
        value={texto}
        onChange={(e) => setTexto(e.target.value)}
        onBlur={confirmar}
        onKeyDown={(e) => {
          if (e.key === 'Enter') e.currentTarget.blur()
          if (e.key === 'Escape') setEditando(false)
        }}
        disabled={salvando}
        inputMode="decimal"
        className="w-32 rounded-md border border-indigo-300 px-2 py-1 text-right text-sm text-slate-900"
      />
    </td>
  )
}

function NovoPeriodoForm({ onCriado, onCancelar }) {
  const [nome, setNome] = useState('')
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [salvando, setSalvando] = useState(false)
  const [erro, setErro] = useState('')

  const handleSubmit = useCallback(async (event) => {
    event.preventDefault()
    if (!nome.trim() || !start || !end) {
      setErro('Preencha nome, data inicial e data final.')
      return
    }
    setSalvando(true)
    setErro('')
    try {
      const res = await fetch('/api/open-data/npi/periodos', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ nome: nome.trim(), start_date: start, end_date: end }),
      })
      const payload = await res.json().catch(() => null)
      if (!res.ok) throw new Error(extrairDetalheErro(payload) || `HTTP ${res.status}`)
      onCriado()
    } catch (err) {
      setErro(err instanceof Error ? err.message : 'Erro ao criar período.')
    } finally {
      setSalvando(false)
    }
  }, [nome, start, end, onCriado])

  return (
    <form onSubmit={handleSubmit} className="mb-4 flex flex-wrap items-end gap-3 rounded-xl border border-slate-200 bg-slate-50 p-4">
      <label className="flex flex-col gap-1 text-sm text-slate-600">
        Nome do período
        <input
          value={nome}
          onChange={(e) => setNome(e.target.value)}
          placeholder="ex: 01 a 11/09"
          className="min-w-[180px] rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900"
        />
      </label>
      <label className="flex flex-col gap-1 text-sm text-slate-600">
        Data inicial
        <input type="date" value={start} onChange={(e) => setStart(e.target.value)} className="rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900" />
      </label>
      <label className="flex flex-col gap-1 text-sm text-slate-600">
        Data final
        <input type="date" value={end} onChange={(e) => setEnd(e.target.value)} className="rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900" />
      </label>
      <button type="submit" disabled={salvando} className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-700 disabled:opacity-50">
        {salvando ? 'Criando...' : 'Criar período'}
      </button>
      <button type="button" onClick={onCancelar} className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-100">
        Cancelar
      </button>
      {erro && <p className="w-full text-xs text-rose-600">{erro}</p>}
    </form>
  )
}

// Fetch + checkbox list dos templates do Omnichat - usado tanto pelo
// "Calcular automaticamente" quanto por "Ver abertura por regional/loja"
// (os dois precisam saber quais templates contam como disparo dessa
// campanha pra classificar o canal, ver calcular_npi_canal).
function TemplateSelector({ selecionados, onToggle }) {
  const [templatesDisponiveis, setTemplatesDisponiveis] = useState([])
  const [templatesLoading, setTemplatesLoading] = useState(true)
  const [templatesErro, setTemplatesErro] = useState('')

  useEffect(() => {
    let cancelado = false
    setTemplatesLoading(true)
    setTemplatesErro('')
    fetch('/api/open-data/npi/templates-disponiveis')
      .then(async (res) => {
        const payload = await res.json().catch(() => null)
        if (!res.ok) throw new Error(extrairDetalheErro(payload) || `HTTP ${res.status}`)
        if (!cancelado) setTemplatesDisponiveis(payload?.items || [])
      })
      .catch((err) => {
        if (!cancelado) setTemplatesErro(err instanceof Error ? err.message : 'Erro ao carregar templates.')
      })
      .finally(() => {
        if (!cancelado) setTemplatesLoading(false)
      })
    return () => { cancelado = true }
  }, [])

  return (
    <div className="flex flex-col gap-1 text-sm text-slate-600">
      Templates do Omnichat que pertencem a essa campanha ({selecionados.size} selecionado{selecionados.size === 1 ? '' : 's'})
      {templatesLoading ? (
        <p className="text-xs text-slate-400">Carregando templates...</p>
      ) : templatesErro ? (
        <p className="text-xs text-rose-600">{templatesErro}</p>
      ) : templatesDisponiveis.length === 0 ? (
        <p className="text-xs text-slate-400">Nenhum template encontrado em dados_omni.</p>
      ) : (
        <div className="max-h-56 overflow-y-auto rounded-lg border border-slate-300 bg-white">
          <table className="min-w-full text-xs">
            <tbody>
              {templatesDisponiveis.map((t, i) => (
                <tr
                  key={t.template_title}
                  onClick={() => onToggle(t.template_title)}
                  className={`cursor-pointer ${i % 2 === 0 ? 'bg-white' : 'bg-slate-50'} hover:bg-indigo-50`}
                >
                  <td className="w-8 px-2 py-1.5">
                    <input
                      type="checkbox"
                      checked={selecionados.has(t.template_title)}
                      onChange={() => onToggle(t.template_title)}
                      onClick={(e) => e.stopPropagation()}
                    />
                  </td>
                  <td className="px-2 py-1.5 font-mono text-slate-700">{t.template_title}</td>
                  <td className="whitespace-nowrap px-2 py-1.5 text-slate-500">{t.total_entregues.toLocaleString('pt-BR')} entregues</td>
                  <td className="whitespace-nowrap px-2 py-1.5 text-slate-500">{t.primeiro_envio} a {t.ultimo_envio}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function CalcularAutomaticoForm({ periodos, onCalculado, onCancelar }) {
  const [periodoId, setPeriodoId] = useState(periodos[0]?.id ?? '')
  const [selecionados, setSelecionados] = useState(() => new Set())
  const [janelaDias, setJanelaDias] = useState(7)
  const [calculando, setCalculando] = useState(false)
  const [erro, setErro] = useState('')
  const [resultado, setResultado] = useState(null)

  const toggleTemplate = useCallback((titulo) => {
    setSelecionados((prev) => {
      const next = new Set(prev)
      if (next.has(titulo)) next.delete(titulo)
      else next.add(titulo)
      return next
    })
  }, [])

  const handleSubmit = useCallback(async (event) => {
    event.preventDefault()
    const templateTitles = Array.from(selecionados)
    if (!periodoId || templateTitles.length === 0) {
      setErro('Selecione o período e marque pelo menos um template.')
      return
    }
    setCalculando(true)
    setErro('')
    setResultado(null)
    try {
      const res = await fetch(`/api/open-data/npi/periodos/${periodoId}/calcular`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ template_titles: templateTitles, janela_dias: Number(janelaDias) || 7 }),
      })
      const payload = await res.json().catch(() => null)
      if (!res.ok) throw new Error(extrairDetalheErro(payload) || `HTTP ${res.status}`)
      setResultado(payload)
      onCalculado()
    } catch (err) {
      setErro(err instanceof Error ? err.message : 'Erro ao calcular.')
    } finally {
      setCalculando(false)
    }
  }, [periodoId, selecionados, janelaDias, onCalculado])

  return (
    <form onSubmit={handleSubmit} className="mb-4 flex flex-col gap-3 rounded-xl border border-indigo-200 bg-indigo-50/50 p-4">
      <p className="text-xs text-slate-500">
        Calcula os 5 canais automaticamente via BigQuery (ponte contact_id↔telefone + disparos do Omnichat) e
        <strong> sobrescreve</strong> as células desse período - dá pra editar manualmente depois se precisar ajustar algo.
      </p>
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-sm text-slate-600">
          Período
          <select
            value={periodoId}
            onChange={(e) => setPeriodoId(e.target.value)}
            className="min-w-[180px] rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900"
          >
            {periodos.map((p) => (
              <option key={p.id} value={p.id}>{p.nome}</option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-sm text-slate-600">
          Janela (dias após o toque)
          <input
            type="number"
            min={1}
            max={30}
            value={janelaDias}
            onChange={(e) => setJanelaDias(e.target.value)}
            className="w-28 rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900"
          />
        </label>
      </div>
      <TemplateSelector selecionados={selecionados} onToggle={toggleTemplate} />
      <div className="flex gap-3">
        <button type="submit" disabled={calculando} className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-700 disabled:opacity-50">
          {calculando ? 'Calculando...' : 'Calcular e salvar'}
        </button>
        <button type="button" onClick={onCancelar} className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-100">
          Fechar
        </button>
      </div>
      {erro && <p className="text-xs text-rose-600">{erro}</p>}
      {resultado && (
        <div className="text-xs text-slate-600">
          <p className="text-emerald-700">Salvo com sucesso.</p>
          {Object.keys(resultado.outros_canais_nao_salvos || {}).length > 0 && (
            <p className="mt-1 text-amber-700">
              Atenção: apareceram canais fora dos 5 conhecidos, não salvos na tabela:{' '}
              {Object.entries(resultado.outros_canais_nao_salvos).map(([c, v]) => `${c} (${formatCurrency(v)})`).join(', ')}
            </p>
          )}
        </div>
      )}
    </form>
  )
}

const ChevronIcon = ({ open }) => (
  <svg className={`h-3.5 w-3.5 text-slate-400 transition-transform ${open ? 'rotate-180' : ''}`}
    viewBox="0 0 20 20" fill="currentColor">
    <path fillRule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clipRule="evenodd" />
  </svg>
)

// Abertura por regional/loja - mesmo cruzamento order_id x vendas_iplace e
// o mesmo layout colapsável já usados em "Canal da Receita Atribuída"
// (Resultado Geral), via /api/open-data/npi/periodos/{id}/regional.
function RegionalBreakdown({ data }) {
  const [expandedRegionals, setExpandedRegionals] = useState(new Set())

  const toggleRegional = useCallback((r) => {
    setExpandedRegionals((prev) => {
      const next = new Set(prev)
      if (next.has(r)) next.delete(r)
      else next.add(r)
      return next
    })
  }, [])

  const regionais = data?.regionais ?? []
  if (regionais.length === 0) {
    return <p className="text-sm text-slate-500">Nenhum pedido cruzado com vendas_iplace nesse período.</p>
  }
  const maxRegReceita = regionais[0]?.receita || 1

  return (
    <div>
      <p className="mb-3 text-xs text-slate-400">
        {data.total_cruzado.toLocaleString('pt-BR')} de {data.total_orders.toLocaleString('pt-BR')} pedidos com receita
        atribuída cruzados com vendas_iplace - o restante aparece em "Outros".
      </p>
      <div className="space-y-2">
        {regionais.map((reg) => (
          <div key={reg.regional} className="overflow-hidden rounded-lg border border-slate-200 bg-white">
            <button
              type="button"
              onClick={() => toggleRegional(reg.regional)}
              className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-slate-50"
            >
              <div className="min-w-0 flex-1">
                <div className="mb-1.5 flex items-center justify-between">
                  <span className="text-sm font-semibold text-slate-700">{reg.regional}</span>
                  <div className="flex items-center gap-4">
                    <span className="text-xs text-slate-400">{reg.linhas.toLocaleString('pt-BR')} pedidos</span>
                    <span className="text-sm font-bold text-slate-900">{formatCurrency(reg.receita)}</span>
                    <ChevronIcon open={expandedRegionals.has(reg.regional)} />
                  </div>
                </div>
                <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
                  <div className="h-full rounded-full bg-indigo-400" style={{ width: `${(reg.receita / maxRegReceita) * 100}%` }} />
                </div>
              </div>
            </button>
            {expandedRegionals.has(reg.regional) && reg.lojas.length > 0 && (
              <div className="divide-y divide-slate-50 border-t border-slate-100 bg-slate-50">
                {reg.lojas.map((f) => {
                  const maxLojaReceita = reg.lojas[0]?.receita || 1
                  return (
                    <div key={f.codigo_filial} className="flex items-center gap-3 px-6 py-2 text-xs">
                      <span className="w-16 shrink-0 font-semibold text-slate-600">
                        LJ{String(f.codigo_filial).padStart(3, '0')}
                      </span>
                      <span className="flex-1 truncate text-slate-500">{f.nome}</span>
                      <div className="w-24 flex-shrink-0">
                        <div className="h-1 overflow-hidden rounded-full bg-slate-200">
                          <div className="h-full rounded-full bg-indigo-300" style={{ width: `${((f.receita || 0) / maxLojaReceita) * 100}%` }} />
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
    </div>
  )
}

function VerRegionalForm({ periodos, onFechar }) {
  const [periodoId, setPeriodoId] = useState(periodos[0]?.id ?? '')
  const [selecionados, setSelecionados] = useState(() => new Set())
  const [janelaDias, setJanelaDias] = useState(7)
  const [carregando, setCarregando] = useState(false)
  const [erro, setErro] = useState('')
  const [resultado, setResultado] = useState(null)

  const toggleTemplate = useCallback((titulo) => {
    setSelecionados((prev) => {
      const next = new Set(prev)
      if (next.has(titulo)) next.delete(titulo)
      else next.add(titulo)
      return next
    })
  }, [])

  const handleSubmit = useCallback(async (event) => {
    event.preventDefault()
    const templateTitles = Array.from(selecionados)
    if (!periodoId || templateTitles.length === 0) {
      setErro('Selecione o período e marque pelo menos um template.')
      return
    }
    setCarregando(true)
    setErro('')
    setResultado(null)
    try {
      const res = await fetch(`/api/open-data/npi/periodos/${periodoId}/regional`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ template_titles: templateTitles, janela_dias: Number(janelaDias) || 7 }),
      })
      const payload = await res.json().catch(() => null)
      if (!res.ok) throw new Error(extrairDetalheErro(payload) || `HTTP ${res.status}`)
      setResultado(payload)
    } catch (err) {
      setErro(err instanceof Error ? err.message : 'Erro ao carregar abertura regional.')
    } finally {
      setCarregando(false)
    }
  }, [periodoId, selecionados, janelaDias])

  return (
    <form onSubmit={handleSubmit} className="mb-4 flex flex-col gap-3 rounded-xl border border-sky-200 bg-sky-50/50 p-4">
      <p className="text-xs text-slate-500">
        Abertura da receita atribuída (todos os canais, exceto "Sem atribuição") por regional e por loja - mesmo
        cruzamento por número de pedido (vendas_iplace) usado no Resultado Geral. Use os mesmos templates do cálculo
        desse período, pra bater com os valores já salvos.
      </p>
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-sm text-slate-600">
          Período
          <select
            value={periodoId}
            onChange={(e) => setPeriodoId(e.target.value)}
            className="min-w-[180px] rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900"
          >
            {periodos.map((p) => (
              <option key={p.id} value={p.id}>{p.nome}</option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-sm text-slate-600">
          Janela (dias após o toque)
          <input
            type="number"
            min={1}
            max={30}
            value={janelaDias}
            onChange={(e) => setJanelaDias(e.target.value)}
            className="w-28 rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900"
          />
        </label>
      </div>
      <TemplateSelector selecionados={selecionados} onToggle={toggleTemplate} />
      <div className="flex gap-3">
        <button type="submit" disabled={carregando} className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-700 disabled:opacity-50">
          {carregando ? 'Calculando...' : 'Ver abertura'}
        </button>
        <button type="button" onClick={onFechar} className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-100">
          Fechar
        </button>
      </div>
      {erro && <p className="text-xs text-rose-600">{erro}</p>}
      {resultado && (
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <RegionalBreakdown data={resultado} />
        </div>
      )}
    </form>
  )
}

export default function ResultadosNpiPage({ currentRole }) {
  const [dados, setDados] = useState(null)
  const [loading, setLoading] = useState(true)
  const [erro, setErro] = useState('')
  const [mostrarNovoPeriodo, setMostrarNovoPeriodo] = useState(false)
  const [mostrarCalcular, setMostrarCalcular] = useState(false)
  const [mostrarRegional, setMostrarRegional] = useState(false)

  const isAdmin = currentRole === 'admin'

  const carregar = useCallback(async () => {
    setLoading(true)
    setErro('')
    try {
      const res = await fetch('/api/open-data/npi/resultados')
      const payload = await res.json().catch(() => null)
      if (!res.ok) throw new Error(extrairDetalheErro(payload) || `HTTP ${res.status}`)
      setDados(payload)
    } catch (err) {
      setErro(err instanceof Error ? err.message : 'Erro ao carregar resultados NPI.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    carregar()
  }, [carregar])

  const handleSalvarValor = useCallback(async (periodoId, canal, receita) => {
    try {
      const res = await fetch('/api/open-data/npi/valores', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ periodo_id: periodoId, canal, receita }),
      })
      const payload = await res.json().catch(() => null)
      if (!res.ok) throw new Error(extrairDetalheErro(payload) || `HTTP ${res.status}`)
      await carregar()
    } catch (err) {
      setErro(err instanceof Error ? err.message : 'Erro ao salvar valor.')
    }
  }, [carregar])

  const handleRemoverPeriodo = useCallback(async (periodoId) => {
    if (!window.confirm('Remover este período e todos os valores lançados nele?')) return
    try {
      const res = await fetch(`/api/open-data/npi/periodos/${periodoId}`, { method: 'DELETE' })
      const payload = await res.json().catch(() => null)
      if (!res.ok) throw new Error(extrairDetalheErro(payload) || `HTTP ${res.status}`)
      await carregar()
    } catch (err) {
      setErro(err instanceof Error ? err.message : 'Erro ao remover período.')
    }
  }, [carregar])

  if (loading) {
    return (
      <div className="mx-auto max-w-7xl px-4 py-8 md:px-6 lg:px-8">
        <p className="text-sm text-slate-500">Carregando...</p>
      </div>
    )
  }

  const canais = dados?.canais ?? []
  const periodos = dados?.periodos ?? []
  const valores = dados?.valores ?? {}

  const valorCelula = (periodoId, canal) => Number(valores?.[periodoId]?.[canal] ?? 0)
  const totalPeriodo = (periodoId) => canais.reduce((s, c) => s + valorCelula(periodoId, c.key), 0)
  const totalCanal = (canal) => periodos.reduce((s, p) => s + valorCelula(p.id, canal), 0)
  const totalGeral = periodos.reduce((s, p) => s + totalPeriodo(p.id), 0)

  // Receita atribuída = todos os canais MENOS "Sem atribuição" (o gap que a
  // Emarsys nao credita a ninguem) - mostra quanto realmente tem canal
  // identificado, separado do total bruto (que inclui o "sem atribuição").
  const canaisAtribuidos = canais.filter((c) => c.key !== 'sem_atribuicao')
  const totalAtribuidoPeriodo = (periodoId) => canaisAtribuidos.reduce((s, c) => s + valorCelula(periodoId, c.key), 0)
  const totalAtribuidoGeral = periodos.reduce((s, p) => s + totalAtribuidoPeriodo(p.id), 0)

  return (
    <div className="mx-auto max-w-7xl px-4 py-8 md:px-6 lg:px-8">
      <section className="mb-6 rounded-2xl bg-gradient-to-r from-indigo-600 to-violet-500 p-6 text-white shadow-soft md:p-8">
        <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">Resultados NPI</h1>
        <p className="mt-2 text-sm text-indigo-100 md:text-base">
          Receita por canal e por período da campanha NPI - lançamento manual, sem cálculo automático.
        </p>
      </section>

      {erro && <p className="mb-4 rounded-lg border border-rose-200 bg-rose-50 px-4 py-2 text-sm text-rose-700">{erro}</p>}

      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft md:p-6">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">Receita por canal e período</h2>
          <div className="flex gap-2">
            {isAdmin && !mostrarNovoPeriodo && (
              <button
                onClick={() => setMostrarNovoPeriodo(true)}
                className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-100"
              >
                + Adicionar período
              </button>
            )}
            {isAdmin && !mostrarCalcular && periodos.length > 0 && (
              <button
                onClick={() => setMostrarCalcular(true)}
                className="rounded-lg border border-indigo-300 bg-indigo-50 px-3 py-1.5 text-xs font-semibold text-indigo-700 hover:bg-indigo-100"
              >
                ⟳ Calcular automaticamente
              </button>
            )}
            {!mostrarRegional && periodos.length > 0 && (
              <button
                onClick={() => setMostrarRegional(true)}
                className="rounded-lg border border-sky-300 bg-sky-50 px-3 py-1.5 text-xs font-semibold text-sky-700 hover:bg-sky-100"
              >
                📊 Ver abertura por regional/loja
              </button>
            )}
          </div>
        </div>

        {mostrarNovoPeriodo && (
          <NovoPeriodoForm
            onCriado={() => { setMostrarNovoPeriodo(false); carregar() }}
            onCancelar={() => setMostrarNovoPeriodo(false)}
          />
        )}

        {mostrarCalcular && (
          <CalcularAutomaticoForm
            periodos={periodos}
            onCalculado={carregar}
            onCancelar={() => setMostrarCalcular(false)}
          />
        )}

        {mostrarRegional && (
          <VerRegionalForm
            periodos={periodos}
            onFechar={() => setMostrarRegional(false)}
          />
        )}

        {periodos.length === 0 ? (
          <p className="text-sm text-slate-500">
            Nenhum período cadastrado ainda. {isAdmin ? 'Clique em "Adicionar período" para começar.' : ''}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                  <th className="px-4 py-2">Canal</th>
                  {periodos.map((p) => (
                    <th key={p.id} className="px-4 py-2 text-right">
                      <div className="flex items-center justify-end gap-1.5">
                        <span>
                          {p.nome}
                          <span className="block font-normal normal-case text-slate-400">{formatarPeriodo(p)}</span>
                        </span>
                        {isAdmin && (
                          <button
                            onClick={() => handleRemoverPeriodo(p.id)}
                            title="Remover período"
                            className="rounded p-0.5 text-slate-300 hover:bg-rose-50 hover:text-rose-600"
                          >
                            ×
                          </button>
                        )}
                      </div>
                    </th>
                  ))}
                  <th className="px-4 py-2 text-right">Total</th>
                </tr>
              </thead>
              <tbody>
                {canais.map((c, i) => (
                  <tr key={c.key} className={i % 2 === 0 ? 'bg-white' : 'bg-slate-50'}>
                    <td className="whitespace-nowrap px-4 py-2 text-sm font-medium text-slate-700">{c.label}</td>
                    {periodos.map((p) => (
                      <CelulaValor
                        key={p.id}
                        isAdmin={isAdmin}
                        valor={valorCelula(p.id, c.key)}
                        onSalvar={(novoValor) => handleSalvarValor(p.id, c.key, novoValor)}
                      />
                    ))}
                    <td className="whitespace-nowrap px-4 py-2 text-right text-sm font-semibold text-slate-900">
                      {formatCurrency(totalCanal(c.key))}
                    </td>
                  </tr>
                ))}
                <tr className="border-t border-slate-200 bg-emerald-50/60 font-semibold">
                  <td className="whitespace-nowrap px-4 py-2 text-sm text-emerald-800">Total de receita atribuída</td>
                  {periodos.map((p) => (
                    <td key={p.id} className="whitespace-nowrap px-4 py-2 text-right text-sm text-emerald-800">
                      {formatCurrency(totalAtribuidoPeriodo(p.id))}
                    </td>
                  ))}
                  <td className="whitespace-nowrap px-4 py-2 text-right text-sm text-emerald-800">
                    {formatCurrency(totalAtribuidoGeral)}
                  </td>
                </tr>
                <tr className="border-t-2 border-slate-300 bg-slate-100 font-semibold">
                  <td className="whitespace-nowrap px-4 py-2 text-sm text-slate-900">Total geral</td>
                  {periodos.map((p) => (
                    <td key={p.id} className="whitespace-nowrap px-4 py-2 text-right text-sm text-slate-900">
                      {formatCurrency(totalPeriodo(p.id))}
                    </td>
                  ))}
                  <td className="whitespace-nowrap px-4 py-2 text-right text-sm text-slate-900">
                    {formatCurrency(totalGeral)}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        )}

        {!isAdmin && periodos.length > 0 && (
          <p className="mt-3 text-xs text-slate-400">Valores lançados manualmente pelo time de CRM.</p>
        )}
      </section>
    </div>
  )
}
