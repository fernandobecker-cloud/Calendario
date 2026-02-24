import { useCallback, useEffect, useMemo, useState } from 'react'
import GanttChart from './GanttChart'

const PROJECT_STATUS_OPTIONS = [
  { value: 'planned', label: 'Planejado' },
  { value: 'active', label: 'Em andamento' },
  { value: 'done', label: 'Concluido' },
  { value: 'cancelled', label: 'Cancelado' }
]

const TASK_STATUS_OPTIONS = [
  { value: 'planned', label: 'Planejada' },
  { value: 'doing', label: 'Fazendo' },
  { value: 'blocked', label: 'Bloqueada' },
  { value: 'done', label: 'Concluida' }
]

const TASK_PRIORITY_OPTIONS = [
  { value: 'low', label: 'Baixa' },
  { value: 'medium', label: 'Media' },
  { value: 'high', label: 'Alta' }
]

async function fetchJson(url, options = undefined) {
  const response = await fetch(url, options)
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
  const [createError, setCreateError] = useState('')
  const [createLoading, setCreateLoading] = useState(false)
  const [createTaskError, setCreateTaskError] = useState('')
  const [createTaskLoading, setCreateTaskLoading] = useState(false)
  const [createForm, setCreateForm] = useState({
    name: '',
    owner: '',
    description: '',
    start_date: '',
    end_date: '',
    status: 'planned'
  })
  const [taskForm, setTaskForm] = useState({
    project_id: '',
    title: '',
    description: '',
    start_date: '',
    end_date: '',
    status: 'planned',
    priority: 'medium',
    progress: 0
  })

  const loadData = useCallback(async () => {
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

      setProjects(loadedProjects)
      setTasksByProject(Object.fromEntries(tasksList))
    } catch (err) {
      setProjects([])
      setTasksByProject({})
      setError(err instanceof Error ? err.message : 'Erro inesperado ao carregar operacao.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    let active = true

    const guardedLoad = async () => {
      await loadData()
      if (!active) return
    }

    guardedLoad()

    return () => {
      active = false
    }
  }, [loadData])

  useEffect(() => {
    if (!projects.length) return
    setTaskForm((prev) => {
      if (prev.project_id) return prev
      return { ...prev, project_id: String(projects[0].id) }
    })
  }, [projects])

  const handleCreateProject = useCallback(
    async (event) => {
      event.preventDefault()
      setCreateError('')

      if (!createForm.name.trim()) {
        setCreateError('Nome do projeto e obrigatorio.')
        return
      }

      setCreateLoading(true)
      try {
        await fetchJson('/api/projects', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            name: createForm.name.trim(),
            owner: createForm.owner.trim() || null,
            description: createForm.description.trim() || null,
            start_date: createForm.start_date || null,
            end_date: createForm.end_date || null,
            status: createForm.status
          })
        })

        setCreateForm({
          name: '',
          owner: '',
          description: '',
          start_date: '',
          end_date: '',
          status: 'planned'
        })

        await loadData()
      } catch (err) {
        setCreateError(err instanceof Error ? err.message : 'Erro ao criar projeto.')
      } finally {
        setCreateLoading(false)
      }
    },
    [createForm, loadData]
  )

  const handleCreateTask = useCallback(
    async (event) => {
      event.preventDefault()
      setCreateTaskError('')

      const projectId = Number(taskForm.project_id)
      if (!projectId) {
        setCreateTaskError('Selecione um projeto.')
        return
      }
      if (!taskForm.title.trim()) {
        setCreateTaskError('Titulo da tarefa e obrigatorio.')
        return
      }

      setCreateTaskLoading(true)
      try {
        await fetchJson(`/api/projects/${projectId}/tasks`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            title: taskForm.title.trim(),
            description: taskForm.description.trim() || null,
            start_date: taskForm.start_date || null,
            end_date: taskForm.end_date || null,
            status: taskForm.status,
            priority: taskForm.priority,
            progress: Number(taskForm.progress) || 0
          })
        })

        setTaskForm((prev) => ({
          ...prev,
          title: '',
          description: '',
          start_date: '',
          end_date: '',
          status: 'planned',
          priority: 'medium',
          progress: 0
        }))

        await loadData()
      } catch (err) {
        setCreateTaskError(err instanceof Error ? err.message : 'Erro ao criar tarefa.')
      } finally {
        setCreateTaskLoading(false)
      }
    },
    [taskForm, loadData]
  )

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

      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft md:p-6">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-slate-900">Novo Projeto</h2>
          <button
            type="button"
            onClick={loadData}
            className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-100"
          >
            Atualizar
          </button>
        </div>
        <form className="grid gap-3 md:grid-cols-3" onSubmit={handleCreateProject}>
          <label className="text-sm text-slate-700">
            Nome
            <input
              required
              value={createForm.name}
              onChange={(event) => setCreateForm((prev) => ({ ...prev, name: event.target.value }))}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
            />
          </label>
          <label className="text-sm text-slate-700">
            Responsavel
            <input
              value={createForm.owner}
              onChange={(event) => setCreateForm((prev) => ({ ...prev, owner: event.target.value }))}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
            />
          </label>
          <label className="text-sm text-slate-700">
            Status
            <select
              value={createForm.status}
              onChange={(event) => setCreateForm((prev) => ({ ...prev, status: event.target.value }))}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
            >
              {PROJECT_STATUS_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm text-slate-700 md:col-span-3">
            Descricao
            <input
              value={createForm.description}
              onChange={(event) => setCreateForm((prev) => ({ ...prev, description: event.target.value }))}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
            />
          </label>
          <label className="text-sm text-slate-700">
            Inicio
            <input
              type="date"
              value={createForm.start_date}
              onChange={(event) => setCreateForm((prev) => ({ ...prev, start_date: event.target.value }))}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
            />
          </label>
          <label className="text-sm text-slate-700">
            Fim
            <input
              type="date"
              value={createForm.end_date}
              onChange={(event) => setCreateForm((prev) => ({ ...prev, end_date: event.target.value }))}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
            />
          </label>
          <div className="flex items-end">
            <button
              type="submit"
              disabled={createLoading}
              className="w-full rounded-lg bg-brand-500 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-600 disabled:cursor-not-allowed disabled:bg-slate-400"
            >
              {createLoading ? 'Salvando...' : 'Cadastrar projeto'}
            </button>
          </div>
        </form>
        {createError && <p className="mt-3 text-sm text-rose-700">{createError}</p>}
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft md:p-6">
        <h2 className="mb-4 text-lg font-semibold text-slate-900">Nova Tarefa</h2>
        <form className="grid gap-3 md:grid-cols-4" onSubmit={handleCreateTask}>
          <label className="text-sm text-slate-700">
            Projeto
            <select
              value={taskForm.project_id}
              onChange={(event) => setTaskForm((prev) => ({ ...prev, project_id: event.target.value }))}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
              disabled={projects.length === 0}
            >
              {projects.length === 0 ? (
                <option value="">Sem projetos</option>
              ) : (
                projects.map((project) => (
                  <option key={project.id} value={project.id}>
                    {project.name}
                  </option>
                ))
              )}
            </select>
          </label>
          <label className="text-sm text-slate-700 md:col-span-2">
            Titulo
            <input
              required
              value={taskForm.title}
              onChange={(event) => setTaskForm((prev) => ({ ...prev, title: event.target.value }))}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
              disabled={projects.length === 0}
            />
          </label>
          <label className="text-sm text-slate-700">
            Progresso (%)
            <input
              type="number"
              min="0"
              max="100"
              value={taskForm.progress}
              onChange={(event) => setTaskForm((prev) => ({ ...prev, progress: event.target.value }))}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
              disabled={projects.length === 0}
            />
          </label>
          <label className="text-sm text-slate-700 md:col-span-4">
            Descricao
            <input
              value={taskForm.description}
              onChange={(event) => setTaskForm((prev) => ({ ...prev, description: event.target.value }))}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
              disabled={projects.length === 0}
            />
          </label>
          <label className="text-sm text-slate-700">
            Inicio
            <input
              type="date"
              value={taskForm.start_date}
              onChange={(event) => setTaskForm((prev) => ({ ...prev, start_date: event.target.value }))}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
              disabled={projects.length === 0}
            />
          </label>
          <label className="text-sm text-slate-700">
            Fim
            <input
              type="date"
              value={taskForm.end_date}
              onChange={(event) => setTaskForm((prev) => ({ ...prev, end_date: event.target.value }))}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
              disabled={projects.length === 0}
            />
          </label>
          <label className="text-sm text-slate-700">
            Status
            <select
              value={taskForm.status}
              onChange={(event) => setTaskForm((prev) => ({ ...prev, status: event.target.value }))}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
              disabled={projects.length === 0}
            >
              {TASK_STATUS_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm text-slate-700">
            Prioridade
            <select
              value={taskForm.priority}
              onChange={(event) => setTaskForm((prev) => ({ ...prev, priority: event.target.value }))}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
              disabled={projects.length === 0}
            >
              {TASK_PRIORITY_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <div className="flex items-end">
            <button
              type="submit"
              disabled={createTaskLoading || projects.length === 0}
              className="w-full rounded-lg bg-brand-500 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-600 disabled:cursor-not-allowed disabled:bg-slate-400"
            >
              {createTaskLoading ? 'Salvando...' : 'Cadastrar tarefa'}
            </button>
          </div>
        </form>
        {createTaskError && <p className="mt-3 text-sm text-rose-700">{createTaskError}</p>}
      </section>

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
