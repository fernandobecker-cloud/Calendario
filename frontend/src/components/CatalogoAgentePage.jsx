import { useCallback, useEffect, useRef, useState } from 'react'
import { extrairDetalheErro, formatarData } from './sacUtils'

// Aba "Catalogo do agente":
//  - Planilha da campanha: o CRM sobe aqui os produtos e precos que o agente usa
//    enquanto o site esta bloqueado pelo Akamai (plano B).
//  - Busca: mostra exatamente o que a API do agente de IA (servico
//    agente-ia-api) devolve para a Omnichat, venha da planilha ou do site.
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
  const semControle = produto.trackInventory === false
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
                  {esgotado ? <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs">Esgotado</span> : semControle ? 'disponível' : v.quantity}
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
            Descrição que o agente recebe (inclui o preço de loja, se houver)
          </summary>
          <p className="mt-2 whitespace-pre-line">{produto.productDescription}</p>
        </details>
      )}
    </section>
  )
}

function PainelSite({ dados, setDados }) {
  const [script, setScript] = useState('')
  const [copiado, setCopiado] = useState(false)
  const [enviando, setEnviando] = useState(false)
  const [erro, setErro] = useState('')
  const [sucesso, setSucesso] = useState('')
  const inputRef = useRef(null)

  const copiarScript = async () => {
    setErro('')
    try {
      let texto = script
      if (!texto) {
        const res = await fetch('/api/agente-ia/site/script')
        const payload = await res.json().catch(() => null)
        if (!res.ok) throw new Error(extrairDetalheErro(payload) || `HTTP ${res.status}`)
        texto = payload.script
        setScript(texto)
      }
      await navigator.clipboard.writeText(texto)
      setCopiado(true)
      setTimeout(() => setCopiado(false), 3000)
    } catch (err) {
      setErro(`Não consegui copiar o script: ${err instanceof Error ? err.message : err}`)
    }
  }

  const enviar = async (event) => {
    const arquivo = event.target.files?.[0]
    event.target.value = ''
    if (!arquivo) return
    setEnviando(true)
    setErro('')
    setSucesso('')
    try {
      const res = await fetch('/api/agente-ia/site', {
        method: 'POST',
        headers: { 'Content-Type': 'application/octet-stream' },
        body: arquivo,
      })
      const payload = await res.json().catch(() => null)
      if (!res.ok) throw new Error(extrairDetalheErro(payload) || `HTTP ${res.status}`)
      setDados((atual) => ({ ...atual, ...payload }))
      setSucesso(`Gravado: ${payload.site?.produtos || 0} produto(s) do site. O agente passa a usar em até 1 minuto.`)
    } catch (err) {
      setErro(err instanceof Error ? err.message : 'Erro ao enviar o arquivo.')
    } finally {
      setEnviando(false)
    }
  }

  const site = dados?.site
  const cob = dados?.cobertura_site

  return (
    <div className="mt-5 rounded-xl border border-slate-200 bg-slate-50 p-4">
      <h3 className="text-sm font-semibold text-slate-800">Descrições e links do site</h3>
      <p className="mt-1 max-w-3xl text-sm text-slate-500">
        Copia uma vez a descrição comercial e o link de cada produto do site e grava na base. O agente usa isso nas
        linhas da planilha, casando pelo <span className="font-mono text-xs">produto_id</span> ou pelo{' '}
        <span className="font-mono text-xs">sku</span> ou pelo id no fim do <span className="font-mono text-xs">link</span>. Se a linha já tiver link na planilha, vale o da planilha; a
        descrição do site vem antes do texto da coluna <span className="font-mono text-xs">descricao</span>.
      </p>
      <ol className="mt-3 list-decimal space-y-1 pl-5 text-sm text-slate-600">
        <li>Clique em <strong>Copiar script</strong>.</li>
        <li>
          Abra <span className="font-mono text-xs">www.iplace.com.br</span> no Chrome, aperte F12, vá na aba
          <strong> Console</strong>, cole e aperte Enter. (Se o Chrome pedir, digite <span className="font-mono text-xs">allow pasting</span> antes.)
        </li>
        <li>Espere uns 30 segundos: ele baixa o arquivo <span className="font-mono text-xs">produtos_site_iplace.json</span>.</li>
        <li>Volte aqui e clique em <strong>Subir arquivo do site</strong>.</li>
      </ol>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={copiarScript}
          className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-100"
        >
          {copiado ? 'Copiado!' : 'Copiar script'}
        </button>
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          disabled={enviando}
          className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-700 disabled:opacity-50"
        >
          {enviando ? 'Enviando...' : 'Subir arquivo do site'}
        </button>
        <input ref={inputRef} type="file" accept=".json" className="hidden" onChange={enviar} />
        {site ? (
          <span className="text-sm text-slate-500">
            {site.produtos} produto(s) do site, {site.com_descricao} com descrição · por {site.carregado_por} em{' '}
            {formatarData(site.carregado_em)}
          </span>
        ) : (
          <span className="text-sm text-slate-400">Ainda não carregado.</span>
        )}
      </div>
      {cob && (
        <p className={`mt-3 text-sm ${cob.ligadas < cob.linhas ? 'text-amber-700' : 'text-emerald-700'}`}>
          Planilha: {cob.ligadas} de {cob.linhas} linha(s) encontradas no site · {cob.com_descricao} com descrição ·{' '}
          {cob.com_link} com link.
          {cob.ligadas < cob.linhas && ' As demais não bateram com o site pelo produto_id, sku nem link.'}
        </p>
      )}
      {sucesso && <p className="mt-3 rounded-lg bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{sucesso}</p>}
      {erro && <p className="mt-3 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{erro}</p>}
    </div>
  )
}

const MODOS_TELEVENDAS = [
  { valor: 'automatico', rotulo: 'Automático', ajuda: 'Segue a fila do time do televendas na Omnichat: quantidade de clientes esperando e/ou tempo de espera.' },
  { valor: 'disponivel', rotulo: 'Forçar disponível', ajuda: 'A Ana sempre oferece o televendas.' },
  { valor: 'indisponivel', rotulo: 'Forçar indisponível', ajuda: 'A Ana oferece só site ou loja física.' },
]

export function DiagnosticoFilas() {
  const [dados, setDados] = useState(null)
  const [erro, setErro] = useState('')

  const carregar = async () => {
    setErro('')
    try {
      const res = await fetch('/api/agente-ia/fila/diagnostico')
      const payload = await res.json().catch(() => null)
      if (!res.ok) throw new Error(extrairDetalheErro(payload) || `HTTP ${res.status}`)
      setDados(payload)
    } catch (err) {
      setErro(err instanceof Error ? err.message : 'Erro ao ler o diagnóstico.')
    }
  }

  return (
    <details className="mt-3 text-sm" onToggle={(e) => e.target.open && !dados && carregar()}>
      <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wide text-slate-500">
        Diagnóstico das filas (o que chegou da Omnichat)
      </summary>
      {erro && <p className="mt-2 text-rose-700">{erro}</p>}
      {dados && (
        <div className="mt-2 space-y-3 text-slate-600">
          <p>
            {dados.eventos_em_memoria} evento(s) nas últimas 26 h
            {dados.primeiro && <> · de {formatarData(dados.primeiro)} a {formatarData(dados.ultimo)}</>} ·{' '}
            <button type="button" onClick={carregar} className="text-indigo-700 underline">atualizar</button>
          </p>
          <p className="text-xs">
            {Object.entries(dados.por_tipo).map(([tipo, n]) => `${tipo}: ${n}`).join(' · ') || 'nenhum'}
          </p>
          <p className="text-xs">
            <span className="font-medium text-slate-700">API da Omnichat (origem e "assumir"): </span>
            {!dados.omnichat_api ? 'sem resposta da API do agente'
              : !dados.omnichat_api.ligado ? 'desligada (falta OMNI_API_KEY / OMNI_API_SECRET no agente-ia-api)'
              : `ligada · ${dados.omnichat_api.consultas} consulta(s) · acompanhando ${dados.omnichat_api.acompanhando}`
                + ` · id do atendimento: ${dados.omnichat_api.id_do_atendimento || 'ainda não descoberto'}`
                + (dados.omnichat_api.erros ? ` · ${dados.omnichat_api.erros} erro(s), último: ${dados.omnichat_api.ultimo_erro}` : '')
                + (dados.omnichat_api.pausado_ate ? ` · pausada até ${formatarData(dados.omnichat_api.pausado_ate)}` : '')}
          </p>
          {dados.origens_hoje?.length > 0 && (
            <table className="w-full text-xs">
              <thead className="text-left text-slate-500">
                <tr><th className="py-1">Respostas a campanhas hoje (webhook "Resposta de campanha")</th><th>Conta como</th><th className="text-right">Respostas</th></tr>
              </thead>
              <tbody>
                {dados.origens_hoje.map((o) => (
                  <tr key={o.origem} className="border-t border-slate-100">
                    <td className="py-1">{o.origem}</td>
                    <td>{o.classe === 'campanha' ? 'Campanha' : 'Orgânico'}</td>
                    <td className="text-right tabular-nums">{o.atendimentos}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {dados.na_fila_televendas && (
            <div className="rounded-lg border border-slate-200 bg-white p-2">
              <p className="text-xs font-medium text-slate-700">
                Contados agora na fila do televendas ({dados.na_fila_televendas.length}) — compare com a Omnichat
              </p>
              {dados.na_fila_televendas.length > 0 && (
                <div className="mt-1 max-h-[360px] overflow-auto">
                  <table className="w-full text-xs">
                    <thead className="text-left text-slate-500">
                      <tr>
                        <th className="py-1 pr-2">Entrou</th>
                        <th className="pr-2 text-right">Espera</th>
                        <th className="pr-2">Atendimento</th>
                        <th className="pr-2">Último evento</th>
                        <th>Status na API da Omnichat</th>
                      </tr>
                    </thead>
                    <tbody>
                      {dados.na_fila_televendas.map((a) => (
                        <tr key={`${a.conversa}-${a.entrou_em}`} className="border-t border-slate-100 align-top">
                          <td className="py-1 pr-2 whitespace-nowrap">{formatarData(a.entrou_em)}</td>
                          <td className="pr-2 text-right tabular-nums">{a.espera_min} min</td>
                          <td className="pr-2 font-mono">{a.atendimento_id || a.conversa}</td>
                          <td className="pr-2">
                            {a.ultimo_evento || '-'}
                            {a.ultimo_evento_em && <span className="text-slate-400"> · {formatarData(a.ultimo_evento_em)}</span>}
                          </td>
                          <td>{a.status_api}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
          {dados.saidas_da_fila && (
            <p className="text-xs">
              <span className="font-medium text-slate-700">Como saíram da fila: </span>
              {Object.entries(dados.saidas_da_fila).map(([como, n]) => `${como}: ${n}`).join(' · ') || 'nenhum ainda'}
            </p>
          )}
          {dados.ultimos_eventos_completos?.length > 0 && (
            <details className="rounded-lg border border-slate-200 bg-slate-50 p-2 text-xs">
              <summary className="cursor-pointer font-medium text-slate-700">
                Últimos {dados.ultimos_eventos_completos.length} eventos completos (sem telefone)
              </summary>
              <div className="mt-2 max-h-[480px] space-y-2 overflow-auto">
                {dados.ultimos_eventos_completos.map((b, i) => (
                  <pre key={i} className="whitespace-pre-wrap break-all rounded bg-white p-2 text-[11px] text-slate-700">
                    {formatarData(b.recebido_em)} · {JSON.stringify(b.evento, null, 2)}
                  </pre>
                ))}
              </div>
            </details>
          )}
          {dados.encaminhado_para_lojas_por?.length > 0 && (
            <table className="w-full text-xs">
              <thead className="text-left text-slate-500">
                <tr><th className="py-1">Quem encaminhou para as lojas hoje</th><th className="text-right">Atendimentos</th></tr>
              </thead>
              <tbody>
                {dados.encaminhado_para_lojas_por.map((q) => (
                  <tr key={q.quem} className="border-t border-slate-100">
                    <td className="py-1">{q.quem}</td>
                    <td className="text-right tabular-nums">{q.hoje}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <table className="w-full text-xs">
            <thead className="text-left text-slate-500">
              <tr><th className="py-1">Time na Omnichat</th><th>No painel como</th><th className="text-right">Eventos (hoje)</th></tr>
            </thead>
            <tbody>
              {dados.times.map((t) => (
                <tr key={t.id} className="border-t border-slate-100">
                  <td className="py-1">{t.nome || t.id}</td>
                  <td className={t.classificacao === 'Fora do painel' ? 'text-slate-400' : 'text-slate-800'}>{t.classificacao}</td>
                  <td className="text-right tabular-nums">{t.eventos} ({t.hoje})</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </details>
  )
}

function PainelTelevendas() {
  const [dados, setDados] = useState(null)
  const [form, setForm] = useState({
    modo: 'disponivel', time_id: '', limite_desliga: 15, limite_religa: 8, espera_desliga_min: '', espera_religa_min: '',
  })
  const [salvando, setSalvando] = useState(false)
  const [erro, setErro] = useState('')
  const [sucesso, setSucesso] = useState('')

  const aplicar = useCallback((payload) => {
    setDados(payload)
    const c = payload?.config
    if (c) {
      setForm({
        modo: c.modo || 'disponivel',
        time_id: c.time_id || '',
        // 0 = critério desligado: aparece vazio. Config antiga (sem os campos de tempo) mantém a fila.
        limite_desliga: c.limite_desliga == null ? 15 : (c.limite_desliga || ''),
        limite_religa: c.limite_desliga ? (c.limite_religa ?? 8) : '',
        espera_desliga_min: c.espera_desliga_min || '',
        espera_religa_min: c.espera_desliga_min ? (c.espera_religa_min ?? '') : '',
      })
    }
  }, [])

  const carregar = useCallback(async () => {
    try {
      const res = await fetch('/api/agente-ia/televendas')
      const payload = await res.json().catch(() => null)
      if (!res.ok) throw new Error(extrairDetalheErro(payload) || `HTTP ${res.status}`)
      aplicar(payload)
    } catch (err) {
      setErro(err instanceof Error ? err.message : 'Erro ao ler o televendas.')
    }
  }, [aplicar])

  useEffect(() => {
    carregar()
    const id = setInterval(carregar, 30000)
    return () => clearInterval(id)
  }, [carregar])

  const salvar = async (event) => {
    event.preventDefault()
    setSalvando(true)
    setErro('')
    setSucesso('')
    try {
      const time = dados?.fila?.times?.find((t) => t.id === form.time_id)
      const res = await fetch('/api/agente-ia/televendas', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...form, time_nome: time?.nome || dados?.config?.time_nome || null }),
      })
      const payload = await res.json().catch(() => null)
      if (!res.ok) throw new Error(extrairDetalheErro(payload) || `HTTP ${res.status}`)
      aplicar(payload)
      setSucesso('Salvo. O agente passa a usar em até 30 segundos.')
    } catch (err) {
      setErro(err instanceof Error ? err.message : 'Erro ao salvar.')
    } finally {
      setSalvando(false)
    }
  }

  const fila = dados?.fila
  const times = fila?.times || []
  const configurado = dados?.config
  const timeSalvo = configurado?.time_id
  const opcoesTime = timeSalvo && !times.some((t) => t.id === timeSalvo)
    ? [{ id: timeSalvo, nome: configurado.time_nome, na_fila: 0 }, ...times]
    : times

  return (
    <section className="mb-6 rounded-2xl border border-slate-200 bg-white p-5 shadow-soft md:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-slate-900">Televendas</h2>
          <p className="mt-1 max-w-3xl text-sm text-slate-500">
            Com o televendas indisponível, a Ana oferece só site ou loja física. No automático, a API do agente conta a
            fila do time do televendas pelos webhooks da Omnichat.
          </p>
        </div>
        {fila ? (
          <span className={`rounded-full px-3 py-1 text-sm font-semibold ${fila.disponivel ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-800'}`}>
            {fila.disponivel ? 'Ana oferece televendas' : 'Ana NÃO oferece televendas'}
          </span>
        ) : (
          <span className="rounded-full bg-slate-100 px-3 py-1 text-sm text-slate-500">API do agente sem resposta</span>
        )}
      </div>

      <form onSubmit={salvar} className="mt-4 space-y-4">
        <div className="flex flex-wrap gap-2">
          {MODOS_TELEVENDAS.map((m) => (
            <label
              key={m.valor}
              className={`cursor-pointer rounded-lg border px-4 py-2 text-sm ${form.modo === m.valor ? 'border-slate-900 bg-slate-900 text-white' : 'border-slate-300 text-slate-700 hover:bg-slate-50'}`}
              title={m.ajuda}
            >
              <input
                type="radio"
                name="modo-televendas"
                value={m.valor}
                checked={form.modo === m.valor}
                onChange={() => setForm((f) => ({ ...f, modo: m.valor }))}
                className="hidden"
              />
              {m.rotulo}
            </label>
          ))}
        </div>
        <p className="text-xs text-slate-400">{MODOS_TELEVENDAS.find((m) => m.valor === form.modo)?.ajuda}</p>

        <div className="flex flex-wrap items-start gap-4">
            <label className="flex min-w-[240px] flex-col gap-1 text-sm text-slate-600">
              Time do televendas na Omnichat
              <select
                value={form.time_id}
                onChange={(e) => setForm((f) => ({ ...f, time_id: e.target.value }))}
                className="rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900"
              >
                <option value="">{opcoesTime.length ? 'Escolha o time' : 'Nenhum time apareceu nos webhooks ainda'}</option>
                {opcoesTime.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.nome || t.id} ({t.na_fila} na fila)
                  </option>
                ))}
              </select>
              <span className="text-xs text-slate-400">a lista vem dos eventos da Omnichat · usado também no painel das filas</span>
            </label>
            {form.modo === 'automatico' && (
            <>
            <fieldset className="flex flex-wrap gap-4 rounded-lg border border-slate-200 px-3 pb-3 pt-1">
              <legend className="px-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Por fila</legend>
              <label className="flex w-44 flex-col gap-1 text-sm text-slate-600">
                Desligar com
                <input
                  type="number"
                  min="1"
                  placeholder="desligado"
                  value={form.limite_desliga}
                  onChange={(e) => setForm((f) => ({ ...f, limite_desliga: e.target.value }))}
                  className="rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900"
                />
                <span className="text-xs text-slate-400">clientes esperando ou mais</span>
              </label>
              <label className="flex w-44 flex-col gap-1 text-sm text-slate-600">
                Religar com
                <input
                  type="number"
                  min="0"
                  value={form.limite_religa}
                  onChange={(e) => setForm((f) => ({ ...f, limite_religa: e.target.value }))}
                  className="rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900"
                />
                <span className="text-xs text-slate-400">clientes esperando ou menos</span>
              </label>
            </fieldset>
            <fieldset className="flex flex-wrap gap-4 rounded-lg border border-slate-200 px-3 pb-3 pt-1">
              <legend className="px-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Por tempo de espera</legend>
              <label className="flex w-44 flex-col gap-1 text-sm text-slate-600">
                Desligar com
                <input
                  type="number"
                  min="1"
                  placeholder="desligado"
                  value={form.espera_desliga_min}
                  onChange={(e) => setForm((f) => ({ ...f, espera_desliga_min: e.target.value }))}
                  className="rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900"
                />
                <span className="text-xs text-slate-400">min ou mais de espera do cliente mais antigo</span>
              </label>
              <label className="flex w-44 flex-col gap-1 text-sm text-slate-600">
                Religar com
                <input
                  type="number"
                  min="0"
                  value={form.espera_religa_min}
                  onChange={(e) => setForm((f) => ({ ...f, espera_religa_min: e.target.value }))}
                  className="rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900"
                />
                <span className="text-xs text-slate-400">min ou menos</span>
              </label>
            </fieldset>
            <p className="w-full text-xs text-slate-400">
              Deixe o "desligar com" vazio para não usar aquele critério. Com os dois preenchidos, desliga quando
              qualquer um passar do limite e só religa quando os dois voltarem ao limite de religar.
            </p>
            </>
            )}
          </div>

        <button
          type="submit"
          disabled={salvando}
          className="rounded-lg bg-slate-900 px-5 py-2 text-sm font-semibold text-white transition hover:bg-slate-700 disabled:opacity-50"
        >
          {salvando ? 'Salvando...' : 'Salvar'}
        </button>
      </form>

      {fila && (
        <p className="mt-4 text-sm text-slate-500">
          {fila.config?.time_id ? (
            <>
              Fila agora: <strong className="text-slate-800">{fila.na_fila}</strong> cliente(s) esperando
              {fila.na_fila > 0 && <> · o mais antigo há {fila.espera_mais_antiga_min} min</>} ·{' '}
            </>
          ) : null}
          {fila.eventos_recebidos} evento(s) da Omnichat recebidos
          {fila.ultimo_evento ? <> · último em {formatarData(fila.ultimo_evento)}</> : ' (webhook ainda não chegou)'} ·
          contando desde {formatarData(fila.contando_desde)}
        </p>
      )}
      <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
        <strong className="text-slate-800">Painel das filas para os gerentes</strong> (só as lojas, por regional, sem login; o televendas fica na aba Filas):{' '}
        {dados?.link_filas ? (
          <>
            <a href={dados.link_filas} target="_blank" rel="noreferrer" className="font-medium text-indigo-700 underline">
              abrir
            </a>
            {' · '}
            <button
              type="button"
              onClick={() => navigator.clipboard.writeText(dados.link_filas)}
              className="font-medium text-indigo-700 underline"
            >
              copiar link
            </button>
            <span className="text-slate-400"> · para cortar o acesso, troque FILAS_LINK_CHAVE no Render.</span>
          </>
        ) : (
          <span className="text-slate-500">crie a variável FILAS_LINK_CHAVE no serviço do portal no Render para gerar o link.</span>
        )}
      </div>
      <DiagnosticoFilas />
      {configurado?.alterado_por && (
        <p className="mt-1 text-xs text-slate-400">
          Alterado por {configurado.alterado_por} em {formatarData(configurado.alterado_em)}
        </p>
      )}
      {sucesso && <p className="mt-3 rounded-lg bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{sucesso}</p>}
      {erro && <p className="mt-3 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{erro}</p>}
    </section>
  )
}

const CAMPOS_AJUSTE = [
  ['preco_de', 'Preço "de"'],
  ['preco_por', 'Preço Pix (por)'],
  ['preco_cartao', 'Preço cartão'],
  ['preco_loja', 'Preço loja'],
  ['estoque', 'Estoque'],
]
const NOMES_CAMPO = { preco_de: 'de', preco_por: 'Pix', preco_pix: 'Pix', preco_cartao: 'cartão', preco_loja: 'loja', estoque: 'estoque', ativo: 'ativo' }

function semAcento(texto) {
  return String(texto || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase()
}

// Ajuste pontual de preço/estoque de alguns SKUs, sem subir a planilha toda.
function AjustePontual({ dados, setDados }) {
  const [busca, setBusca] = useState('')
  const [marcados, setMarcados] = useState([])
  const [valores, setValores] = useState({})
  const [limparCartao, setLimparCartao] = useState(false)
  const [ativo, setAtivo] = useState('')
  const [enviando, setEnviando] = useState(false)
  const [msg, setMsg] = useState({ ok: '', erro: '', erros: [] })

  const linhas = dados?.planilha?.linhas || []
  const termos = semAcento(busca).split(/\s+/).filter(Boolean)
  const achados = termos.length
    ? linhas.filter((l) => {
      const alvo = semAcento(`${l.sku} ${l.produto} ${l.variante || ''} ${l.capacidade || ''} ${l.cor || ''}`)
      return termos.every((t) => alvo.includes(t))
    })
    : []
  const visiveis = achados.slice(0, 40)
  const selecionadas = linhas.filter((l) => marcados.includes(String(l.sku)))
  const alternar = (sku) => setMarcados((m) => (m.includes(sku) ? m.filter((x) => x !== sku) : [...m, sku]))
  const todosVisiveis = visiveis.length > 0 && visiveis.every((l) => marcados.includes(String(l.sku)))

  const campos = {}
  CAMPOS_AJUSTE.forEach(([k]) => { if (String(valores[k] ?? '').trim()) campos[k] = valores[k] })
  if (limparCartao) campos.preco_cartao = ''
  if (ativo) campos.ativo = ativo === 'S'
  const cartaoAntigo = campos.preco_por && !('preco_cartao' in campos)
    && selecionadas.some((l) => l.preco_cartao != null)

  const aplicar = async () => {
    setEnviando(true)
    setMsg({ ok: '', erro: '', erros: [] })
    try {
      const res = await fetch('/api/agente-ia/planilha/skus', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ skus: marcados, campos }),
      })
      const payload = await res.json().catch(() => null)
      if (!res.ok) {
        const d = payload?.detail
        if (d && Array.isArray(d.erros)) { setMsg({ ok: '', erro: d.mensagem, erros: d.erros }); return }
        throw new Error(extrairDetalheErro(payload) || `HTTP ${res.status}`)
      }
      setDados((atual) => ({ ...atual, ...payload }))
      const n = new Set((payload.feitos || []).map((f) => f.sku)).size
      setMsg({ ok: n ? `${n} SKU(s) alterado(s). O agente passa a usar em até 2 minutos.` : 'Nada mudou: os valores já eram esses.', erro: '', erros: [] })
      setValores({})
      setLimparCartao(false)
      setAtivo('')
    } catch (err) {
      setMsg({ ok: '', erro: err instanceof Error ? err.message : 'Falhou.', erros: [] })
    } finally {
      setEnviando(false)
    }
  }

  if (!linhas.length) return null
  const ajustes = dados?.ajustes || []
  return (
    <details className="mt-4 rounded-xl border border-slate-200 p-4 text-sm" open={marcados.length > 0 || undefined}>
      <summary className="cursor-pointer font-semibold text-slate-800">
        Ajuste pontual de preço / estoque{ajustes.length > 0 && ` · ${ajustes.length} ajuste(s) desde a planilha atual`}
      </summary>
      <p className="mt-2 text-xs text-slate-500">
        Busque pelo SKU ou pelo nome (ex.: "17 pro max 256"), marque os SKUs e preencha só o que muda; campo vazio fica como
        está. Subir uma planilha nova substitui tudo, inclusive estes ajustes: leve-os para a planilha antes.
      </p>
      <input value={busca} onChange={(e) => setBusca(e.target.value)} placeholder="SKU ou nome do produto"
        className="mt-3 w-full max-w-md rounded-lg border border-slate-300 px-3 py-2 text-sm" />
      {termos.length > 0 && (
        <div className="mt-2 max-h-72 overflow-auto">
          <table className="min-w-full text-xs">
            <thead>
              <tr className="border-b border-slate-200 text-left font-semibold text-slate-500">
                <th className="px-2 py-1.5">
                  <input type="checkbox" checked={todosVisiveis} onChange={() => setMarcados((m) => (todosVisiveis
                    ? m.filter((x) => !visiveis.some((l) => String(l.sku) === x))
                    : [...new Set([...m, ...visiveis.map((l) => String(l.sku))])]))} />
                </th>
                <th className="px-2 py-1.5">SKU</th>
                <th className="px-2 py-1.5">Produto</th>
                <th className="px-2 py-1.5 text-right">De</th>
                <th className="px-2 py-1.5 text-right">Pix</th>
                <th className="px-2 py-1.5 text-right">Cartão</th>
                <th className="px-2 py-1.5 text-right">Loja</th>
                <th className="px-2 py-1.5 text-right">Estoque</th>
              </tr>
            </thead>
            <tbody>
              {visiveis.map((l) => (
                <tr key={l.sku} onClick={() => alternar(String(l.sku))}
                  className={`cursor-pointer border-b border-slate-100 ${marcados.includes(String(l.sku)) ? 'bg-indigo-50' : ''} ${l.ativo === false ? 'text-slate-400 line-through' : ''}`}>
                  <td className="px-2 py-1.5"><input type="checkbox" readOnly checked={marcados.includes(String(l.sku))} /></td>
                  <td className="px-2 py-1.5">{l.sku}</td>
                  <td className="px-2 py-1.5">{l.produto} {l.variante || [l.capacidade, l.cor].filter(Boolean).join(' ')}</td>
                  <td className="whitespace-nowrap px-2 py-1.5 text-right">{moeda(l.preco_de)}</td>
                  <td className="whitespace-nowrap px-2 py-1.5 text-right">{moeda(l.preco_pix ?? l.preco_por)}</td>
                  <td className="whitespace-nowrap px-2 py-1.5 text-right">{l.preco_cartao != null ? moeda(l.preco_cartao) : 'Pix ÷ 0,9'}</td>
                  <td className="whitespace-nowrap px-2 py-1.5 text-right">{moeda(l.preco_loja)}</td>
                  <td className="px-2 py-1.5 text-right">{l.estoque ?? 'disponível'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-1 text-xs text-slate-400">
            {achados.length} encontrado(s){achados.length > visiveis.length && `, mostrando ${visiveis.length}: refine a busca`}
          </p>
        </div>
      )}
      {marcados.length > 0 && (
        <div className="mt-3 rounded-lg bg-slate-50 p-3">
          <p className="text-xs text-slate-600">
            {marcados.length} SKU(s) marcado(s): {marcados.join(', ')}{' '}
            <button type="button" onClick={() => setMarcados([])} className="text-indigo-600 hover:underline">limpar</button>
          </p>
          <div className="mt-2 flex flex-wrap items-end gap-3">
            {CAMPOS_AJUSTE.map(([k, rotulo]) => (
              <label key={k} className="text-xs text-slate-600">
                {rotulo}
                <input value={valores[k] ?? ''} onChange={(e) => setValores((v) => ({ ...v, [k]: e.target.value }))}
                  disabled={k === 'preco_cartao' && limparCartao} placeholder={k === 'estoque' ? '0 = esgotado' : 'R$'}
                  className="mt-1 block w-28 rounded-lg border border-slate-300 px-2 py-1.5 text-sm disabled:bg-slate-100" />
              </label>
            ))}
            <label className="text-xs text-slate-600">
              Ativo
              <select value={ativo} onChange={(e) => setAtivo(e.target.value)}
                className="mt-1 block rounded-lg border border-slate-300 px-2 py-1.5 text-sm">
                <option value="">manter</option>
                <option value="S">sim</option>
                <option value="N">não (tira do agente)</option>
              </select>
            </label>
            <button type="button" disabled={enviando || !Object.keys(campos).length} onClick={aplicar}
              className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">
              {enviando ? 'Aplicando...' : `Aplicar em ${marcados.length} SKU(s)`}
            </button>
          </div>
          <label className="mt-2 flex items-center gap-2 text-xs text-slate-600">
            <input type="checkbox" checked={limparCartao} onChange={(e) => {
              setLimparCartao(e.target.checked)
              if (e.target.checked) setValores((v) => ({ ...v, preco_cartao: '' }))
            }} />
            Preço cartão em branco (o agente calcula Pix ÷ 0,9, como no site)
          </label>
          {cartaoAntigo && (
            <p className="mt-2 text-xs text-amber-700">
              Atenção: você mudou o Pix, mas o preço no cartão (base do parcelamento) continua o antigo. Preencha o novo
              preço no cartão ou marque a opção acima.
            </p>
          )}
        </div>
      )}
      {msg.ok && <p className="mt-3 rounded-lg bg-emerald-50 px-3 py-2 text-xs text-emerald-700">{msg.ok}</p>}
      {msg.erro && (
        <div className="mt-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
          <p>{msg.erro}</p>
          {msg.erros.length > 0 && <ul className="mt-1 list-disc pl-5">{msg.erros.map((e) => <li key={e}>{e}</li>)}</ul>}
        </div>
      )}
      {ajustes.length > 0 && (
        <details className="mt-3 text-xs text-slate-600">
          <summary className="cursor-pointer">Ajustes desde a planilha atual ({ajustes.length})</summary>
          <ul className="mt-2 space-y-1">
            {ajustes.map((a, i) => (
              <li key={i}>
                {formatarData(a.em)} · {a.usuario} · {a.sku} {a.produto} · {NOMES_CAMPO[a.campo] || a.campo}:{' '}
                {a.antes || 'vazio'} → {a.depois || 'vazio'}
              </li>
            ))}
          </ul>
        </details>
      )}
    </details>
  )
}

function PainelPlanilha() {
  const [dados, setDados] = useState(null)
  const [carregando, setCarregando] = useState(true)
  const [enviando, setEnviando] = useState(false)
  const [erro, setErro] = useState('')
  const [errosPlanilha, setErrosPlanilha] = useState([])
  const [avisos, setAvisos] = useState([])
  const [sucesso, setSucesso] = useState('')
  const inputRef = useRef(null)

  const carregar = useCallback(async () => {
    setCarregando(true)
    try {
      const res = await fetch('/api/agente-ia/planilha')
      const payload = await res.json().catch(() => null)
      if (!res.ok) throw new Error(extrairDetalheErro(payload) || `HTTP ${res.status}`)
      setDados(payload)
    } catch (err) {
      setErro(err instanceof Error ? err.message : 'Erro ao carregar a planilha.')
    } finally {
      setCarregando(false)
    }
  }, [])

  useEffect(() => { carregar() }, [carregar])

  const enviar = async (event) => {
    const arquivo = event.target.files?.[0]
    event.target.value = ''
    if (!arquivo) return
    setEnviando(true)
    setErro('')
    setErrosPlanilha([])
    setAvisos([])
    setSucesso('')
    try {
      const res = await fetch(`/api/agente-ia/planilha?arquivo=${encodeURIComponent(arquivo.name)}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/octet-stream' },
        body: arquivo,
      })
      const payload = await res.json().catch(() => null)
      if (!res.ok) {
        const detalhe = payload?.detail
        if (detalhe && Array.isArray(detalhe.erros)) {
          setErro(detalhe.mensagem)
          setErrosPlanilha(detalhe.erros)
          return
        }
        throw new Error(extrairDetalheErro(payload) || `HTTP ${res.status}`)
      }
      setDados((atual) => ({ ...atual, ...payload }))
      setAvisos(payload.avisos || [])
      setSucesso(`Planilha carregada: ${payload.planilha?.linhas?.length || 0} linha(s). O agente passa a usar em até 1 minuto.`)
    } catch (err) {
      setErro(err instanceof Error ? err.message : 'Erro ao enviar a planilha.')
    } finally {
      setEnviando(false)
    }
  }

  // Download via fetch: o login do portal so injeta a credencial no fetch,
  // um <a href> direto para /api daria 401.
  const baixarModelo = async () => {
    try {
      const res = await fetch('/api/agente-ia/planilha/modelo')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const url = URL.createObjectURL(await res.blob())
      const link = document.createElement('a')
      link.href = url
      link.download = 'modelo_planilha_agente.csv'
      link.click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (err) {
      setErro(`Não consegui baixar o modelo: ${err instanceof Error ? err.message : err}`)
    }
  }

  const planilha = dados?.planilha
  const linhas = planilha?.linhas || []
  const ativas = linhas.filter((l) => l.ativo !== false)
  const produtos = new Set(ativas.map((l) => (l.produto_id || l.produto || '').toLowerCase())).size
  const fonte = dados?.agente?.fonte

  return (
    <section className="mb-6 rounded-2xl border border-slate-200 bg-white p-5 shadow-soft md:p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold text-slate-900">Planilha da campanha</h2>
          <p className="mt-1 max-w-2xl text-sm text-slate-500">
            Enquanto o site estiver bloqueado para a API, o agente usa os produtos e preços desta planilha. Uma linha
            por SKU. Ao subir uma nova, ela substitui a anterior inteira.
          </p>
        </div>
        <span className={`rounded-full px-3 py-1 text-xs font-semibold ${
          fonte === 'planilha' ? 'bg-emerald-50 text-emerald-700'
            : fonte === 'site' ? 'bg-indigo-50 text-indigo-700' : 'bg-slate-100 text-slate-500'}`}
        >
          {fonte === 'planilha' ? 'Agente usando: planilha'
            : fonte === 'site' ? 'Agente usando: site (a planilha não é usada)' : 'Agente: fonte não confirmada'}
        </span>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          disabled={enviando}
          className="rounded-lg bg-slate-900 px-5 py-2 text-sm font-semibold text-white transition hover:bg-slate-700 disabled:opacity-50"
        >
          {enviando ? 'Enviando...' : 'Subir planilha (.xlsx ou .csv)'}
        </button>
        <input ref={inputRef} type="file" accept=".xlsx,.csv" className="hidden" onChange={enviar} />
        <button
          type="button"
          onClick={baixarModelo}
          className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-100"
        >
          Baixar modelo
        </button>
        {carregando ? (
          <span className="text-sm text-slate-400">Carregando...</span>
        ) : planilha ? (
          <span className="text-sm text-slate-500">
            Atual: <strong className="text-slate-700">{planilha.arquivo}</strong> · {ativas.length} SKU(s) ativos em{' '}
            {produtos} produto(s) · por {planilha.carregado_por} em {formatarData(planilha.carregado_em)}
          </span>
        ) : (
          <span className="text-sm text-amber-600">Nenhuma planilha carregada ainda.</span>
        )}
      </div>

      {sucesso && <p className="mt-4 rounded-lg bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{sucesso}</p>}
      {erro && (
        <div className="mt-4 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          <p>{erro}</p>
          {errosPlanilha.length > 0 && (
            <ul className="mt-2 list-disc pl-5">{errosPlanilha.map((e) => <li key={e}>{e}</li>)}</ul>
          )}
        </div>
      )}
      {avisos.length > 0 && (
        <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-700">
          <p>Carregada, mas confira:</p>
          <ul className="mt-2 list-disc pl-5">{avisos.map((a) => <li key={a}>{a}</li>)}</ul>
        </div>
      )}

      <AjustePontual dados={dados} setDados={setDados} />

      <PainelSite dados={dados} setDados={setDados} />

      {dados?.colunas && (
        <details className="mt-4 text-sm text-slate-600">
          <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wide text-slate-500">
            Colunas da planilha
          </summary>
          <table className="mt-2 min-w-full text-sm">
            <tbody>
              {dados.colunas.map((c) => (
                <tr key={c.nome} className="border-b border-slate-100">
                  <td className="whitespace-nowrap py-1.5 pr-4 font-mono text-xs text-slate-700">
                    {c.nome}{c.obrigatoria && <span className="ml-1 text-rose-500">*</span>}
                  </td>
                  <td className="py-1.5">{c.explicacao}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-2 text-xs text-slate-400">* obrigatória. Preços aceitam "R$ 10.921,11" ou "10921.11".</p>
        </details>
      )}

      {linhas.length > 0 && (
        <details className="mt-3 text-sm text-slate-600">
          <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wide text-slate-500">
            Linhas carregadas ({linhas.length})
          </summary>
          <div className="mt-2 max-h-96 overflow-auto">
            <table className="min-w-full text-xs">
              <thead>
                <tr className="border-b border-slate-200 text-left font-semibold uppercase tracking-wide text-slate-500">
                  <th className="px-2 py-1.5">Linha</th>
                  <th className="px-2 py-1.5">SKU</th>
                  <th className="px-2 py-1.5">Produto</th>
                  <th className="px-2 py-1.5 text-right">De</th>
                  <th className="px-2 py-1.5 text-right">Por / Pix (site)</th>
                  <th className="px-2 py-1.5 text-right">Cartão</th>
                  <th className="px-2 py-1.5 text-right">Loja</th>
                  <th className="px-2 py-1.5 text-right">Estoque</th>
                  <th className="px-2 py-1.5">Link</th>
                </tr>
              </thead>
              <tbody>
                {linhas.map((l) => (
                  <tr key={l.sku} className={`border-b border-slate-100 ${l.ativo === false ? 'text-slate-400 line-through' : ''}`}>
                    <td className="px-2 py-1.5">{l.linha}</td>
                    <td className="px-2 py-1.5">{l.sku}</td>
                    <td className="px-2 py-1.5">{l.produto} {l.variante || [l.capacidade, l.cor].filter(Boolean).join(' ')}</td>
                    <td className="whitespace-nowrap px-2 py-1.5 text-right">{moeda(l.preco_de)}</td>
                    <td className="whitespace-nowrap px-2 py-1.5 text-right">{moeda(l.preco_pix ?? l.preco_por)}</td>
                    <td className="whitespace-nowrap px-2 py-1.5 text-right">{l.preco_cartao != null ? moeda(l.preco_cartao) : 'Pix ÷ 0,9'}</td>
                    <td className="whitespace-nowrap px-2 py-1.5 text-right">{moeda(l.preco_loja)}</td>
                    <td className="px-2 py-1.5 text-right">{l.estoque ?? 'disponível'}</td>
                    <td className="px-2 py-1.5">
                      {l.link ? <a href={l.link} target="_blank" rel="noreferrer" className="text-indigo-600 hover:underline">abrir</a> : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
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
          estoque. Use a busca abaixo para conferir com a página do produto no site.
        </p>
      </section>

      <PainelTelevendas />
      <PainelPlanilha />

      <section className="mb-6 rounded-2xl border border-slate-200 bg-white p-5 shadow-soft md:p-6">
        <h2 className="mb-4 text-lg font-semibold text-slate-900">O que o agente responde</h2>
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
