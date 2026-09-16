import { useCallback, useState } from 'react'

function extrairDetalheErro(payload) {
  const detail = payload?.detail
  if (!detail) return ''
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail.map((d) => d?.msg || JSON.stringify(d)).join('; ')
  }
  return JSON.stringify(detail)
}

function formatarMoeda(valor) {
  return (Number(valor) || 0).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })
}

function formatarNumero(valor) {
  return (Number(valor) || 0).toLocaleString('pt-BR')
}

function CartaoMetrica({ titulo, destaque, nota, compradores, pedidos, receita }) {
  return (
    <div
      className={`rounded-2xl border p-5 shadow-soft ${
        destaque ? 'border-emerald-300 bg-emerald-50/60' : 'border-slate-200 bg-white'
      }`}
    >
      <div className="mb-3 flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-600">{titulo}</h3>
        {destaque && (
          <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-semibold text-emerald-700">
            Recomendado
          </span>
        )}
      </div>
      <p className="text-3xl font-semibold tracking-tight text-slate-900">{formatarMoeda(receita)}</p>
      <p className="mt-1 text-sm text-slate-500">
        {formatarNumero(pedidos)} pedido(s) - {formatarNumero(compradores)} comprador(es) unico(s)
      </p>
      {nota && <p className="mt-3 text-xs leading-relaxed text-slate-500">{nota}</p>}
    </div>
  )
}

