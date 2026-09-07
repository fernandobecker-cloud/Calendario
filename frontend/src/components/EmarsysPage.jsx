import { useCallback, useEffect, useMemo, useState } from 'react'
import JSZip from 'jszip'

function base64ParaBlob(base64, mimeType = 'text/csv') {
  const bytes = atob(base64)
  const array = new Uint8Array(bytes.length)
  for (let i = 0; i < bytes.length; i += 1) array[i] = bytes.charCodeAt(i)
  return new Blob([array], { type: mimeType })
}

function baixarBlob(blob, nomeArquivo) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = nomeArquivo
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

function StatusBadge({ resultado }) {
  if (!resultado) {
    return <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-500">Aguardando</span>
  }
  if (resultado.ja_enviado) {
    return <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-500">Ja enviado</span>
  }
  if (resultado.pendente) {
    return <span className="rounded-full bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-700">Pendente ({resultado.status_atual || '...'})</span>
  }
  if (resultado.ok) {
    return <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700">OK</span>
  }
  return <span className="rounded-full bg-rose-50 px-2 py-0.5 text-xs font-medium text-rose-700">Falha</span>
}

function ResultadoDetalhe({ resultado }) {
  if (!resultado) return null
  if (resultado.erro) {
    return <p className="text-xs text-rose-700">{resultado.erro}</p>
  }
  const excluidos = resultado.excluidos_opt_out
  return (
    <div className="space-y-1 text-xs text-slate-600">
      {resultado.grupos_no_export && (
        <p>
          Contatos a enviar:{' '}
          {Object.entries(resultado.grupos_no_export).map(([cod, n]) => `${cod}: ${n}`).join(', ') || '0'}
        </p>
      )}
      {excluidos && (
        <p className="text-amber-700">
          Excluidos por opt-out: {Object.entries(excluidos).map(([cod, n]) => `${cod}: ${n}`).join(', ')}
        </p>
      )}
      {Array.isArray(resultado.envios) && resultado.envios.map((envio, i) => (
        <p key={i}>
          {resultado.baixar_arquivo ? (
            <>Loja {envio.codigo_loja}: {envio.contatos} contato(s) - {envio.arquivo_nome ? `arquivo "${envio.arquivo_nome}" baixado` : (envio.motivo || 'sem arquivo')}</>
          ) : (
            <>
              Loja {envio.codigo_loja}: {envio.contatos} contato(s) -{' '}
              {envio.enviado ? 'enviado' : resultado.dry_run ? 'simulado' : (envio.erro || envio.motivo || 'nao enviado')} para{' '}
              {(envio.destinatarios || []).join(', ') || '-'}
            </>
          )}
        </p>
      ))}
    </div>
  )
}

