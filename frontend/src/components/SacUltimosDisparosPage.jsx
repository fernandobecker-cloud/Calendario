import { useCallback, useState } from 'react'

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

export default function SacUltimosDisparosPage() {
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
      const res = await fetch(`/api/open-data/emarsys/ultimos-disparos-email?cpf=${encodeURIComponent(cpfLimpo)}`)
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

      {resultado && resultado.contato_encontrado && (
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

      {resultado && (
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
