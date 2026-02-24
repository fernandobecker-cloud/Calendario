import { useMemo } from 'react'
import GanttTaskBar from './GanttTaskBar'

const DAY_WIDTH = 42

function toDate(value) {
  if (!value) return null
  const date = new Date(`${value}T00:00:00`)
  return Number.isNaN(date.getTime()) ? null : date
}

function dayDiff(start, end) {
  const msPerDay = 24 * 60 * 60 * 1000
  return Math.floor((end.getTime() - start.getTime()) / msPerDay)
}

function formatHeaderLabel(date) {
  return new Intl.DateTimeFormat('pt-BR', {
    day: '2-digit',
    month: '2-digit'
  }).format(date)
}

function addDays(date, count) {
  const next = new Date(date)
  next.setDate(next.getDate() + count)
  return next
}

function getTimelineBounds(projects, tasksByProject) {
  const dates = []

  projects.forEach((project) => {
    const start = toDate(project.start_date)
    const end = toDate(project.end_date)
    if (start) dates.push(start)
    if (end) dates.push(end)

    const tasks = tasksByProject[project.id] || []
    tasks.forEach((task) => {
      const taskStart = toDate(task.start_date)
      const taskEnd = toDate(task.end_date)
      if (taskStart) dates.push(taskStart)
      if (taskEnd) dates.push(taskEnd)
    })
  })

  if (dates.length === 0) {
    const now = new Date()
    const start = new Date(now.getFullYear(), now.getMonth(), 1)
    return {
      start,
      end: addDays(start, 30)
    }
  }

  const minDate = new Date(Math.min(...dates.map((date) => date.getTime())))
  const maxDate = new Date(Math.max(...dates.map((date) => date.getTime())))

  return {
    start: addDays(minDate, -2),
    end: addDays(maxDate, 2)
  }
}

export default function GanttChart({ projects, tasksByProject }) {
  const { timelineStart, timelineDays, headerDates, timelineWidth } = useMemo(() => {
    const bounds = getTimelineBounds(projects, tasksByProject)
    const days = dayDiff(bounds.start, bounds.end) + 1

    const dates = Array.from({ length: days }).map((_, index) => addDays(bounds.start, index))

    return {
      timelineStart: bounds.start,
      timelineDays: days,
      headerDates: dates,
      timelineWidth: days * DAY_WIDTH
    }
  }, [projects, tasksByProject])

  if (projects.length === 0) {
    return (
      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-soft">
        <p className="text-sm text-slate-600">Nenhum projeto cadastrado.</p>
      </section>
    )
  }

  return (
    <section className="rounded-2xl border border-slate-200 bg-white shadow-soft">
      <div className="overflow-x-auto">
        <div className="min-w-full" style={{ minWidth: `${timelineWidth + 340}px` }}>
          <div className="sticky top-0 z-20 flex border-b border-slate-200 bg-slate-50">
            <div className="w-[340px] shrink-0 border-r border-slate-200 px-4 py-3 text-xs font-semibold uppercase tracking-wide text-slate-500">
              Projeto / Tarefa
            </div>
            <div className="relative flex" style={{ width: `${timelineWidth}px` }}>
              {headerDates.map((date) => (
                <div
                  key={date.toISOString()}
                  className="flex h-11 items-center justify-center border-r border-slate-200 text-[11px] font-medium text-slate-600"
                  style={{ width: `${DAY_WIDTH}px` }}
                >
                  {formatHeaderLabel(date)}
                </div>
              ))}
            </div>
          </div>

          {projects.map((project) => {
            const tasks = tasksByProject[project.id] || []

            return (
              <div key={project.id} className="border-b border-slate-100">
                <div className="flex border-b border-slate-100 bg-white">
                  <div className="w-[340px] shrink-0 border-r border-slate-200 px-4 py-3">
                    <p className="text-sm font-semibold text-slate-900">{project.name}</p>
                    <p className="mt-1 text-xs text-slate-500 line-clamp-2">{project.description || 'Sem descricao'}</p>
                  </div>
                  <div className="relative h-14" style={{ width: `${timelineWidth}px` }}>
                    {Array.from({ length: timelineDays }).map((_, index) => (
                      <div
                        key={`${project.id}-grid-${index}`}
                        className="absolute top-0 h-full border-r border-slate-100"
                        style={{ left: `${index * DAY_WIDTH}px`, width: `${DAY_WIDTH}px` }}
                      />
                    ))}
                  </div>
                </div>

                {tasks.length === 0 ? (
                  <div className="flex bg-slate-50/70">
                    <div className="w-[340px] shrink-0 border-r border-slate-200 px-4 py-2 text-xs text-slate-500">Sem tarefas</div>
                    <div className="h-11" style={{ width: `${timelineWidth}px` }} />
                  </div>
                ) : (
                  tasks.map((task) => (
                    <div key={task.id} className="flex bg-white">
                      <div className="w-[340px] shrink-0 border-r border-slate-200 px-4 py-2">
                        <p className="text-sm font-medium text-slate-700">{task.title}</p>
                        <p className="text-xs text-slate-500">{task.start_date || '—'} → {task.end_date || '—'}</p>
                      </div>
                      <div className="relative h-11" style={{ width: `${timelineWidth}px` }}>
                        {Array.from({ length: timelineDays }).map((_, index) => (
                          <div
                            key={`${task.id}-grid-${index}`}
                            className="absolute top-0 h-full border-r border-slate-100"
                            style={{ left: `${index * DAY_WIDTH}px`, width: `${DAY_WIDTH}px` }}
                          />
                        ))}
                        <GanttTaskBar task={task} timelineStart={timelineStart} />
                      </div>
                    </div>
                  ))
                )}
              </div>
            )
          })}
        </div>
      </div>
    </section>
  )
}
