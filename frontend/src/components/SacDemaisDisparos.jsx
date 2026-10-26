import { useCallback, useState } from 'react'
import { BotaoVoltar, extrairDetalheErro, formatarData } from './sacUtils'

const ROTULO_CANAL = { email: 'E-mail', sms: 'SMS', whatsapp: 'WhatsApp' }

// Classes completas (nao interpoladas) pra sobreviver ao scan do Tailwind.
const ESTILO_SELO = {
  verde: 'bg-emerald-50 text-emerald-700',
  azul: 'bg-sky-50 text-sky-700',
  cinza: 'bg-slate-100 text-slate-500',
  vermelho: 'bg-rose-50 text-rose-700',
}

function statusDoDisparo(item) {
  if (item.canal === 'email') {
    if (item.entregue === false) return { texto: 'Voltou (bounce)', cor: 'vermelho' }
    return item.abriu ? { texto: 'Abriu', cor: 'verde' } : { texto: 'Não abriu', cor: 'cinza' }
  }
  if (item.canal === 'whatsapp') {
    if (item.abriu) return { texto: 'Lida', cor: 'verde' }
    return item.entregue ? { texto: 'Entregue', cor: 'azul' } : { texto: 'Não entregue', cor: 'vermelho' }
  }
  // SMS nao tem abertura - so confirmacao de entrega da operadora.
  return item.entregue ? { texto: 'Entregue', cor: 'azul' } : { texto: 'Entrega não confirmada', cor: 'cinza' }
}

function falaDeCupom(item) {
  return `${item.campanha || ''} ${item.assunto || ''}`.toLowerCase().includes('cupom')
}

function CartaoCupom({ resultado }) {
  const [copiado, setCopiado] = useState(false)
  const cupom = resultado.cupom_primeira_compra
  const mensagemCupom = (resultado.items || []).find(falaDeCupom)

  const copiar = async () => {
    try {
      await navigator.clipboard.writeText(cupom.valor)
      setCopiado(true)
      setTimeout(() => setCopiado(false), 2000)
    } catch {
      setCopiado(false)
    }
  }

  let corpo
  if (cupom?.erro) {
    corpo = (
      <p className="text-sm text-slate-500">
        Não foi possível consultar o cupom agora ({cupom.erro}). Tente buscar de novo.
      </p>
    )
  } else if (cupom?.valor) {
    corpo = (
      <div className="flex flex-wrap items-center gap-3">
        <span className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-2 font-mono text-lg font-semibold text-emerald-800">
          {cupom.valor}
        </span>
        <button
          type="button"
          onClick={copiar}
          className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-semibold text-slate-600 hover:bg-slate-100"
        >
          {copiado ? 'Copiado!' : 'Copiar cupom'}
        </button>
        <p className="w-full text-xs text-slate-500">
          Se o cliente não recebeu a mensagem, você pode passar o cupom direto para ele.
        </p>
      </div>
    )
  } else {
    corpo = (
      <p className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
        Cliente sem cupom de primeira compra. Ele ainda não fez o cadastro de primeira compra, ou o cupom não foi gerado.
        Oriente o cliente a concluir o cadastro e, se ele disser que já fez, avise o CRM.
      </p>
    )
  }

  return (
    <section className="mb-6 rounded-2xl border border-slate-200 bg-white p-5 shadow-soft md:p-6">
      <h2 className="mb-4 text-sm font-semibold uppercase tracking-wide text-slate-500">Cupom de primeira compra</h2>
      {corpo}
      {cupom?.valor && (
        <p className="mt-4 text-sm text-slate-600">
          {mensagemCupom
            ? `Mensagem do cupom: enviada por ${ROTULO_CANAL[mensagemCupom.canal] || mensagemCupom.canal} em ${formatarData(mensagemCupom.data_envio)} — ${statusDoDisparo(mensagemCupom).texto.toLowerCase()}.`
            : 'Nenhuma mensagem com "cupom" no nome aparece entre os últimos 10 disparos para esse cliente.'}
        </p>
      )}
    </section>
  )
}

function CartaoContato({ resultado }) {
  const optin = resultado.optin_email
  const email = resultado.email_cadastrado
  let textoOptin = 'Não foi possível confirmar agora.'
  if (optin?.disponivel && optin.valor === '1') textoOptin = 'Sim, aceita receber e-mails'
  else if (optin?.disponivel && optin.valor === '2') textoOptin = 'Não (opt-out) — não recebe e-mails'
  else if (optin?.disponivel) textoOptin = `Valor não mapeado: ${optin.valor ?? '-'}`

  return (
    <section className="mb-6 rounded-2xl border border-slate-200 bg-white p-5 shadow-soft md:p-6">
      <dl className="grid gap-4 md:grid-cols-2">
        <div>
          <dt className="text-xs uppercase tracking-wide text-slate-400">E-mail cadastrado</dt>
          <dd className="text-sm text-slate-800">{email?.valor || (email?.erro ? 'Não foi possível consultar' : '-')}</dd>
        </div>
        <div>
          <dt className="text-xs uppercase tracking-wide text-slate-400">Opt-in de e-mail</dt>
          <dd className={`text-sm ${optin?.valor === '2' ? 'font-semibold text-rose-700' : 'text-slate-800'}`}>{textoOptin}</dd>
        </div>
      </dl>
    </section>
  )
}