export default function EmarsysPage() {
  const [lojas, setLojas] = useState([])
  const [lojasLoading, setLojasLoading] = useState(true)
  const [lojasErro, setLojasErro] = useState('')

  const [filialSelecionada, setFilialSelecionada] = useState('')
  const [campanhaIndividual, setCampanhaIndividual] = useState('')
  const [dryRunIndividual, setDryRunIndividual] = useState(true)
  const [emailTesteIndividual, setEmailTesteIndividual] = useState('')
  const [baixarArquivoIndividual, setBaixarArquivoIndividual] = useState(false)
  const [individualLoading, setIndividualLoading] = useState(false)
  const [individualErro, setIndividualErro] = useState('')
  const [individualResultado, setIndividualResultado] = useState(null)

  const [campanhaMassa, setCampanhaMassa] = useState('')
  const [dryRunMassa, setDryRunMassa] = useState(true)
  const [confirmarMassa, setConfirmarMassa] = useState(false)
  const [emailTesteMassa, setEmailTesteMassa] = useState('')
  const [baixarArquivoMassa, setBaixarArquivoMassa] = useState(false)

  const [iniciarLoading, setIniciarLoading] = useState(false)
  const [iniciarErro, setIniciarErro] = useState('')
  const [iniciarResumo, setIniciarResumo] = useState(null)
  const [lotePendente, setLotePendente] = useState([])
  const [loteTotal, setLoteTotal] = useState([])

  const [coletarLoading, setColetarLoading] = useState(false)
  const [coletarErro, setColetarErro] = useState('')
  const [coletarResumoUltima, setColetarResumoUltima] = useState(null)
  const [resultadosPorFilial, setResultadosPorFilial] = useState({})

  const loadLojas = useCallback(async () => {
    setLojasLoading(true)
    setLojasErro('')
    try {
      const res = await fetch('/api/emarsys/lojas')
      const payload = await res.json().catch(() => null)
      if (!res.ok) throw new Error(payload?.detail || `HTTP ${res.status}`)
      setLojas(payload?.items || [])
    } catch (err) {
      setLojasErro(err instanceof Error ? err.message : 'Erro ao carregar lojas.')
    } finally {
      setLojasLoading(false)
    }
  }, [])

  useEffect(() => {
    loadLojas()
  }, [loadLojas])

  const totalProntas = useMemo(() => lojas.filter((l) => l.segmento_base_id).length, [lojas])

  const handleEnviarIndividual = useCallback(async (event) => {
    event.preventDefault()
    if (!filialSelecionada) {
      setIndividualErro('Selecione uma loja.')
      return
    }
    setIndividualLoading(true)
    setIndividualErro('')
    setIndividualResultado(null)
    try {
      const params = new URLSearchParams({
        campanha: campanhaIndividual,
        dry_run: String(dryRunIndividual),
        email_teste: emailTesteIndividual,
        baixar_arquivo: String(baixarArquivoIndividual),
      })
      const res = await fetch(`/api/emarsys/enviar/${filialSelecionada}?${params}`, { method: 'POST' })
      const payload = await res.json().catch(() => null)
      if (!res.ok) throw new Error(payload?.detail || `HTTP ${res.status}`)
      setIndividualResultado(payload)
      if (baixarArquivoIndividual) {
        for (const envio of payload.envios || []) {
          if (envio.arquivo_base64) {
            baixarBlob(base64ParaBlob(envio.arquivo_base64), envio.arquivo_nome)
          }
        }
      }
    } catch (err) {
      setIndividualErro(err instanceof Error ? err.message : 'Erro ao enviar.')
    } finally {
      setIndividualLoading(false)
    }
  }, [filialSelecionada, campanhaIndividual, dryRunIndividual, emailTesteIndividual, baixarArquivoIndividual])

  const handleIniciar = useCallback(async () => {
    setIniciarLoading(true)
    setIniciarErro('')
    try {
      const res = await fetch('/api/emarsys/enviar-todas/iniciar', { method: 'POST' })
      const payload = await res.json().catch(() => null)
      if (!res.ok) throw new Error(payload?.detail || `HTTP ${res.status}`)
      setIniciarResumo(payload)
      setLoteTotal(payload?.lote || [])
      setLotePendente(payload?.lote || [])
      setResultadosPorFilial({})
      setColetarResumoUltima(null)
    } catch (err) {
      setIniciarErro(err instanceof Error ? err.message : 'Erro ao iniciar exportacao.')
    } finally {
      setIniciarLoading(false)
    }
  }, [])

  const handleColetar = useCallback(async () => {
    if (lotePendente.length === 0) return
    if (!baixarArquivoMassa && !dryRunMassa && !confirmarMassa) {
      setColetarErro('Marque "Confirmar envio real" (alem de desmarcar simulacao) para mandar de verdade.')
      return
    }
    setColetarLoading(true)
    setColetarErro('')
    try {
      const params = new URLSearchParams({
        campanha: campanhaMassa,
        dry_run: String(dryRunMassa),
        confirmar: String(confirmarMassa),
        email_teste: emailTesteMassa,
        baixar_arquivo: String(baixarArquivoMassa),
      })
      const res = await fetch(`/api/emarsys/enviar-todas/coletar?${params}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ lote: lotePendente }),
      })
      const payload = await res.json().catch(() => null)
      if (!res.ok) throw new Error(payload?.detail || `HTTP ${res.status}`)

      setResultadosPorFilial((prev) => {
        const next = { ...prev }
        for (const r of payload.resultados || []) next[r.filial] = r
        return next
      })
      const aindaPendentes = new Set((payload.resultados || []).filter((r) => r.pendente).map((r) => r.filial))
      setLotePendente((prev) => prev.filter((item) => aindaPendentes.has(item.filial)))
      setColetarResumoUltima(payload)

      if (baixarArquivoMassa) {
        const zip = new JSZip()
        let arquivos = 0
        for (const r of payload.resultados || []) {
          for (const envio of r.envios || []) {
            if (envio.arquivo_base64) {
              zip.file(envio.arquivo_nome, base64ParaBlob(envio.arquivo_base64))
              arquivos += 1
            }
          }
        }
        if (arquivos > 0) {
          const blob = await zip.generateAsync({ type: 'blob' })
          const agora = new Date().toISOString().slice(0, 16).replace(':', 'h')
          baixarBlob(blob, `emarsys_lojas_${agora}.zip`)
        }
      }
    } catch (err) {
      setColetarErro(err instanceof Error ? err.message : 'Erro ao coletar envios.')
    } finally {
      setColetarLoading(false)
    }
  }, [lotePendente, dryRunMassa, confirmarMassa, campanhaMassa, emailTesteMassa, baixarArquivoMassa])

  return (
    <div className="mx-auto max-w-7xl px-4 py-8 md:px-6 lg:px-8">
      <section className="mb-6 rounded-2xl bg-gradient-to-r from-indigo-600 to-violet-500 p-6 text-white shadow-soft md:p-8">
        <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">Emarsys - Envio de Listas</h1>
        <p className="mt-2 text-sm text-indigo-100 md:text-base">
          Exporta os segmentos de cada loja, aplica o filtro de opt-out de WhatsApp e envia por e-mail
          para o gerente/subgerente. Isolamento entre lojas e exclusao de opt-out sao sempre aplicados.
        </p>
      </section>

      <section className="mb-6 rounded-2xl border border-slate-200 bg-white p-5 shadow-soft md:p-6">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-lg font-semibold text-slate-900">Lojas mapeadas</h2>
          <button
            onClick={loadLojas}
            disabled={lojasLoading}
            className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-semibold text-slate-700 transition hover:bg-slate-100 disabled:opacity-50"
          >
            {lojasLoading ? 'Carregando...' : 'Atualizar'}
          </button>
        </div>
        {lojasErro && <p className="mb-3 rounded-lg border border-rose-200 bg-rose-50 px-4 py-2 text-sm text-rose-700">{lojasErro}</p>}
        <p className="text-sm text-slate-600">
          {lojas.length} loja(s) no mapeamento - {totalProntas} com segmento ja configurado (
          <code className="rounded bg-slate-100 px-1">segmento_base_id</code>), {lojas.length - totalProntas} ainda sem.
        </p>
        <details className="mt-3">
          <summary className="cursor-pointer text-sm font-medium text-slate-700">Ver lista completa</summary>
          <div className="mt-2 max-h-64 overflow-y-auto overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                  <th className="px-3 py-2">Filial</th>
                  <th className="px-3 py-2">Descricao</th>
                  <th className="px-3 py-2">Regional</th>
                  <th className="px-3 py-2">Pronta?</th>
                </tr>
              </thead>
              <tbody>
                {lojas.map((loja, i) => (
                  <tr key={loja.filial} className={i % 2 === 0 ? 'bg-white' : 'bg-slate-50'}>
                    <td className="whitespace-nowrap px-3 py-1.5 text-slate-700">{loja.filial}</td>
                    <td className="whitespace-nowrap px-3 py-1.5 text-slate-700">{loja.descricao}</td>
                    <td className="whitespace-nowrap px-3 py-1.5 text-slate-700">{loja.regional}</td>
                    <td className="whitespace-nowrap px-3 py-1.5">
                      {loja.segmento_base_id ? (
                        <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700">Sim</span>
                      ) : (
                        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-500">Nao</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      </section>

      <section className="mb-6 rounded-2xl border border-slate-200 bg-white p-5 shadow-soft md:p-6">
        <h2 className="mb-4 text-lg font-semibold text-slate-900">Envio individual (uma loja)</h2>
        <form onSubmit={handleEnviarIndividual} className="flex flex-wrap items-end gap-4">
          <label className="flex flex-col gap-1 text-sm text-slate-600">
            Loja
            <select
              value={filialSelecionada}
              onChange={(e) => setFilialSelecionada(e.target.value)}
              className="min-w-[220px] rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900"
            >
              <option value="">Selecione...</option>
              {lojas.map((loja) => (
                <option key={loja.filial} value={loja.filial}>
                  {loja.filial} - {loja.descricao}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-sm text-slate-600">
            Campanha
            <input
              value={campanhaIndividual}
              onChange={(e) => setCampanhaIndividual(e.target.value)}
              placeholder="ex: NPI Setembro"
              className="rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900"
            />
          </label>
          {!baixarArquivoIndividual && (
            <label className="flex flex-col gap-1 text-sm text-slate-600">
              E-mail de teste (opcional)
              <input
                value={emailTesteIndividual}
                onChange={(e) => setEmailTesteIndividual(e.target.value)}
                placeholder="seuemail@iplace.com.br"
                className="rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900"
              />
            </label>
          )}
          {!baixarArquivoIndividual && (
            <label className="flex items-center gap-2 pb-2 text-sm text-slate-600">
              <input type="checkbox" checked={dryRunIndividual} onChange={(e) => setDryRunIndividual(e.target.checked)} />
              Simular (dry run)
            </label>
          )}
          <label className="flex items-center gap-2 pb-2 text-sm text-slate-600">
            <input type="checkbox" checked={baixarArquivoIndividual} onChange={(e) => setBaixarArquivoIndividual(e.target.checked)} />
            Baixar arquivo (em vez de enviar por e-mail)
          </label>
          <button
            type="submit"
            disabled={individualLoading}
            className="rounded-lg bg-slate-900 px-5 py-2 text-sm font-semibold text-white transition hover:bg-slate-700 disabled:opacity-50"
          >
            {individualLoading ? 'Processando...' : baixarArquivoIndividual ? 'Baixar CSV' : dryRunIndividual ? 'Simular envio' : 'Enviar de verdade'}
          </button>
        </form>
        {individualErro && (
          <p className="mt-4 rounded-lg border border-rose-200 bg-rose-50 px-4 py-2 text-sm text-rose-700">{individualErro}</p>
        )}
        {individualResultado && (
          <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50 p-4">
            <div className="mb-2 flex items-center gap-2">
              <StatusBadge resultado={individualResultado} />
              <span className="text-xs text-slate-500">
                {individualResultado.baixar_arquivo ? 'Arquivo baixado' : individualResultado.dry_run ? 'Simulacao' : 'Envio real'}
              </span>
            </div>
            <ResultadoDetalhe resultado={individualResultado} />
          </div>
        )}
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft md:p-6">
        <h2 className="mb-1 text-lg font-semibold text-slate-900">Envio em massa (todas as lojas)</h2>
        <p className="mb-4 text-sm text-slate-500">
          Fluxo em duas etapas: primeiro dispara a exportacao de todas as lojas de uma vez (rapido), depois
          coleta o resultado de cada uma - repita "Coletar" ate nenhuma loja ficar pendente, ja que o tempo
          de exportacao varia bastante de loja para loja.
        </p>

        <div className="mb-4 flex flex-wrap items-end gap-4">
          <label className="flex flex-col gap-1 text-sm text-slate-600">
            Campanha
            <input
              value={campanhaMassa}
              onChange={(e) => setCampanhaMassa(e.target.value)}
              placeholder="ex: NPI Setembro"
              className="rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900"
            />
          </label>
          {!baixarArquivoMassa && (
            <label className="flex flex-col gap-1 text-sm text-slate-600">
              E-mail de teste (opcional)
              <input
                value={emailTesteMassa}
                onChange={(e) => setEmailTesteMassa(e.target.value)}
                placeholder="seuemail@iplace.com.br"
                className="rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900"
              />
            </label>
          )}
          {!baixarArquivoMassa && (
            <label className="flex items-center gap-2 pb-2 text-sm text-slate-600">
              <input type="checkbox" checked={dryRunMassa} onChange={(e) => setDryRunMassa(e.target.checked)} />
              Simular (dry run)
            </label>
          )}
          {!baixarArquivoMassa && !dryRunMassa && (
            <label className="flex items-center gap-2 pb-2 text-sm font-semibold text-rose-700">
              <input type="checkbox" checked={confirmarMassa} onChange={(e) => setConfirmarMassa(e.target.checked)} />
              Confirmar envio real em massa
            </label>
          )}
          <label className="flex items-center gap-2 pb-2 text-sm text-slate-600">
            <input type="checkbox" checked={baixarArquivoMassa} onChange={(e) => setBaixarArquivoMassa(e.target.checked)} />
            Baixar arquivos (.zip) em vez de enviar por e-mail
          </label>
        </div>

        <div className="flex flex-wrap gap-3">
          <button
            onClick={handleIniciar}
            disabled={iniciarLoading}
            className="rounded-lg bg-slate-900 px-5 py-2 text-sm font-semibold text-white transition hover:bg-slate-700 disabled:opacity-50"
          >
            {iniciarLoading ? 'Disparando...' : '1. Iniciar exportacao de todas as lojas'}
          </button>
          <button
            onClick={handleColetar}
            disabled={coletarLoading || lotePendente.length === 0}
            className="rounded-lg border border-slate-300 px-5 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {coletarLoading
              ? 'Coletando...'
              : `2. Coletar e ${baixarArquivoMassa ? 'baixar' : 'enviar'} (${lotePendente.length} pendente(s))`}
          </button>
        </div>

        {iniciarErro && (
          <p className="mt-4 rounded-lg border border-rose-200 bg-rose-50 px-4 py-2 text-sm text-rose-700">{iniciarErro}</p>
        )}
        {coletarErro && (
          <p className="mt-4 rounded-lg border border-rose-200 bg-rose-50 px-4 py-2 text-sm text-rose-700">{coletarErro}</p>
        )}

        {iniciarResumo && (
          <p className="mt-4 text-sm text-slate-600">
            Exportacao disparada: {iniciarResumo.iniciados} de {iniciarResumo.total_lojas} lojas
            {iniciarResumo.falhas > 0 && (
              <>
                {' '}- <span className="text-amber-700">{iniciarResumo.falhas} falharam ao achar o segmento</span>
                <details className="mt-1 inline">
                  <summary className="inline cursor-pointer text-xs text-slate-500">ver erros</summary>
                  <ul className="mt-1 list-disc pl-5 text-xs text-slate-600">
                    {(iniciarResumo.erros || []).map((e) => (
                      <li key={e.filial}>{e.filial}: {e.erro}</li>
                    ))}
                  </ul>
                </details>
              </>
            )}
          </p>
        )}

        {coletarResumoUltima && (
          <p className="mt-2 text-sm text-slate-600">
            Ultima coleta: {coletarResumoUltima.sucesso} concluida(s), {coletarResumoUltima.pendente} ainda pendente(s), {coletarResumoUltima.falha} falha(s)
            {baixarArquivoMassa ? ' (arquivos baixados em .zip)' : coletarResumoUltima.dry_run ? ' (simulacao)' : ' (envio real)'}.
          </p>
        )}

        {loteTotal.length > 0 && (
          <div className="mt-4 max-h-[28rem] overflow-y-auto overflow-x-auto rounded-lg border border-slate-200">
            <table className="min-w-full text-sm">
              <thead className="sticky top-0 bg-white">
                <tr className="border-b border-slate-200 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                  <th className="px-3 py-2">Filial</th>
                  <th className="px-3 py-2">Status</th>
                  <th className="px-3 py-2">Detalhes</th>
                </tr>
              </thead>
              <tbody>
                {loteTotal.map((item, i) => (
                  <tr key={item.filial} className={i % 2 === 0 ? 'bg-white' : 'bg-slate-50'}>
                    <td className="whitespace-nowrap px-3 py-2 align-top text-slate-700">{item.filial}</td>
                    <td className="whitespace-nowrap px-3 py-2 align-top"><StatusBadge resultado={resultadosPorFilial[item.filial]} /></td>
                    <td className="px-3 py-2 align-top"><ResultadoDetalhe resultado={resultadosPorFilial[item.filial]} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}
