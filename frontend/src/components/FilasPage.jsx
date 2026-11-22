import { useCallback, useEffect, useState } from 'react'
import { DiagnosticoFilas } from './CatalogoAgentePage'

// Painel das filas de atendimento na Omnichat, lojas por regional.
// - Link dos gerentes, sem login (/filas/<chave>): só as lojas.
// - Aba Filas do portal (admin): o mesmo painel com o televendas e o diagnóstico.
// Atualiza sozinho.

const ATUALIZA_MS = 30000
// Destaque: fila ou espera acima disso pede atenção do gerente.
const ALERTA_FILA = 5
const ALERTA_ESPERA_MIN = 15

function min(valor) {
  if (valor === null || valor === undefined) return '–'
  if (valor < 1) return '< 1 min'
  if (valor >= 60) return `${Math.floor(valor / 60)}h${String(Math.round(valor % 60)).padStart(2, '0')}`
  return `${Math.round(valor)} min`
}

function hora(iso) {
  if (!iso) return '–'
  return new Date(iso).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function emAlerta(d) {
  return d.na_fila >= ALERTA_FILA || d.espera_mais_antiga_min >= ALERTA_ESPERA_MIN
}

function Numero({ rotulo, valor, destaque, detalhe }) {
  return (
    <div className="min-w-[110px] flex-1">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">{rotulo}</p>
      <p className={`mt-1 text-2xl font-semibold tabular-nums ${destaque ? 'text-rose-600' : 'text-slate-900'}`}>{valor}</p>
      {detalhe && <p className="text-xs text-slate-500">{detalhe}</p>}
    </div>
  )
}

// Campanha x orgânico só aparece quando a API da Omnichat trouxe a origem.
function origens(d) {
  if (!d.entraram_campanha && !d.entraram_organico) return null
  return `${d.entraram_campanha || 0} campanha · ${d.entraram_organico || 0} orgânico`
}

function Resumo({ titulo, subtitulo, dados }) {
  const alerta = emAlerta(dados)
  return (
    <div className={`rounded-2xl border bg-white p-5 shadow-sm ${alerta ? 'border-rose-300' : 'border-slate-200'}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg font-semibold text-slate-900">{titulo}</h2>
        {subtitulo && <span className="text-sm text-slate-500">{subtitulo}</span>}
      </div>
      <div className="mt-4 flex flex-wrap gap-4">
        <Numero rotulo="Na fila agora" valor={dados.na_fila} destaque={dados.na_fila >= ALERTA_FILA} />
        <Numero rotulo="Espera mais antiga" valor={dados.na_fila ? min(dados.espera_mais_antiga_min) : '–'}
          destaque={dados.espera_mais_antiga_min >= ALERTA_ESPERA_MIN} />
        <Numero rotulo="Entraram hoje" valor={dados.entraram_hoje} detalhe={origens(dados)} />
        <Numero rotulo="Atendidos hoje" valor={dados.atendidos_hoje} />
        <Numero rotulo="Espera média" valor={min(dados.espera_media_min)} />
        <Numero rotulo="Saíram sem atendimento" valor={dados.sem_atendimento_hoje} />
      </div>
    </div>
  )
}

function Regional({ reg, aberta, alternar }) {
  const alerta = reg.lojas.some(emAlerta)
  return (
    <section className={`rounded-2xl border bg-white shadow-sm ${alerta ? 'border-rose-300' : 'border-slate-200'}`}>
      <button type="button" onClick={alternar} className="flex w-full flex-wrap items-center justify-between gap-3 p-5 text-left">
        <div>
          <h2 className="text-lg font-semibold text-slate-900">
            {reg.regional}
          </h2>
          <p className="text-sm text-slate-500">{reg.lojas.length} lojas</p>
        </div>
        <div className="flex flex-wrap items-center gap-5 text-sm">
          <span>Na fila: <strong className={`tabular-nums ${reg.total.na_fila >= ALERTA_FILA ? 'text-rose-600' : 'text-slate-900'}`}>{reg.total.na_fila}</strong></span>
          <span>Atendidos hoje: <strong className="tabular-nums text-slate-900">{reg.total.atendidos_hoje}</strong></span>
          <span>Espera média: <strong className="text-slate-900">{min(reg.total.espera_media_min)}</strong></span>
          <span className="text-slate-400">{aberta ? '▲' : '▼'}</span>
        </div>
      </button>
      {aberta && (
        <div className="overflow-x-auto border-t border-slate-100">
          <table className="w-full min-w-[720px] text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-2">Loja</th>
                <th className="px-3 py-2 text-right">Na fila</th>
                <th className="px-3 py-2 text-right">Espera mais antiga</th>
                <th className="px-3 py-2 text-right">Entraram hoje</th>
                <th className="px-3 py-2 text-right">Atendidos</th>
                <th className="px-3 py-2 text-right">Espera média</th>
                <th className="px-3 py-2 text-right">Sem atendimento</th>
                <th className="px-4 py-2 text-right">Atendimento médio</th>
              </tr>
            </thead>
            <tbody>
              {reg.lojas.map((l) => (
                <tr key={l.filial} className={`border-t border-slate-100 ${emAlerta(l) ? 'bg-rose-50' : ''} ${l.na_omnichat ? '' : 'text-slate-400'}`}>
                  <td className="px-4 py-2">
                    <span className="mr-2 inline-block w-9 tabular-nums text-slate-500">{l.filial}</span>
                    <span className="font-medium text-slate-800">{l.loja}</span>
                  </td>
                  <td className={`px-3 py-2 text-right tabular-nums font-semibold ${l.na_fila >= ALERTA_FILA ? 'text-rose-600' : ''}`}>{l.na_fila}</td>
                  <td className={`px-3 py-2 text-right tabular-nums ${l.espera_mais_antiga_min >= ALERTA_ESPERA_MIN ? 'font-semibold text-rose-600' : ''}`}>
                    {l.na_fila ? min(l.espera_mais_antiga_min) : '–'}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {l.entraram_hoje}
                    {l.entraram_campanha > 0 && <span className="block text-xs text-indigo-600">{l.entraram_campanha} campanha</span>}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{l.atendidos_hoje}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{min(l.espera_media_min)}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{l.sem_atendimento_hoje}</td>
                  <td className="px-4 py-2 text-right tabular-nums">{min(l.atendimento_medio_min)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

export default function FilasPage({ chave, admin = false }) {
  const [dados, setDados] = useState(null)
  const [erro, setErro] = useState('')
  const [abertas, setAbertas] = useState({})

  const carregar = useCallback(async () => {
    try {
      const url = admin ? '/api/agente-ia/fila/painel' : `/api/publico/filas?chave=${encodeURIComponent(chave)}`
      const res = await fetch(url)
      const payload = await res.json().catch(() => null)
      if (!res.ok) throw new Error(payload?.detail || `Erro ${res.status}`)
      setDados(payload)
      setErro('')
    } catch (err) {
      setErro(err instanceof Error ? err.message : 'Não consegui atualizar o painel.')
    }
  }, [chave, admin])

  useEffect(() => {
    if (!admin) document.title = 'Filas de atendimento · iPlace'
    carregar()
    const id = setInterval(carregar, ATUALIZA_MS)
    return () => clearInterval(id)
  }, [carregar])

  const todasAbertas = dados && dados.regionais.every((r) => abertas[r.regional] !== false)

  return (
    <div className={admin ? '' : 'min-h-screen bg-slate-50'}>
      <div className={`mx-auto max-w-7xl space-y-5 ${admin ? 'px-4 py-8 md:px-6 lg:px-8' : 'px-4 py-6 md:px-6'}`}>
        <header className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold text-slate-900">Filas de atendimento</h1>
            <p className="text-sm text-slate-500">
              {admin ? 'Lojas e televendas' : 'Lojas'} na Omnichat · atualiza sozinho a cada 30 s · números de hoje
            </p>
          </div>
          <div className="text-right text-sm text-slate-500">
            {dados && <p>Atualizado às {hora(dados.atualizado_em)}</p>}
            {dados?.ultimo_evento_em && <p className="text-xs">Último evento da Omnichat às {hora(dados.ultimo_evento_em)}</p>}
          </div>
        </header>

        {erro && (
          <p className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
            {erro}{dados ? ' Mostrando a última atualização.' : ''}
          </p>
        )}
        {!dados && !erro && <p className="text-sm text-slate-400">Carregando...</p>}

        {dados && (
          <>
            {admin && dados.link_filas && (
              <p className="rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600">
                Link dos gerentes (só lojas, sem o televendas):{' '}
                <a href={dados.link_filas} target="_blank" rel="noreferrer" className="break-all text-indigo-700 underline">{dados.link_filas}</a>
              </p>
            )}
            <div className={`grid gap-4 ${'televendas' in dados ? 'lg:grid-cols-2' : ''}`}>
              {'televendas' in dados && (dados.televendas ? (
                <Resumo titulo="Televendas" dados={dados.televendas} />
              ) : (
                <div className="rounded-2xl border border-dashed border-slate-300 bg-white p-5 text-sm text-slate-500">
                  <h2 className="text-lg font-semibold text-slate-900">Televendas</h2>
                  <p className="mt-2">Escolha o time do televendas na aba Catálogo do Agente (painel Televendas).</p>
                </div>
              ))}
              <Resumo titulo="Todas as lojas" subtitulo={`${dados.regionais.length} regionais`} dados={dados.total_lojas} />
            </div>

            <div className="flex items-center justify-between">
              <p className="text-xs text-slate-500">
                Em vermelho: {ALERTA_FILA} ou mais clientes na fila, ou alguém esperando há {ALERTA_ESPERA_MIN} min ou mais.
                Lojas em cinza ainda não receberam atendimento pela Omnichat hoje.
              </p>
              <button
                type="button"
                onClick={() => setAbertas(Object.fromEntries(dados.regionais.map((r) => [r.regional, !todasAbertas])))}
                className="shrink-0 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-100"
              >
                {todasAbertas ? 'Recolher todas' : 'Abrir todas'}
              </button>
            </div>

            <div className="space-y-4">
              {dados.regionais.map((reg) => (
                <Regional
                  key={reg.regional}
                  reg={reg}
                  aberta={abertas[reg.regional] !== false}
                  alternar={() => setAbertas((a) => ({ ...a, [reg.regional]: a[reg.regional] === false }))}
                />
              ))}
            </div>
            <p className="pb-4 text-xs text-slate-400">
              Fila = cliente encaminhado para o time da loja e ainda não pego por um vendedor. Espera = tempo entre entrar
              no time e ser pego. Esperas acima de 2 h saem da conta.
            </p>
            {admin && <DiagnosticoFilas />}
          </>
        )}
      </div>
    </div>
  )
}
