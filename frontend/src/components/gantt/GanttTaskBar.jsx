const STATUS_STYLES = {
  planned: {
    bar: 'bg-slate-400',
    fill: 'bg-slate-600'
  },
  doing: {
    bar: 'bg-blue-400',
    fill: 'bg-blue-700'
  },
  blocked: {
    bar: 'bg-rose-400',
    fill: 'bg-rose-700'
  },
  done: {
    bar: 'bg-emerald-400',
    fill: 'bg-emerald-700'
  }
}

const STATUS_LABELS = {
  planned: 'Planejada',
  doing: 'Fazendo',
  blocked: 'Bloqueada',
  done: 'Concluida'
}

const DAY_WIDTH = 42

function clampProgress(value) {
  const numeric = Number(value)
  if (Number.isNaN(numeric)) return 0
  return Math.max(0, Math.min(100, numeric))
}

function toDate(value) {
  if (!value) return null
  const date = new Date(`${value}T00:00:00`)
  return Number.isNaN(date.getTime()) ? null : date
}

function dayDiff(start, end) {
  const msPerDay = 24 * 60 * 60 * 1000
  return Math.floor((end.getTime() - start.getTime()) / msPerDay)
}

export default function GanttTaskBar({ task, timelineStart }) {
  const startDate = toDate(task.start_date)
  const endDate = toDate(task.end_date)

  if (!startDate || !endDate || endDate < startDate) return null

  const left = dayDiff(timelineStart, startDate) * DAY_WIDTH
  const days = dayDiff(startDate, endDate) + 1
  const width = Math.max(DAY_WIDTH, days * DAY_WIDTH)
  const progress = clampProgress(task.progress)
  const styles = STATUS_STYLES[task.status] || STATUS_STYLES.planned
  const statusLabel = STATUS_LABELS[task.status] || STATUS_LABELS.planned

  return (
    <div
      className={`group absolute top-1/2 h-8 -translate-y-1/2 overflow-hidden rounded-lg ${styles.bar} shadow-sm`}
      style={{ left: `${left}px`, width: `${width}px` }}
      role="img"
      aria-label={`${task.title} de ${task.start_date} ate ${task.end_date}`}
    >
      <div className={`h-full ${styles.fill} transition-all`} style={{ width: `${progress}%` }} />

      <div className="pointer-events-none absolute inset-0 flex items-center justify-between px-2 text-xs font-semibold text-white">
        <span className="truncate">{task.title}</span>
        <span className="ml-2 shrink-0">{progress}%</span>
      </div>

      <div className="pointer-events-none absolute left-1/2 top-[-58px] z-30 hidden -translate-x-1/2 rounded-md bg-slate-900 px-2 py-1 text-[11px] text-white shadow-lg group-hover:block">
        {task.title} • {task.start_date} → {task.end_date} • {statusLabel} • {progress}%
      </div>
    </div>
  )
}
