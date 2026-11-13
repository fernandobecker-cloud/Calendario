import { useCallback, useState } from 'react'
import { extrairDetalheErro } from './sacUtils'

// Aba "Catalogo do agente": mostra exatamente o que a API do agente de IA
// (servico agente-ia-api) devolve para a Omnichat, para conferir com o site.
// O portal nao calcula nada: preco, Pix e parcelamento vem prontos da API.

const TIPOS = [
  { valor: 'TEXT', rotulo: 'Texto (como o cliente digita)', exemplo: 'iphone 17 pro max' },
  { valor: 'SKUID', rotulo: 'Código do SKU', exemplo: '100072482' },
  { valor: 'URL', rotulo: 'Link do produto no site', exemplo: 'https://www.iplace.com.br/airpods-pro-3/100413PR' },
  { valor: 'ID', rotulo: 'ID do produto', exemplo: '100544PR' },
]

const brl = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' })
const pct = new Intl.NumberFormat('pt-BR', { style: 'percent', maximumFractionDigits: 1 })

function moeda(valor) {
  return typeof valor === 'number' ? brl.format(valor) : '-'
}

function opcao(variante, nome) {
  return (variante.installmentOptions || []).find((o) => o.name === nome)
}

function descontoDe(variante) {
  if (!variante.price || !variante.salePrice || variante.salePrice >= variante.price) return null
  return (variante.price - variante.salePrice) / variante.price
}

function ordenar(variantes) {
  // Com estoque primeiro, depois do mais barato pro mais caro.
  return [...variantes].sort((a, b) => (b.quantity > 0) - (a.quantity > 0) || a.salePrice - b.salePrice)
}

