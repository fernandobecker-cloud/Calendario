import { useCallback, useMemo, useState } from 'react'

function extrairDetalheErro(payload) {
  const detail = payload?.detail
  if (!detail) return ''
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map((d) => d?.msg || JSON.stringify(d)).join('; ')
  return JSON.stringify(detail)
}

function formatarData(iso) {
  if (!iso) return '-'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  return d.toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}

function formatarValorGarantia(valor) {
  if (valor === null || valor === undefined || valor === '') return '-'
  if (typeof valor === 'string' && /^\d{4}-\d{2}-\d{2}/.test(valor)) return formatarData(valor)
  return String(valor)
}

// Rotulos amigaveis pros campos conhecidos da tabela garantia_estendida
// (carregada por fora, pode ganhar colunas novas sem avisar - por isso o
// componente mostra qualquer campo extra tambem, so sem rotulo bonito).
// Serial/IMEI/Origem existem na tabela mas o SAC pediu pra nao mostrar -
// sao dados tecnicos irrelevantes pro atendimento.
const LABELS_GARANTIA = {
  ge_contrato: 'Contrato',
  ge_data_venda: 'Data da venda',
  ge_data_validade: 'Validade',
  ge_Nome: 'Nome',
  ge_produto: 'Produto',
  CPF: 'CPF',
}
const CAMPOS_GARANTIA_OCULTOS = new Set(['ge_serial', 'GE_IMEI', 'Origem'])

function CampoGarantia({ campo, valor }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-xs uppercase tracking-wide text-slate-400">{LABELS_GARANTIA[campo] || campo}</dt>
      <dd className="text-sm text-slate-800">{formatarValorGarantia(valor)}</dd>
    </div>
  )
}

function normalizarTexto(valor) {
  return (valor || '')
    .normalize('NFD')
    .replace(/\p{Diacritic}/gu, '')
    .toLowerCase()
}

// Classes completas (nao interpoladas) pra sobreviver ao scan estatico do
// Tailwind em build de producao. Cada status do passo tem cor + selo fixos.
const ESTILO_STATUS_PASSO = {
  ok: {
    caixa: 'border-emerald-200 bg-emerald-50',
    selo: 'bg-emerald-500 text-white',
    marca: '✓',
    titulo: 'text-emerald-800',
    texto: 'text-emerald-700',
  },
  atencao: {
    caixa: 'border-sky-200 bg-sky-50',
    selo: 'bg-sky-500 text-white',
    marca: '!',
    titulo: 'text-sky-800',
    texto: 'text-sky-700',
  },
  bloqueio: {
    caixa: 'border-amber-300 bg-amber-50 ring-2 ring-amber-300',
    selo: 'bg-amber-500 text-white',
    marca: '!',
    titulo: 'text-amber-900',
    texto: 'text-amber-800',
  },
  erro: {
    caixa: 'border-slate-200 bg-slate-50',
    selo: 'bg-slate-400 text-white',
    marca: '?',
    titulo: 'text-slate-700',
    texto: 'text-slate-600',
  },
  pendente: {
    caixa: 'border-slate-100 bg-slate-50 opacity-60',
    selo: 'bg-slate-300 text-white',
    marca: '–',
    titulo: 'text-slate-500',
    texto: 'text-slate-400',
  },
}