export default function SacDemaisDisparos({ onVoltar }) {
  const [cpf, setCpf] = useState('')
  const [loading, setLoading] = useState(false)
  const [erro, setErro] = useState('')
  const [resultado, setResultado] = useState(null)

  const handleBuscar = useCallback(async (event) => {
    event.preventDefault()
    const cpfLimpo = cpf.replace(/\D/g, '')
    if (cpfLimpo.length < 3) {
      setErro('Informe um CPF válido.')
      return
    }
    setLoading(true)
    setErro('')
    setResultado(null)
    try {
      const res = await fetch(`/api/open-data/emarsys/ultimos-disparos?cpf=${encodeURIComponent(cpfLimpo)}`)
      const payload = await res.json().catch(() => null)
      if (!res.ok) throw new Error(extrairDetalheErro(payload) || `HTTP ${res.status}`)
      setResultado(payload)
    } catch (err) {
      setErro(err instanceof Error ? err.message : 'Erro ao buscar disparos.')
    } finally {
      setLoading(false)
    }
  }, [cpf])

  return (
    <div className="mx-auto max-w-4xl px-4 py-8 md:px-6 lg:px-8">
      <BotaoVoltar onClick={onVoltar} />
      <section className="mb-6 rounded-2xl bg-gradient-to-r from-indigo-600 to-violet-500 p-6 text-white shadow-soft md:p-8">
        <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">Demais disparos</h1>
        <p className="mt-2 text-sm text-indigo-100 md:text-base">
          Busca pelo CPF do cliente e mostra o cupom de primeira compra e os últimos 10 disparos de CRM (e-mail, SMS e
          WhatsApp), com o status de cada um.
        </p>
      </section>

      <section className="mb-6 rounded-2xl border border-slate-200 bg-white p-5 shadow-soft md:p-6">
        <form onSubmit={handleBuscar} className="flex flex-wrap items-end gap-4">
          <label className="flex flex-col gap-1 text-sm text-slate-600">
            CPF do cliente
            <input
              value={cpf}
              onChange={(e) => setCpf(e.target.value)}
              placeholder="000.000.000-00"
              className="min-w-[220px] rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900"
            />
          </label>
          <button
            type="submit"
            disabled={loading}
            className="rounded-lg bg-slate-900 px-5 py-2 text-sm font-semibold text-white transition hover:bg-slate-700 disabled:opacity-50"
          >
            {loading ? 'Buscando...' : 'Buscar'}
          </button>
        </form>
        {erro && <p className="mt-4 rounded-lg border border-rose-200 bg-rose-50 px-4 py-2 text-sm text-rose-700">{erro}</p>}
      </section>

      {resultado && !resultado.contato_encontrado && (
        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft md:p-6">
          <p className="text-sm text-amber-700">Nenhum cliente encontrado com esse CPF na base de contatos da Emarsys.</p>
        </section>
      )}

      {resultado && resultado.contato_encontrado && (
        <>
          <CartaoCupom resultado={resultado} />
          <CartaoContato resultado={resultado} />

          <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft md:p-6">
            {resultado.items.length === 0 ? (
              <p className="text-sm text-slate-500">
                Cliente encontrado, mas sem disparos de CRM nos últimos {resultado.lookback_dias} dias.
              </p>
            ) : (
              <>
                <h2 className="mb-4 text-sm font-semibold uppercase tracking-wide text-slate-500">
                  Últimos {resultado.items.length} disparo(s)
                </h2>
                <div className="overflow-x-auto">
                  <table className="min-w-full text-sm">
                    <thead>
                      <tr className="border-b border-slate-200 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                        <th className="px-3 py-2">Canal</th>
                        <th className="px-3 py-2">Campanha</th>
                        <th className="px-3 py-2">Data de envio</th>
                        <th className="px-3 py-2">Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {resultado.items.map((item, i) => {
                        const status = statusDoDisparo(item)
                        return (
                          <tr
                            key={`${item.canal}-${item.campanha}-${item.data_envio}`}
                            className={falaDeCupom(item) ? 'bg-amber-50' : i % 2 === 0 ? 'bg-white' : 'bg-slate-50'}
                          >
                            <td className="whitespace-nowrap px-3 py-2 text-slate-700">{ROTULO_CANAL[item.canal] || item.canal}</td>
                            <td className="px-3 py-2 text-slate-700">
                              {item.campanha}
                              {item.assunto && <span className="block text-xs text-slate-400">{item.assunto}</span>}
                            </td>
                            <td className="whitespace-nowrap px-3 py-2 text-slate-700">{formatarData(item.data_envio)}</td>
                            <td className="whitespace-nowrap px-3 py-2">
                              <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${ESTILO_SELO[status.cor]}`}>{status.texto}</span>
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
                <p className="mt-3 text-xs text-slate-400">Linhas em amarelo são mensagens com "cupom" no nome ou no assunto.</p>
              </>
            )}
          </section>
        </>
      )}
    </div>
  )
}
