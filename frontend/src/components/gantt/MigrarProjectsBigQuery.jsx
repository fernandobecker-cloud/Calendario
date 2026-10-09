import { useEffect, useState } from 'react'

// Migracao temporaria Sheets -> BigQuery de projects/tasks (mesmo esquema do
// botao da tela de Resultados NPI). So aparece pra admin enquanto o backend
// roda com PROJECTS_STORAGE=sheets.
export default function MigrarProjectsBigQuery({ isAdmin }) {
  const [storage, setStorage] = useState(null)
  const [migrando, setMigrando] = useState(false)
  const [erro, setErro] = useState('')
  const [resultado, setResultado] = useState(null)

  useEffect(() => {
    if (!isAdmin) return
    fetch('/api/projects-storage')
      .then((res) => (res.ok ? res.json() : null))
      .then((payload) => setStorage(payload?.storage ?? null))
      .catch(() => setStorage(null))
  }, [isAdmin])

  if (!isAdmin || storage !== 'sheets') return null

  const migrar = async () => {
    if (!window.confirm('Copiar os projetos e tarefas da planilha para o BigQuery? O que já estiver nas tabelas do BigQuery será substituído.')) return
    setMigrando(true)
    setErro('')
    setResultado(null)
    try {
      const res = await fetch('/api/projects-storage/migrar-para-bigquery', { method: 'POST' })
      const payload = await res.json().catch(() => null)
      if (!res.ok) throw new Error(payload?.detail || `HTTP ${res.status}`)
      setResultado(payload)
    } catch (err) {
      setErro(err instanceof Error ? err.message : 'Erro ao migrar para o BigQuery.')
    } finally {
      setMigrando(false)
    }
  }

  return (
    <section className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-amber-800">Migração: os projetos e tarefas ainda estão no Google Sheets.</p>
        <button
          onClick={migrar}
          disabled={migrando}
          className="rounded-lg bg-amber-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-amber-700 disabled:opacity-50"
        >
          {migrando ? 'Migrando...' : 'Migrar para BigQuery'}
        </button>
      </div>
      {erro && <p className="mt-2 text-xs text-rose-600">{erro}</p>}
      {resultado && (
        <div className="mt-3 text-xs text-slate-700">
          <p className={`font-semibold ${resultado.confere ? 'text-emerald-700' : 'text-rose-700'}`}>
            {resultado.confere
              ? '✓ Conferido: planilha e BigQuery batem. Agora configure PROJECTS_STORAGE=bigquery no Render.'
              : '✗ Os dados não bateram - não troque o PROJECTS_STORAGE ainda.'}
          </p>
          <p className="mt-1">Planilha: {resultado.planilha.projects} projetos, {resultado.planilha.tasks} tarefas</p>
          <p>BigQuery: {resultado.bigquery.projects} projetos, {resultado.bigquery.tasks} tarefas</p>
          {resultado.ids_divergentes?.length > 0 && (
            <p className="text-rose-700">IDs com diferença: {resultado.ids_divergentes.join(', ')}</p>
          )}
        </div>
      )}
    </section>
  )
}
