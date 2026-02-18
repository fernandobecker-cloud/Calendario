import { useMemo } from 'react'

const URGENCY_STYLES = {
  normal: 'bg-slate-100 text-slate-700',
  alerta: 'bg-amber-100 text-amber-800',
  critico: 'bg-rose-100 text-rose-800'
}

function getStartOfDay(date) {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate())
}

function getCampaignDate(value) {
  if (!value) return null
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return null
  return getStartOfDay(date)
}

function getDaysRemaining(startDate, today) {
  const diff = startDate.getTime() - today.getTime()
  return Math.round(diff / 86400000)
}

function getUrgency(daysRemaining) {
  if (daysRemaining <= 3) return { key: 'critico', label: 'Critico' }
  if (daysRemaining <= 7) return { key: 'alerta', label: 'Alerta' }
  return { key: 'normal', label: 'Normal' }
}

function getStatus(event) {
  const raw = String(event?.extendedProps?.status || '').trim()
  if (!raw) return 'Planejada'
  return raw
}

export default function BriefingsPanel({ events }) {
  const briefingRows = useMemo(() => {
    const today = getStartOfDay(new Date())

    return (events || [])
      .map((event) => {
        const campaignDate = getCampaignDate(event?.start)
        if (!campaignDate) return null

        const daysRemaining = getDaysRemaining(campaignDate, today)
        const status = getStatus(event)
        const isPlanned = status.toLowerCase() === 'planejada'

        if (!isPlanned || daysRemaining < 0) return null

        const urgency = getUrgency(daysRemaining)

        return {
          id: event.id,
          campaignDate,
          daysRemaining,
          urgency,
          status,
          canal: event?.extendedProps?.canal || 'Nao informado',
          campaignName: event?.extendedProps?.titulo_original || event?.title || 'Sem nome'
        }
      })
      .filter(Boolean)
      .sort((a, b) => a.campaignDate.getTime() - b.campaignDate.getTime())
  }, [events])

  const hasUrgentBriefing = briefingRows.some((row) => row.daysRemaining < 7)

  return (
    <section className="space-y-4">
      {hasUrgentBriefing && (
        <section className="rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-sm font-semibold text-amber-900">
          ATENCAO: Existem campanhas proximas sem briefing enviado.
        </section>
      )}

      <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-soft md:p-5">
        <div className="mb-4">
          <h2 className="text-xl font-semibold text-slate-900">Briefings de Criacao</h2>
          <p className="mt-1 text-sm text-slate-600">Campanhas planejadas com data igual ou superior a hoje.</p>
        </div>

        {briefingRows.length === 0 ? (
          <p className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
            Nenhuma campanha planejada futura encontrada.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-slate-600">
                  <th className="px-3 py-2 font-semibold">Data</th>
                  <th className="px-3 py-2 font-semibold">Nome da campanha</th>
                  <th className="px-3 py-2 font-semibold">Canal</th>
                  <th className="px-3 py-2 font-semibold">Dias restantes</th>
                  <th className="px-3 py-2 font-semibold">Nivel de urgencia</th>
                  <th className="px-3 py-2 font-semibold">Status</th>
                </tr>
              </thead>
              <tbody>
                {briefingRows.map((row) => (
                  <tr key={row.id} className="border-b border-slate-100 text-slate-800">
                    <td className="px-3 py-3">
                      {new Intl.DateTimeFormat('pt-BR', {
                        day: '2-digit',
                        month: '2-digit',
                        year: 'numeric'
                      }).format(row.campaignDate)}
                    </td>
                    <td className="px-3 py-3">{row.campaignName}</td>
                    <td className="px-3 py-3">{row.canal}</td>
                    <td className="px-3 py-3">{row.daysRemaining}</td>
                    <td className="px-3 py-3">
                      <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${URGENCY_STYLES[row.urgency.key]}`}>
                        {row.urgency.label}
                      </span>
                    </td>
                    <td className="px-3 py-3">{row.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </section>
  )
}
