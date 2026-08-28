export default function DataDelayBanner({ dataDelay }) {
  if (!dataDelay?.ultimo_evento) return null
  const ultimoEvento = dataDelay.ultimo_evento
  // Só mostra quando os dados estão realmente 2+ dias atrás de hoje
  const hoje = new Date()
  hoje.setHours(0, 0, 0, 0)
  const ultimoEventoDate = new Date(ultimoEvento + 'T00:00:00')
  const diffDias = Math.round((hoje - ultimoEventoDate) / 86400000)
  if (diffDias < 2) return null
  const [y, m, d] = ultimoEvento.split('-')
  const label = `${d}/${m}/${y}`
  return (
    <div className="flex items-start gap-2.5 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
      <svg className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" viewBox="0 0 20 20" fill="currentColor">
        <path fillRule="evenodd" d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.17 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 5a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 0110 5zm0 9a1 1 0 100-2 1 1 0 000 2z" clipRule="evenodd" />
      </svg>
      <span>
        <strong>Dados disponíveis até {label}</strong> — o Emarsys Open Data tem ~2 dias de delay para exportar para o BigQuery. Dados mais recentes aparecerão em breve.
      </span>
    </div>
  )
}
