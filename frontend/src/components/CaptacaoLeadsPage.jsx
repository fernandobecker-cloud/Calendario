import { useState, useCallback, useEffect } from 'react'

function getDefaultDates() {
  const today = new Date()
  return {
    start: '2026-08-26',
    end: today.toISOString().split('T')[0],
  }
}

const fmtN = (n) => new Intl.NumberFormat('pt-BR').format(n ?? 0)

function StatTile({ label, value, accent = false }) {
  return (
    <div
      className={`flex-1 rounded-2xl border p-5 shadow-soft ${
        accent ? 'border-slate-900 bg-slate-900 text-white' : 'border-slate-200 bg-white'
      }`}
    >
      <p className={`text-sm font-medium ${accent ? 'text-slate-300' : 'text-slate-500'}`}>{label}</p>
      <p className={`mt-1 text-4xl font-semibold ${accent ? 'text-white' : 'text-slate-900'}`}>{fmtN(value)}</p>
    </div>
  )
}

export default function CaptacaoLeadsPage() {
  const defaults = getDefaultDates()
  const [startDate, setStartDate] = useState(defaults.start)
  const [endDate, setEndDate] = useState(defaults.end)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [data, setData] = useState(null)

  const loadData = useCallback(async () => {
    if (!startDate || !endDate) return
    setLoading(true)
    setError('')
    try {
      const params = new URLSearchParams({ start: startDate, end: endDate })
      const res = await fetch(`/api/open-data/captacao-leads?${params}`)
      const json = await res.json().catch(() => null)
      if (!res.ok) throw new Error(json?.detail || `HTTP ${res.status}`)
      setData(json)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Falha ao carregar dados.')
      setData(null)
    } finally {
      setLoading(false)
    }
  }, [startDate, endDate])

  useEffect(() => {
    loadData()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div className="mx-auto max-w-7xl px-4 py-8 md:px-6 lg:px-8">
      <h1 className="mb-6 text-xl font-bold text-slate-900">Captação de Leads</h1>

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
            onClick={loadData}
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

      {loading && !data && <p className="text-sm text-slate-500">Carregando...</p>}

      {!loading && !data && !error && (
        <p className="text-sm text-slate-500">Selecione o período e clique em Atualizar.</p>
      )}

      {data && (
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-4 sm:flex-row">
            <StatTile label="Site" value={data.formularios?.site?.qtd} />
            <StatTile label="Lojas" value={data.formularios?.lojas?.qtd} />
            <StatTile label="Total" value={data.total} accent />
          </div>
        </div>
      )}
    </div>
  )
}