function TabelaVariantes({ produto }) {
  const principal = produto.mainVariant?.objectId
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-sm">
        <thead>
          <tr className="border-b border-slate-200 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
            <th className="px-3 py-2">Variante</th>
            <th className="px-3 py-2 text-right">De</th>
            <th className="px-3 py-2 text-right">Por</th>
            <th className="px-3 py-2 text-right">Desconto</th>
            <th className="px-3 py-2 text-right">Pix</th>
            <th className="px-3 py-2">Cartão</th>
            <th className="px-3 py-2 text-right">Estoque</th>
          </tr>
        </thead>
        <tbody>
          {ordenar(produto.variants || []).map((v, i) => {
            const pix = opcao(v, 'Pix')
            const cartao = opcao(v, 'Cartão de crédito')
            const desconto = descontoDe(v)
            const esgotado = !(v.quantity > 0)
            return (
              <tr key={v.objectId} className={`${i % 2 === 0 ? 'bg-white' : 'bg-slate-50'} ${esgotado ? 'text-slate-400' : 'text-slate-700'}`}>
                <td className="px-3 py-2">
                  <span className="block">
                    {v.name}
                    {v.objectId === principal && (
                      <span className="ml-2 rounded-full bg-indigo-50 px-2 py-0.5 text-xs font-medium text-indigo-700">principal</span>
                    )}
                  </span>
                  <span className="block text-xs text-slate-400">
                    SKU {v.objectId}
                    {(v.variations || []).map((x) => ` · ${x.key}: ${x.value}`).join('')}
                  </span>
                </td>
                <td className="whitespace-nowrap px-3 py-2 text-right">{moeda(v.price)}</td>
                <td className="whitespace-nowrap px-3 py-2 text-right font-semibold">{moeda(v.salePrice)}</td>
                <td className="whitespace-nowrap px-3 py-2 text-right">{desconto ? pct.format(desconto) : '-'}</td>
                <td className="whitespace-nowrap px-3 py-2 text-right">{moeda(pix?.oneTimePayment)}</td>
                <td className="whitespace-nowrap px-3 py-2">
                  {cartao ? (
                    <>
                      <span className="block">{cartao.maxInstallments}x de {moeda(cartao.installmentPrice)}</span>
                      <span className="block text-xs text-slate-400">
                        total {moeda(cartao.totalWithInterest)}
                        {cartao.interest ? ` · ${String(cartao.interest).replace('.', ',')}% a.m.` : ' · sem juros'}
                      </span>
                    </>
                  ) : '-'}
                </td>
                <td className="whitespace-nowrap px-3 py-2 text-right">
                  {esgotado ? <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs">Esgotado</span> : v.quantity}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function CartaoProduto({ produto }) {
  const imagem = produto.mainVariant?.externalImageURL
  return (
    <section className="mb-6 rounded-2xl border border-slate-200 bg-white p-5 shadow-soft md:p-6">
      <div className="mb-4 flex flex-wrap items-start gap-4">
        {imagem && <img src={imagem} alt="" className="h-16 w-16 rounded-lg border border-slate-100 object-contain" />}
        <div className="min-w-0 flex-1">
          <h2 className="text-lg font-semibold text-slate-900">{produto.name}</h2>
          <p className="text-xs text-slate-400">Produto {produto.objectId} · {(produto.variants || []).length} variante(s)</p>
        </div>
        {produto.externalUrl && (
          <a
            href={produto.externalUrl}
            target="_blank"
            rel="noreferrer"
            className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-semibold text-slate-600 hover:bg-slate-100"
          >
            Abrir no site ↗
          </a>
        )}
      </div>
      <TabelaVariantes produto={produto} />
      {produto.productDescription && (
        <details className="mt-4 text-sm text-slate-600">
          <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wide text-slate-500">
            Descrição que o agente recebe
          </summary>
          <p className="mt-2 whitespace-pre-line">{produto.productDescription}</p>
        </details>
      )}
    </section>
  )
}

export default function CatalogoAgentePage() {
  const [tipo, setTipo] = useState('TEXT')
  const [termo, setTermo] = useState('')
  const [loading, setLoading] = useState(false)
  const [erro, setErro] = useState('')
  const [resultado, setResultado] = useState(null)

  const exemplo = TIPOS.find((t) => t.valor === tipo)?.exemplo

  const buscar = useCallback(async (event) => {
    event.preventDefault()
    if (!termo.trim()) return
    setLoading(true)
    setErro('')
    setResultado(null)
    try {
      const params = new URLSearchParams({ query: termo.trim(), searchType: tipo, size: '10' })
      const res = await fetch(`/api/agente-ia/catalogo?${params}`)
      const payload = await res.json().catch(() => null)
      if (!res.ok) throw new Error(extrairDetalheErro(payload) || `HTTP ${res.status}`)
      setResultado({ ...payload, termo: termo.trim() })
    } catch (err) {
      setErro(err instanceof Error ? err.message : 'Erro ao consultar o catálogo.')
    } finally {
      setLoading(false)
    }
  }, [termo, tipo])

  const bloqueioAkamai = /akamai/i.test(erro)

  return (
    <div className="mx-auto max-w-6xl px-4 py-8 md:px-6 lg:px-8">
      <section className="mb-6 rounded-2xl bg-gradient-to-r from-indigo-600 to-violet-500 p-6 text-white shadow-soft md:p-8">
        <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">Catálogo do agente de IA</h1>
        <p className="mt-2 text-sm text-indigo-100 md:text-base">
          O que o agente da Omnichat recebe quando o cliente pergunta por um produto: preço, desconto, Pix, parcelamento e
          estoque. Confira com a página do produto no site.
        </p>
      </section>

      <section className="mb-6 rounded-2xl border border-slate-200 bg-white p-5 shadow-soft md:p-6">
        <form onSubmit={buscar} className="flex flex-wrap items-end gap-4">
          <label className="flex flex-col gap-1 text-sm text-slate-600">
            Buscar por
            <select
              value={tipo}
              onChange={(e) => setTipo(e.target.value)}
              className="rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900"
            >
              {TIPOS.map((t) => <option key={t.valor} value={t.valor}>{t.rotulo}</option>)}
            </select>
          </label>
          <label className="flex min-w-[260px] flex-1 flex-col gap-1 text-sm text-slate-600">
            Termo
            <input
              value={termo}
              onChange={(e) => setTermo(e.target.value)}
              placeholder={`ex.: ${exemplo}`}
              className="rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900"
            />
          </label>
          <button
            type="submit"
            disabled={loading || !termo.trim()}
            className="rounded-lg bg-slate-900 px-5 py-2 text-sm font-semibold text-white transition hover:bg-slate-700 disabled:opacity-50"
          >
            {loading ? 'Buscando...' : 'Buscar'}
          </button>
        </form>
        {loading && (
          <p className="mt-3 text-xs text-slate-400">
            Se a API do agente estiver dormindo (plano gratuito da Render), a primeira busca pode levar até 1 minuto.
          </p>
        )}
        {erro && (
          <div className="mt-4 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
            <p>{erro}</p>
            {bloqueioAkamai && (
              <p className="mt-2 text-rose-600">
                O site ainda bloqueia a API do agente. Esta aba volta a funcionar quando o TI liberar o acesso no Akamai.
              </p>
            )}
          </div>
        )}
      </section>

      {resultado && resultado.itens.length === 0 && (
        <section className="rounded-2xl border border-slate-200 bg-white p-5 text-sm text-slate-500 shadow-soft md:p-6">
          Nenhum produto com estoque para "{resultado.termo}". Produtos esgotados em todas as variantes não vão para o agente.
        </section>
      )}

      {resultado && resultado.itens.length > 0 && (
        <>
          <p className="mb-3 text-sm text-slate-500">
            {resultado.itens.length} produto(s) para "{resultado.termo}", na ordem em que o agente recebe.
          </p>
          {resultado.itens.map((produto) => <CartaoProduto key={produto.objectId} produto={produto} />)}
        </>
      )}
    </div>
  )
}
