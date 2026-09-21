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

export default function ResultadosNpiPage({ currentRole }) {
  const [dados, setDados] = useState(null)
  const [loading, setLoading] = useState(true)
  const [erro, setErro] = useState('')
  const [mostrarNovoPeriodo, setMostrarNovoPeriodo] = useState(false)

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
          {isAdmin && !mostrarNovoPeriodo && (
            <button
              onClick={() => setMostrarNovoPeriodo(true)}
              className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-100"
            >
              + Adicionar período
            </button>
          )}
        </div>

        {mostrarNovoPeriodo && (
          <NovoPeriodoForm
            onCriado={() => { setMostrarNovoPeriodo(false); carregar() }}
            onCancelar={() => setMostrarNovoPeriodo(false)}
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
