import { useState, useCallback, useEffect } from 'react'

function getDefaultDates() {
  const today = new Date()
  const start = new Date(today)
  start.setDate(start.getDate() - 30)
  return {
    start: start.toISOString().split('T')[0],
    end: today.toISOString().split('T')[0],
  }
}

const fmtN = (n) => new Intl.NumberFormat('pt-BR').format(n ?? 0)
const fmtCurrency = (n) =>
  new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL', minimumFractionDigits: 2 }).format(Number(n || 0))

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

export default function VendasNpiPage() {
  const defaults = getDefaultDates()
  const [startDate, setStartDate] = useState(defaults.start)
  const [endDate, setEndDate] = useState(defaults.end)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [ga, setGa] = useState(null)
  const [emarsys, setEmarsys] = useState(null)

  const loadData = useCallback(async () => {
    if (!startDate || !endDate) return
    setLoading(true)
    setError('')
    try {
      const params = new URLSearchParams({ start: startDate, end: endDate })
      const [gaRes, emarsysRes] = await Promise.all([
        fetch(`/api/ga4/vendas-npi?${params}`),
        fetch(`/api/open-data/vendas-npi?${params}`),
      ])
      const gaJson = await gaRes.json().catch(() => null)
      const emarsysJson = await emarsysRes.json().catch(() => null)
      if (!gaRes.ok) throw new Error(gaJson?.detail || `GA4: HTTP ${gaRes.status}`)
      if (!emarsysRes.ok) throw new Error(emarsysJson?.detail || `Emarsys: HTTP ${emarsysRes.status}`)
      setGa(gaJson)
      setEmarsys(emarsysJson)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Falha ao carregar dados.')
      setGa(null)
      setEmarsys(null)
    } finally {
      setLoading(false)
    }
  }, [startDate, endDate])

  useEffect(() => {
    loadData()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const items = []
  const porModelo = {}
  if (ga && emarsys) {
    const emarsysBySku = new Map(emarsys.items.map((item) => [item.sku, item]))
    for (const gaItem of ga.items) {
      const emItem = emarsysBySku.get(gaItem.sku)
      const modelo = emItem?.modelo || 'Outro'
      const qtdGa = gaItem.qtd || 0
      const qtdEmarsys = emItem?.qtd || 0
      items.push({
        sku: gaItem.sku,
        descricao: gaItem.descricao || emItem?.descricao || '',
        modelo,
        qtdGa,
        qtdEmarsys,
        qtdTotal: qtdGa + qtdEmarsys,
      })
      if (!porModelo[modelo]) porModelo[modelo] = { modelo, qtdGa: 0, qtdEmarsys: 0, qtdTotal: 0 }
      porModelo[modelo].qtdGa += qtdGa
      porModelo[modelo].qtdEmarsys += qtdEmarsys
      porModelo[modelo].qtdTotal += qtdGa + qtdEmarsys
    }
    items.sort((a, b) => b.qtdTotal - a.qtdTotal)
  }
  const resumoModelo = Object.values(porModelo).sort((a, b) => b.qtdTotal - a.qtdTotal)
  const totalGa = ga?.total_qtd ?? 0
  const totalEmarsys = emarsys?.total_qtd ?? 0

  return (
    <div className="mx-auto max-w-7xl px-4 py-8 md:px-6 lg:px-8">
      <h1 className="mb-6 text-xl font-bold text-slate-900">Vendas NPI - iPhone 18</h1>

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

      {loading && !ga && <p className="text-sm text-slate-500">Carregando...</p>}

      {!loading && !ga && !error && (
        <p className="text-sm text-slate-500">Selecione o período e clique em Atualizar.</p>
      )}

      {ga && emarsys && (
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-4 sm:flex-row">
            <StatTile label="Google Analytics" value={totalGa} />
            <StatTile label="Emarsys" value={totalEmarsys} />
            <StatTile label="Total" value={totalGa + totalEmarsys} accent />
          </div>

          <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft">
            <h2 className="mb-4 text-lg font-semibold text-slate-900">Por modelo</h2>
            <div className="overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-200 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                    <th className="px-3 py-2">Modelo</th>
                    <th className="px-3 py-2 text-right">GA</th>
                    <th className="px-3 py-2 text-right">Emarsys</th>
                    <th className="px-3 py-2 text-right">Total</th>
                  </tr>
                </thead>
                <tbody>
                  {resumoModelo.map((item, i) => (
                    <tr key={item.modelo} className={i % 2 === 0 ? 'bg-white' : 'bg-slate-50'}>
                      <td className="whitespace-nowrap px-3 py-2 font-medium text-slate-700">{item.modelo}</td>
                      <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums text-slate-700">{fmtN(item.qtdGa)}</td>
                      <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums text-slate-700">{fmtN(item.qtdEmarsys)}</td>
                      <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums font-semibold text-slate-900">{fmtN(item.qtdTotal)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft">
            <h2 className="mb-4 text-lg font-semibold text-slate-900">Por SKU</h2>
            <div className="overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-200 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                    <th className="px-3 py-2">SKU</th>
                    <th className="px-3 py-2">Descrição</th>
                    <th className="px-3 py-2 text-right">GA</th>
                    <th className="px-3 py-2 text-right">Emarsys</th>
                    <th className="px-3 py-2 text-right">Total</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((item, i) => (
                    <tr key={item.sku} className={i % 2 === 0 ? 'bg-white' : 'bg-slate-50'}>
                      <td className="whitespace-nowrap px-3 py-2 text-slate-500">{item.sku}</td>
                      <td className="whitespace-nowrap px-3 py-2 text-slate-700">{item.descricao}</td>
                      <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums text-slate-700">{fmtN(item.qtdGa)}</td>
                      <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums text-slate-700">{fmtN(item.qtdEmarsys)}</td>
                      <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums font-semibold text-slate-900">{fmtN(item.qtdTotal)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <p className="text-xs text-slate-400">
            Emarsys - receita no período: {fmtCurrency(emarsys.total_valor)}. Google Analytics - receita no período:{' '}
            {fmtCurrency(ga.total_revenue)}.
          </p>
        </div>
      )}
    </div>
  )
}