export default function ReceitaPosDisparoPage() {
  const [segmentoId, setSegmentoId] = useState('')
  const [dataDisparo, setDataDisparo] = useState('')
  const [janelaDias, setJanelaDias] = useState(7)
  const [campanha, setCampanha] = useState('')
  const [skus, setSkus] = useState('')
  const [campoCpf, setCampoCpf] = useState('12908')

  const [loading, setLoading] = useState(false)
  const [erro, setErro] = useState('')
  const [resultado, setResultado] = useState(null)

  const handleSubmit = useCallback(
    async (event) => {
      event.preventDefault()
      if (!segmentoId.trim() || !dataDisparo) {
        setErro('Informe o ID do segmento e a data do disparo.')
        return
      }
      setLoading(true)
      setErro('')
      setResultado(null)
      try {
        const params = new URLSearchParams({
          data_disparo: dataDisparo,
          janela_dias: String(janelaDias || 7),
          campanha,
          campo_cpf: campoCpf || '12908',
        })
        if (skus.trim()) params.set('skus', skus.trim())
        const res = await fetch(
          `/api/emarsys/segmento/${encodeURIComponent(segmentoId.trim())}/receita-atribuida?${params}`,
          { method: 'POST' }
        )
        const payload = await res.json().catch(() => null)
        if (!res.ok) throw new Error(extrairDetalheErro(payload) || `HTTP ${res.status}`)
        setResultado(payload)
      } catch (err) {
        setErro(err instanceof Error ? err.message : 'Erro ao calcular receita.')
      } finally {
        setLoading(false)
      }
    },
    [segmentoId, dataDisparo, janelaDias, campanha, skus, campoCpf]
  )

  return (
    <div className="mx-auto max-w-7xl px-4 py-8 md:px-6 lg:px-8">
      <section className="mb-6 rounded-2xl bg-gradient-to-r from-indigo-600 to-violet-500 p-6 text-white shadow-soft md:p-8">
        <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">Receita Pos-Disparo</h1>
        <p className="mt-2 text-sm text-indigo-100 md:text-base">
          Mede a receita de um segmento apos um disparo feito fora da Emarsys (ex: WhatsApp pelo Omnichat) -
          a Emarsys nao enxerga esse envio, entao a conta e feita cruzando o CPF dos contatos do segmento
          direto com as compras (si_purchases), sem depender do modelo de atribuicao por canal dela.
        </p>
      </section>

      <section className="mb-6 rounded-2xl border border-slate-200 bg-white p-5 shadow-soft md:p-6">
        <h2 className="mb-4 text-lg font-semibold text-slate-900">Consultar disparo</h2>
        <form onSubmit={handleSubmit} className="flex flex-wrap items-end gap-4">
          <label className="flex flex-col gap-1 text-sm text-slate-600">
            ID do segmento (Emarsys)
            <input
              value={segmentoId}
              onChange={(e) => setSegmentoId(e.target.value)}
              placeholder="ex: 305785"
              className="min-w-[160px] rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm text-slate-600">
            Data do disparo
            <input
              type="date"
              value={dataDisparo}
              onChange={(e) => setDataDisparo(e.target.value)}
              className="rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm text-slate-600">
            Janela (dias)
            <input
              type="number"
              min={1}
              max={60}
              value={janelaDias}
              onChange={(e) => setJanelaDias(e.target.value)}
              className="w-24 rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm text-slate-600">
            Campanha (rotulo, opcional)
            <input
              value={campanha}
              onChange={(e) => setCampanha(e.target.value)}
              placeholder="ex: NPI pre-venda WhatsApp"
              className="min-w-[200px] rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900"
            />
          </label>
          <button
            type="submit"
            disabled={loading}
            className="rounded-lg bg-slate-900 px-5 py-2 text-sm font-semibold text-white transition hover:bg-slate-700 disabled:opacity-50"
          >
            {loading ? 'Calculando...' : 'Calcular receita'}
          </button>
        </form>

        <details className="mt-4">
          <summary className="cursor-pointer text-sm font-medium text-slate-700">Opcoes avancadas</summary>
          <div className="mt-3 flex flex-wrap items-end gap-4">
            <label className="flex flex-col gap-1 text-sm text-slate-600">
              SKUs da campanha (opcional)
              <textarea
                value={skus}
                onChange={(e) => setSkus(e.target.value)}
                placeholder="Vazio = usa os SKUs do lancamento iPhone 18 (padrao). Separe varios por virgula."
                rows={2}
                className="min-w-[320px] rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900"
              />
            </label>
            <label className="flex flex-col gap-1 text-sm text-slate-600">
              ID do campo de CPF na Emarsys
              <input
                value={campoCpf}
                onChange={(e) => setCampoCpf(e.target.value)}
                className="w-32 rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900"
              />
            </label>
          </div>
        </details>

        {erro && <p className="mt-4 rounded-lg border border-rose-200 bg-rose-50 px-4 py-2 text-sm text-rose-700">{erro}</p>}
      </section>

      {resultado && (
        <>
          <section className="mb-6 rounded-2xl border border-slate-200 bg-white p-5 shadow-soft md:p-6">
            <h2 className="mb-3 text-lg font-semibold text-slate-900">
              {resultado.segmento_nome || resultado.segmento_id}
              {resultado.campanha && <span className="ml-2 text-sm font-normal text-slate-500">({resultado.campanha})</span>}
            </h2>
            <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm text-slate-600 sm:grid-cols-4">
              <p>Segmento: <span className="font-medium text-slate-900">{resultado.segmento_id}</span></p>
              <p>Contatos no segmento: <span className="font-medium text-slate-900">{formatarNumero(resultado.total_contatos_segmento)}</span></p>
              <p>CPFs validos: <span className="font-medium text-slate-900">{formatarNumero(resultado.total_cpfs_informados)}</span></p>
              <p>Janela: <span className="font-medium text-slate-900">{resultado.data_disparo} a {resultado.fim_janela}</span></p>
            </div>
          </section>

          <section className="mb-6 grid grid-cols-1 gap-4 md:grid-cols-2">
            <CartaoMetrica
              titulo="Receita pos-disparo - so o produto (NPI)"
              destaque
              compradores={resultado.receita_pos_disparo?.npi?.compradores_unicos}
              pedidos={resultado.receita_pos_disparo?.npi?.pedidos}
              receita={resultado.receita_pos_disparo?.npi?.receita}
              nota="So a receita das linhas dos SKUs informados (ou do lancamento iPhone 18, por padrao) - proxy mais proxima do que o disparo de fato promoveu."
            />
            <CartaoMetrica
              titulo="Receita pos-disparo - qualquer compra (teto superior)"
              compradores={resultado.receita_pos_disparo?.total?.compradores_unicos}
              pedidos={resultado.receita_pos_disparo?.total?.pedidos}
              receita={resultado.receita_pos_disparo?.total?.receita}
              nota="Qualquer compra do segmento na janela, de qualquer produto - superestima bastante o efeito real (inclui compra sem relacao com o disparo). Use so como referencia de teto."
            />
          </section>

          <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft md:p-6">
            <div className="mb-3 flex items-center justify-between gap-2">
              <h2 className="text-lg font-semibold text-slate-900">Atribuicao nativa Emarsys (contexto)</h2>
              <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-500">
                Nao mede o Omnichat
              </span>
            </div>
            <p className="mb-4 text-xs leading-relaxed text-slate-500">{resultado.atribuicao_nativa_emarsys?.nota}</p>
            <div className="mb-4 grid grid-cols-2 gap-x-6 gap-y-1 text-sm text-slate-600 sm:grid-cols-4">
              <p>Match CPF x Emarsys: <span className="font-medium text-slate-900">{resultado.atribuicao_nativa_emarsys?.taxa_match_pct}%</span></p>
              <p>Pedidos atribuidos: <span className="font-medium text-slate-900">{formatarNumero(resultado.atribuicao_nativa_emarsys?.total_pedidos_atribuidos)}</span></p>
              <p>Receita atribuida: <span className="font-medium text-slate-900">{formatarMoeda(resultado.atribuicao_nativa_emarsys?.total_receita_atribuida)}</span></p>
            </div>
            {Array.isArray(resultado.atribuicao_nativa_emarsys?.by_channel) && resultado.atribuicao_nativa_emarsys.by_channel.length > 0 && (
              <div className="overflow-x-auto">
                <table className="min-w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-200 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                      <th className="px-3 py-2">Canal</th>
                      <th className="px-3 py-2">Compradores unicos</th>
                      <th className="px-3 py-2">Pedidos</th>
                      <th className="px-3 py-2">Receita</th>
                    </tr>
                  </thead>
                  <tbody>
                    {resultado.atribuicao_nativa_emarsys.by_channel.map((linha, i) => (
                      <tr key={linha.canal} className={i % 2 === 0 ? 'bg-white' : 'bg-slate-50'}>
                        <td className="whitespace-nowrap px-3 py-1.5 capitalize text-slate-700">{linha.canal}</td>
                        <td className="whitespace-nowrap px-3 py-1.5 text-slate-700">{formatarNumero(linha.compradores_unicos)}</td>
                        <td className="whitespace-nowrap px-3 py-1.5 text-slate-700">{formatarNumero(linha.pedidos_atribuidos)}</td>
                        <td className="whitespace-nowrap px-3 py-1.5 text-slate-700">{formatarMoeda(linha.receita_atribuida)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </div>
  )
}
