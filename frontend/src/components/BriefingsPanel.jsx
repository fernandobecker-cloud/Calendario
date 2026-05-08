import { useMemo, useState } from 'react'

const STATUS_FILTERS = ['Todas', 'Briefing Urgente', 'Planejada', 'Briefing Enviado', 'Programada']

const DOT_COLORS = {
  red:    'bg-rose-500',
  yellow: 'bg-amber-400',
  green:  'bg-emerald-500',
  gray:   'bg-slate-300',
}

const DAYS_TEXT = {
  red:    'text-rose-600',
  yellow: 'text-amber-600',
  green:  'text-emerald-600',
  gray:   'text-slate-400',
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

function formatDateBR(date) {
  if (!date) return '—'
  return new Intl.DateTimeFormat('pt-BR', { day: '2-digit', month: '2-digit', year: 'numeric' }).format(date)
}

function getStatus(event) {
  const raw = String(event?.extendedProps?.status || '').trim()
  return raw || 'Planejada'
}

function buildRow(event, today) {
  const campaignDate = getCampaignDate(event?.start)
  if (!campaignDate) return null

  const status = getStatus(event)
  const canal = String(event?.extendedProps?.canal || 'Nao informado')
  const isEmailPlanejada =
    canal.toLowerCase() === 'email' && status.toLowerCase() === 'planejada'

  let briefingDeadline = null
  let daysUntilDeadline = null
  let dotColor = 'gray'

  if (isEmailPlanejada) {
    const d = new Date(campaignDate.getTime())
    d.setDate(d.getDate() - 10)
    briefingDeadline = getStartOfDay(d)
    daysUntilDeadline = Math.round((briefingDeadline.getTime() - today.getTime()) / 86400000)
    if (daysUntilDeadline <= 0) dotColor = 'red'
    else if (daysUntilDeadline <= 2) dotColor = 'yellow'
    else dotColor = 'green'
  }

  return {
    id: event.id,
    campaignDate,
    status,
    canal,
    campaignName: event?.extendedProps?.titulo_original || event?.title || 'Sem nome',
    isEmailPlanejada,
    briefingDeadline,
    daysUntilDeadline,
    dotColor,
  }
}

function DaysCell({ row }) {
  if (row.daysUntilDeadline == null) return <span className="text-slate-400">—</span>
  const d = row.daysUntilDeadline
  let label
  if (d === 0) label = 'Vence hoje'
  else if (d < 0) label = `${Math.abs(d)}d vencido`
  else label = `${d}d`
  return <span className={`font-semibold ${DAYS_TEXT[row.dotColor]}`}>{label}</span>
}

export default function BriefingsPanel({ events }) {
  const [statusFilter, setStatusFilter] = useState('Todas')

  const today = useMemo(() => getStartOfDay(new Date()), [])

  const allRows = useMemo(() =>
    (events || [])
      .map((e) => buildRow(e, today))
      .filter((r) => r && r.status.toLowerCase() !== 'finalizada')
      .sort((a, b) => a.campaignDate.getTime() - b.campaignDate.getTime()),
  [events, today])

  const urgentRows = useMemo(() =>
    allRows.filter((r) => r.isEmailPlanejada && r.daysUntilDeadline <= 0),
  [allRows])

  const filteredRows = useMemo(() => {
    if (statusFilter === 'Todas') return allRows
    if (statusFilter === 'Briefing Urgente')
      return allRows.filter((r) => r.isEmailPlanejada && r.daysUntilDeadline <= 0)
    return allRows.filter(
      (r) => r.status.toLowerCase() === statusFilter.toLowerCase()
    )
  }, [allRows, statusFilter])

  return (
    <section className="space-y-4">
      {urgentRows.length > 0 && (
        <section className="rounded-xl border border-rose-300 bg-rose-50 px-4 py-3 text-sm text-rose-900">
          <p className="mb-1 font-semibold">Atenção: briefings vencidos ou que vencem hoje</p>
          <ul className="list-inside list-disc space-y-0.5">
            {urgentRows.map((r) => (
              <li key={r.id}>
                <span className="font-medium">{r.campaignName}</span>
                {' — envio: '}
                {formatDateBR(r.campaignDate)}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-soft md:p-5">
        <div className="mb-4">
          <h2 className="text-xl font-semibold text-slate-900">Briefings de Criacao</h2>
          <p className="mt-1 text-sm text-slate-600">
            Campanhas do calendário. Data limite de briefing = data de envio − 10 dias (somente E-mail Planejada).
          </p>
        </div>

        <div className="mb-4 flex flex-wrap gap-2">
          {STATUS_FILTERS.map((f) => (
            <button
              key={f}
              onClick={() => setStatusFilter(f)}
              className={`rounded-full px-3 py-1 text-xs font-semibold transition ${
                statusFilter === f
                  ? 'bg-slate-900 text-white'
                  : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
              }`}
            >
              {f}
            </button>
          ))}
        </div>

        {filteredRows.length === 0 ? (
          <p className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
            Nenhuma campanha encontrada.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-slate-600">
                  <th className="w-6 px-3 py-2" />
                  <th className="px-3 py-2 font-semibold">Data envio</th>
                  <th className="px-3 py-2 font-semibold">Nome da campanha</th>
                  <th className="px-3 py-2 font-semibold">Canal</th>
                  <th className="px-3 py-2 font-semibold">Status</th>
                  <th className="px-3 py-2 font-semibold">Data limite briefing</th>
                  <th className="px-3 py-2 font-semibold">Dias restantes</th>
                </tr>
              </thead>
              <tbody>
                {filteredRows.map((row) => (
                  <tr key={row.id} className="border-b border-slate-100 text-slate-800">
                    <td className="px-3 py-3">
                      <span className={`inline-block h-2.5 w-2.5 rounded-full ${DOT_COLORS[row.dotColor]}`} />
                    </td>
                    <td className="px-3 py-3">{formatDateBR(row.campaignDate)}</td>
                    <td className="px-3 py-3">{row.campaignName}</td>
                    <td className="px-3 py-3">{row.canal}</td>
                    <td className="px-3 py-3">{row.status}</td>
                    <td className="px-3 py-3">
                      {row.briefingDeadline ? formatDateBR(row.briefingDeadline) : '—'}
                    </td>
                    <td className="px-3 py-3">
                      <DaysCell row={row} />
                    </td>
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