// Roteiro passado pelo SAC: 3 passos, cada um so avaliado se o anterior
// nao bloqueou o atendimento. Devolve os 3 sempre (mesmo os "pendente",
// ainda nao avaliados) pra o atendente ver o roteiro inteiro, nao so o
// resultado final - pedido explicito pra ser didatico.
function calcularPassos({ garantia, erroGarantia, resultado, erro }) {
  const PENDENTE_1 = { numero: 1, titulo: 'Está na base do comercial?', texto: 'Ainda não verificado.', status: 'pendente' }
  const PENDENTE_2 = { numero: 2, titulo: 'Opt-in de e-mail', texto: 'Não avaliado - resolva o passo 1 primeiro.', status: 'pendente' }
  const PENDENTE_3 = { numero: 3, titulo: 'E-mail de garantia estendida foi enviado e aberto?', texto: 'Não avaliado - resolva os passos anteriores primeiro.', status: 'pendente' }

  if (!garantia && !erroGarantia) return [PENDENTE_1, PENDENTE_2, PENDENTE_3]

  if (erroGarantia) {
    return [
      { numero: 1, titulo: 'Está na base do comercial?', texto: 'Não foi possível verificar agora. Tente buscar de novo.', status: 'erro' },
      { ...PENDENTE_2, texto: 'Não avaliado - não foi possível verificar o passo 1.' },
      { ...PENDENTE_3, texto: 'Não avaliado - não foi possível verificar o passo 1.' },
    ]
  }

  const encontrado = garantia.encontrado
  const passo1 = {
    numero: 1,
    titulo: 'Está na base do comercial?',
    texto: encontrado
      ? 'Sim, o cliente está na base de garantia estendida.'
      : 'Não. Peça para o cliente aguardar — a garantia estendida está sendo emitida.',
    status: encontrado ? 'ok' : 'bloqueio',
  }
  if (!encontrado) return [passo1, PENDENTE_2, PENDENTE_3]

  if (erro) {
    return [
      passo1,
      { numero: 2, titulo: 'Opt-in de e-mail', texto: 'Não foi possível verificar agora. Confira manualmente antes de responder ao cliente.', status: 'erro' },
      { ...PENDENTE_3, texto: 'Não avaliado - não foi possível verificar o passo 2.' },
    ]
  }

  const optin = resultado?.optin_email
  const optOut = optin?.disponivel && optin.valor === '2'
  const passo2 = {
    numero: 2,
    titulo: 'Opt-in de e-mail',
    texto: optOut
      ? 'Cliente está com opt-out. Peça para ele mudar a preferência no site e avise o CRM para refazer o disparo assim que ele atualizar.'
      : 'Cliente pode receber e-mail (não está em opt-out).',
    status: optOut ? 'bloqueio' : 'ok',
  }
  if (optOut) return [passo1, passo2, PENDENTE_3]

  const emailsGarantia = (resultado?.items || []).filter((item) => normalizarTexto(item.campanha).includes('garantia'))
  if (emailsGarantia.length === 0) {
    return [
      passo1,
      passo2,
      {
        numero: 3,
        titulo: 'E-mail de garantia estendida foi enviado e aberto?',
        texto: resultado?.email_cadastrado?.disponivel
          ? `Não encontramos esse e-mail entre os últimos enviados a esse cliente. Confirme com ele se o e-mail cadastrado (${resultado.email_cadastrado.valor}) está correto e avise o CRM para verificar o que aconteceu.`
          : 'Não encontramos esse e-mail entre os últimos enviados a esse cliente. Confirme com ele se o e-mail cadastrado está correto e avise o CRM para verificar o que aconteceu.',
        status: 'bloqueio',
      },
    ]
  }

  const abriu = emailsGarantia[0].abriu
  const dataEnvio = formatarData(emailsGarantia[0].data_envio)
  const emailAtual = resultado?.email_cadastrado?.disponivel ? resultado.email_cadastrado.valor : null
  const trechoEmail = emailAtual ? ` E-mail cadastrado atualmente: ${emailAtual}.` : ''
  return [
    passo1,
    passo2,
    {
      numero: 3,
      titulo: 'E-mail de garantia estendida foi enviado e aberto?',
      texto: abriu
        ? `Sim, o e-mail foi enviado em ${dataEnvio} e o cliente já abriu. Nenhuma ação pendente aqui.${trechoEmail}`
        : `O e-mail foi enviado em ${dataEnvio}, mas o cliente ainda não abriu. Peça para ele olhar a caixa de entrada e a pasta de spam/lixo eletrônico.${trechoEmail}`,
      status: abriu ? 'ok' : 'atencao',
    },
  ]
}

