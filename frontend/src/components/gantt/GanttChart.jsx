import { memo, useCallback, useEffect, useMemo, useState } from 'react'
import GanttTaskBar from './GanttTaskBar'

const DAY_WIDTH = 42
const STORAGE_KEY = 'gantt_expanded_projects'

function PencilIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M12 20h9" />
      <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z" />
    </svg>
  )
}

function ChevronIcon({ expanded }) {
  return (
    <span className="inline-block text-slate-700">{expanded ? '▾' : '▸'}</span>
  )
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

function getProjectProgress(tasks) {
  if (!tasks.length) return 0
  const done = tasks.filter((task) => task.status === 'done').length
  return Math.round((done / tasks.length) * 100)
}

function getProgressStyle(progress) {
  if (progress < 40) {
    return { fill: 'bg-rose-400', track: 'bg-rose-100' }
  }
  if (progress < 80) {
    return { fill: 'bg-amber-400', track: 'bg-amber-100' }
  }
  return { fill: 'bg-emerald-500', track: 'bg-emerald-100' }
}

function readExpandedFromStorage() {
  if (typeof window === 'undefined') return {}
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw)
    return parsed && typeof parsed === 'object' ? parsed : {}
  } catch (_error) {
    return {}
  }
}

const TaskRow = memo(function TaskRow({ task, timelineDays, timelineWidth, timelineStart, onEditTask }) {
  return (
    <div className="flex bg-white/70">
      <div className="w-[340px] shrink-0 border-r border-slate-200 px-4 py-2 pl-10">
        <div className="flex items-start justify-between gap-2">
          <div>
            <p className="text-sm font-medium text-slate-600">{task.title}</p>
            <p className="text-[11px] text-slate-400">{task.start_date || '—'} → {task.end_date || '—'}</p>
          </div>
          <button
            type="button"
            onClick={() => onEditTask(task)}
            className="rounded-md border border-slate-300 p-1.5 text-slate-600 hover:bg-slate-100"
            aria-label="Editar tarefa"
          >
            <PencilIcon />
          </button>
        </div>
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
  )
})

const ProjectBlock = memo(function ProjectBlock({
  project,
  tasks,
  expanded,
  timelineDays,
  timelineWidth,
  timelineStart,
  onToggle,
  onCreateTask,
  onEditProject,
  onEditTask
}) {
  const progress = useMemo(() => getProjectProgress(tasks), [tasks])
  const progressStyle = useMemo(() => getProgressStyle(progress), [progress])

  return (
    <div className="mt-[18px] rounded-xl border border-slate-200 bg-[#f8fafc]">
      <div className="flex border-b border-slate-200 bg-[#f8fafc] transition hover:bg-slate-100/80">
        <div className="w-[340px] shrink-0 border-r border-slate-200 px-4 py-4">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => onToggle(project.id)}
                  className="rounded p-1 text-base leading-none hover:bg-slate-200"
                  aria-label={expanded ? 'Recolher projeto' : 'Expandir projeto'}
                >
                  <ChevronIcon expanded={expanded} />
                </button>
                <p className="truncate text-base font-bold text-[#0f172a]">
                  {project.name} — {progress}%
                </p>
              </div>

              <div className={`mt-2 h-2.5 w-40 overflow-hidden rounded-full ${progressStyle.track}`}>
                <div className={`h-full ${progressStyle.fill}`} style={{ width: `${progress}%` }} />
              </div>

              <p className="mt-2 text-xs text-slate-500 line-clamp-2">{project.description || 'Sem descricao'}</p>
            </div>

            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => onCreateTask(project.id)}
                className="rounded-md border border-slate-300 px-2 py-1 text-xs font-semibold text-slate-700 hover:bg-slate-100"
              >
                + Nova tarefa
              </button>
              <button
                type="button"
                onClick={() => onEditProject(project)}
                className="rounded-md border border-slate-300 p-1.5 text-slate-600 hover:bg-slate-100"
                aria-label="Editar projeto"
              >
                <PencilIcon />
              </button>
            </div>
          </div>
        </div>

        <div className="relative h-[92px]" style={{ width: `${timelineWidth}px` }}>
          {Array.from({ length: timelineDays }).map((_, index) => (
            <div
              key={`${project.id}-grid-${index}`}
              className="absolute top-0 h-full border-r border-slate-100"
              style={{ left: `${index * DAY_WIDTH}px`, width: `${DAY_WIDTH}px` }}
            />
          ))}
        </div>
      </div>

      {expanded && (
        <>
          {tasks.length === 0 ? (
            <div className="flex border-t border-slate-200 bg-white/60">
              <div className="w-[340px] shrink-0 border-r border-slate-200 px-4 py-2 pl-10 text-xs text-slate-500">Sem tarefas</div>
              <div className="h-11" style={{ width: `${timelineWidth}px` }} />
            </div>
          ) : (
            tasks.map((task) => (
              <TaskRow
                key={task.id}
                task={task}
                timelineDays={timelineDays}
                timelineWidth={timelineWidth}
                timelineStart={timelineStart}
                onEditTask={onEditTask}
              />
            ))
          )}
        </>
      )}

      <div className="h-px bg-slate-300" />
    </div>
  )
})

export default function GanttChart({ projects, tasksByProject, onCreateTask, onEditProject, onEditTask }) {
  const [expandedProjects, setExpandedProjects] = useState(() => readExpandedFromStorage())

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

  useEffect(() => {
    if (typeof window === 'undefined') return
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(expandedProjects))
  }, [expandedProjects])

  const toggleProject = useCallback((projectId) => {
    setExpandedProjects((prev) => {
      const current = prev[String(projectId)]
      return {
        ...prev,
        [String(projectId)]: !current
      }
    })
  }, [])

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
        <div className="min-w-full pb-4" style={{ minWidth: `${timelineWidth + 340}px` }}>
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
            const expanded = expandedProjects[String(project.id)] !== false

            return (
              <ProjectBlock
                key={project.id}
                project={project}
                tasks={tasks}
                expanded={expanded}
                timelineDays={timelineDays}
                timelineWidth={timelineWidth}
                timelineStart={timelineStart}
                onToggle={toggleProject}
                onCreateTask={onCreateTask}
                onEditProject={onEditProject}
                onEditTask={onEditTask}
              />
            )
          })}
        </div>
      </div>
    </section>
  )
}
