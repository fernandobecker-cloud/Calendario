import { useEffect, useMemo, useState } from 'react'
import GanttChart from './GanttChart'

async function fetchJson(url) {
  const response = await fetch(url)
  let payload = null

  try {
    payload = await response.json()
  } catch (_error) {
    payload = null
  }

  if (!response.ok) {
    const detail = payload?.detail || `Falha na requisicao: ${url}`
    throw new Error(detail)
  }

  return payload
}

export default function GanttPage() {
  const [projects, setProjects] = useState([])
  const [tasksByProject, setTasksByProject] = useState({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true

    const load = async () => {
      setLoading(true)
      setError('')

      try {
        const projectsPayload = await fetchJson('/api/projects')
        const loadedProjects = Array.isArray(projectsPayload) ? projectsPayload : []

        const tasksList = await Promise.all(
          loadedProjects.map(async (project) => {
            const tasks = await fetchJson(`/api/projects/${project.id}/tasks`)
            return [project.id, Array.isArray(tasks) ? tasks : []]
          })
        )

        if (!active) return

        setProjects(loadedProjects)
        setTasksByProject(Object.fromEntries(tasksList))
      } catch (err) {
        if (!active) return
        setProjects([])
        setTasksByProject({})
        setError(err instanceof Error ? err.message : 'Erro inesperado ao carregar operacao.')
      } finally {
        if (active) setLoading(false)
      }
    }

    load()

    return () => {
      active = false
    }
  }, [])

  const totalTasks = useMemo(
    () => Object.values(tasksByProject).reduce((sum, tasks) => sum + tasks.length, 0),
    [tasksByProject]
  )

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-7xl flex-col gap-5 px-4 py-6 md:px-6 lg:px-8">
      <section className="rounded-2xl bg-gradient-to-r from-brand-500 to-brand-600 p-6 text-white shadow-soft md:p-8">
        <h1 className="text-2xl font-semibold tracking-tight md:text-4xl">Operacao CRM</h1>
        <p className="mt-2 text-sm text-blue-100 md:text-base">Gantt de projetos e tarefas para execucao do plano CRM.</p>
        <p className="mt-3 text-xs text-blue-100/90">
          {projects.length} projeto(s) • {totalTasks} tarefa(s)
        </p>
      </section>

      {error && <section className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-rose-700">{error}</section>}

      {loading ? (
        <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-soft">
          <p className="text-sm text-slate-600">Carregando projetos e tarefas...</p>
        </section>
      ) : (
        <GanttChart projects={projects} tasksByProject={tasksByProject} />
      )}
    </main>
  )
}