export default function SacUltimosDisparosPage() {
  const [cpf, setCpf] = useState('')
  const [loading, setLoading] = useState(false)
  const [erro, setErro] = useState('')
  const [resultado, setResultado] = useState(null)
  const [garantia, setGarantia] = useState(null)
  const [erroGarantia, setErroGarantia] = useState('')
  const [buscaFeita, setBuscaFeita] = useState(false)

  const mostrarResultados = buscaFeita && !loading

  const passos = useMemo(
    () => (mostrarResultados ? calcularPassos({ garantia, erroGarantia, resultado, erro }) : []),
    [mostrarResultados, garantia, erroGarantia, resultado, erro],
  )

  const handleBuscar = useCallback(async (event) => {
    event.preventDefault()
    const cpfLimpo = cpf.replace(/\D/g, '')
    if (cpfLimpo.length < 3) {
      setErro('Informe um CPF válido.')
      return
    }
    setBuscaFeita(true)
    setLoading(true)
    setErro('')
    setResultado(null)
    setGarantia(null)
    setErroGarantia('')

    const buscaEmail = fetch(`/api/open-data/emarsys/ultimos-disparos-email?cpf=${encodeURIComponent(cpfLimpo)}`)
      .then(async (res) => {
        const payload = await res.json().catch(() => null)
        if (!res.ok) throw new Error(extrairDetalheErro(payload) || `HTTP ${res.status}`)
        setResultado(payload)
      })
      .catch((err) => setErro(err instanceof Error ? err.message : 'Erro ao buscar disparos.'))

    const buscaGarantia = fetch(`/api/open-data/comercial/garantia-estendida?cpf=${encodeURIComponent(cpfLimpo)}`)
      .then(async (res) => {
        const payload = await res.json().catch(() => null)
        if (!res.ok) throw new Error(extrairDetalheErro(payload) || `HTTP ${res.status}`)
        setGarantia(payload)
      })
      .catch((err) => setErroGarantia(err instanceof Error ? err.message : 'Erro ao buscar garantia estendida.'))

    await Promise.all([buscaEmail, buscaGarantia])
    setLoading(false)
  }, [cpf])

  return (
    <div className="mx-auto max-w-4xl px-4 py-8 md:px-6 lg:px-8">
      <section className="mb-6 rounded-2xl bg-gradient-to-r from-indigo-600 to-violet-500 p-6 text-white shadow-soft md:p-8">
        <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">Últimos Disparos (SAC)</h1>
        <p className="mt-2 text-sm text-indigo-100 md:text-base">
          Busca pelo CPF do cliente e mostra os últimos 5 e-mails de CRM enviados a ele, com data e se foi aberto.
          Cobre apenas e-mail — outros canais (SMS, WhatsApp) não aparecem aqui.
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

      {mostrarResultados && passos.length > 0 && (
        <section className="mb-6 rounded-2xl border border-slate-200 bg-white p-5 shadow-soft md:p-6">
          <h2 className="mb-4 text-sm font-semibold uppercase tracking-wide text-slate-500">Roteiro de atendimento</h2>
          <ol className="flex flex-col gap-3">
            {passos.map((passo) => {
              const estilo = ESTILO_STATUS_PASSO[passo.status]
              return (
                <li key={passo.numero} className={`flex gap-3 rounded-xl border p-4 ${estilo.caixa}`}>
                  <span className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-bold ${estilo.selo}`}>
                    {estilo.marca}
                  </span>
                  <div>
                    <p className={`text-sm font-semibold ${estilo.titulo}`}>Passo {passo.numero} — {passo.titulo}</p>
                    <p className={`text-sm ${estilo.texto}`}>{passo.texto}</p>
                  </div>
                </li>
              )
            })}
          </ol>
        </section>
      )}

      {mostrarResultados && (garantia || erroGarantia) && (
        <section className="mb-6 rounded-2xl border border-slate-200 bg-white p-5 shadow-soft md:p-6">
          <h2 className="mb-4 text-sm font-semibold uppercase tracking-wide text-slate-500">Garantia estendida</h2>
          {erroGarantia ? (
            <p className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-2 text-sm text-rose-700">{erroGarantia}</p>
          ) : !garantia.encontrado ? (
            <p className="text-sm text-slate-500">Nenhum contrato de garantia estendida encontrado para esse CPF.</p>
          ) : (
            <div className="flex flex-col gap-4">
              {garantia.items.map((item, i) => (
                <dl key={item.ge_contrato ?? i} className="grid grid-cols-2 gap-x-4 gap-y-3 rounded-xl bg-slate-50 p-4 md:grid-cols-3">
                  {Object.entries(item)
                    .filter(([campo]) => !CAMPOS_GARANTIA_OCULTOS.has(campo))
                    .map(([campo, valor]) => (
                      <CampoGarantia key={campo} campo={campo} valor={valor} />
                    ))}
                </dl>
              ))}
            </div>
          )}
        </section>
      )}

      {mostrarResultados && resultado && resultado.contato_encontrado && (
        <section className="mb-6 rounded-2xl border border-slate-200 bg-white p-5 shadow-soft md:p-6">
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">Opt-in de e-mail</h2>
          {resultado.optin_email?.disponivel ? (
            resultado.optin_email.valor === '1' ? (
              <p className="text-sm">
                <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700">Sim, optou por receber</span>
              </p>
            ) : resultado.optin_email.valor === '2' ? (
              <p className="text-sm">
                <span className="rounded-full bg-rose-50 px-2 py-0.5 text-xs font-medium text-rose-700">Não, não recebe e-mails</span>
              </p>
            ) : (
              <p className="text-sm text-slate-700">
                Valor do campo: <span className="font-mono font-semibold">{String(resultado.optin_email.valor ?? '-')}</span>
                <span className="ml-2 text-xs text-slate-400">(só "1" e "2" estão confirmados - esse valor ainda não foi mapeado)</span>
              </p>
            )
          ) : (
            <p className="text-sm text-slate-400">
              Não foi possível confirmar o opt-in agora{resultado.optin_email?.erro ? ` (${resultado.optin_email.erro})` : ''}.
            </p>
          )}
        </section>
      )}

      {mostrarResultados && resultado && (
        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft md:p-6">
          {!resultado.contato_encontrado ? (
            <p className="text-sm text-amber-700">
              Nenhum cliente encontrado com esse CPF na base de contatos da Emarsys.
            </p>
          ) : resultado.items.length === 0 ? (
            <p className="text-sm text-slate-500">
              Cliente encontrado, mas sem e-mails de CRM enviados nos últimos {resultado.lookback_dias} dias.
            </p>
          ) : (
            <>
              <h2 className="mb-4 text-sm font-semibold uppercase tracking-wide text-slate-500">
                Últimos {resultado.items.length} e-mail(s) enviado(s)
              </h2>
              <div className="overflow-x-auto">
                <table className="min-w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-200 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                      <th className="px-3 py-2">Campanha</th>
                      <th className="px-3 py-2">Data de envio</th>
                      <th className="px-3 py-2">Abriu?</th>
                    </tr>
                  </thead>
                  <tbody>
                    {resultado.items.map((item, i) => (
                      <tr key={`${item.campanha}-${item.data_envio}`} className={i % 2 === 0 ? 'bg-white' : 'bg-slate-50'}>
                        <td className="px-3 py-2 text-slate-700">{item.campanha}</td>
                        <td className="whitespace-nowrap px-3 py-2 text-slate-700">{formatarData(item.data_envio)}</td>
                        <td className="whitespace-nowrap px-3 py-2">
                          {item.abriu ? (
                            <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700">Sim</span>
                          ) : (
                            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-500">Não</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </section>
      )}
    </div>
  )
}
