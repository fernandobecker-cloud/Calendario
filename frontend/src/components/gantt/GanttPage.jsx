import { useCallback, useEffect, useMemo, useState } from 'react'
import ActionHeader from './ActionHeader'
import EditProjectModal from './EditProjectModal'
import EditTaskModal from './EditTaskModal'
import GanttChart from './GanttChart'
import ProjectModal from './ProjectModal'
import TaskModal from './TaskModal'

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

  const [toasts, setToasts] = useState([])

  const [isProjectModalOpen, setIsProjectModalOpen] = useState(false)
  const [isTaskModalOpen, setIsTaskModalOpen] = useState(false)

  const [editingProject, setEditingProject] = useState(null)
  const [editingTask, setEditingTask] = useState(null)

  const [projectModalError, setProjectModalError] = useState('')
  const [taskModalError, setTaskModalError] = useState('')
  const [projectSaving, setProjectSaving] = useState(false)
  const [taskSaving, setTaskSaving] = useState(false)

  const showToast = useCallback((message) => {
    const id = Date.now() + Math.random()
    setToasts((prev) => [...prev, { id, message }])
    setTimeout(() => {
      setToasts((prev) => prev.filter((toast) => toast.id !== id))
    }, 3000)
  }, [])

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
    loadData()
  }, [loadData])

  const totalTasks = useMemo(
    () => Object.values(tasksByProject).reduce((sum, tasks) => sum + tasks.length, 0),
    [tasksByProject]
  )

  const openCreateProject = useCallback(() => {
    setEditingProject(null)
    setProjectModalError('')
    setIsProjectModalOpen(true)
  }, [])

  const openEditProject = useCallback((project) => {
    setEditingProject(project)
    setProjectModalError('')
    setIsProjectModalOpen(true)
  }, [])

  const closeProjectModal = useCallback(() => {
    setIsProjectModalOpen(false)
    setEditingProject(null)
    setProjectModalError('')
  }, [])

  const openCreateTask = useCallback((projectId) => {
    setEditingTask({ project_id: projectId })
    setTaskModalError('')
    setIsTaskModalOpen(true)
  }, [])

  const openEditTask = useCallback((task) => {
    setEditingTask(task)
    setTaskModalError('')
    setIsTaskModalOpen(true)
  }, [])

  const closeTaskModal = useCallback(() => {
    setIsTaskModalOpen(false)
    setEditingTask(null)
    setTaskModalError('')
  }, [])

  const handleProjectSubmit = useCallback(
    async (payload) => {
      setProjectModalError('')
      if (!payload.name) {
        setProjectModalError('Nome do projeto e obrigatorio.')
        return
      }

      setProjectSaving(true)
      try {
        if (editingProject?.id) {
          await fetchJson(`/api/projects/${editingProject.id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
          })
          showToast('Projeto atualizado')
        } else {
          await fetchJson('/api/projects', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
          })
          showToast('Projeto criado')
        }

        closeProjectModal()
        await loadData()
      } catch (err) {
        setProjectModalError(err instanceof Error ? err.message : 'Erro ao salvar projeto.')
      } finally {
        setProjectSaving(false)
      }
    },
    [editingProject, showToast, closeProjectModal, loadData]
  )

  const handleTaskSubmit = useCallback(
    async (payload) => {
      setTaskModalError('')
      if (!payload.title) {
        setTaskModalError('Titulo da tarefa e obrigatorio.')
        return
      }

      setTaskSaving(true)
      try {
        if (editingTask?.id) {
          await fetchJson(`/api/tasks/${editingTask.id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              title: payload.title,
              description: payload.description,
              start_date: payload.start_date,
              end_date: payload.end_date,
              status: payload.status,
              priority: payload.priority,
              progress: payload.progress
            })
          })
          showToast('Tarefa atualizada')
        } else {
          if (!payload.project_id) {
            setTaskModalError('Selecione um projeto.')
            return
          }

          await fetchJson(`/api/projects/${payload.project_id}/tasks`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              title: payload.title,
              description: payload.description,
              start_date: payload.start_date,
              end_date: payload.end_date,
              status: payload.status,
              priority: payload.priority,
              progress: payload.progress
            })
          })
          showToast('Tarefa criada')
        }

        closeTaskModal()
        await loadData()
      } catch (err) {
        setTaskModalError(err instanceof Error ? err.message : 'Erro ao salvar tarefa.')
      } finally {
        setTaskSaving(false)
      }
    },
    [editingTask, showToast, closeTaskModal, loadData]
  )

  const editingTaskInitialValues = useMemo(() => {
    if (!editingTask) return null
    return {
      project_id: editingTask.project_id,
      title: editingTask.title || '',
      description: editingTask.description || '',
      start_date: editingTask.start_date || '',
      end_date: editingTask.end_date || '',
      status: editingTask.status || 'planned',
      priority: editingTask.priority || 'medium',
      progress: editingTask.progress ?? 0
    }
  }, [editingTask])

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-7xl flex-col gap-5 px-4 py-6 md:px-6 lg:px-8">
      <ActionHeader totalProjects={projects.length} totalTasks={totalTasks} onRefresh={loadData} onNewProject={openCreateProject} />

      {error && <section className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-rose-700">{error}</section>}

      {loading ? (
        <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-soft">
          <p className="text-sm text-slate-600">Carregando projetos e tarefas...</p>
        </section>
      ) : (
        <GanttChart
          projects={projects}
          tasksByProject={tasksByProject}
          onCreateTask={openCreateTask}
          onEditProject={openEditProject}
          onEditTask={openEditTask}
        />
      )}

      {!editingProject ? (
        <ProjectModal
          isOpen={isProjectModalOpen}
          onClose={closeProjectModal}
          onSubmit={handleProjectSubmit}
          initialValues={null}
          loading={projectSaving}
          error={projectModalError}
          title="Novo Projeto"
          submitLabel="Cadastrar projeto"
        />
      ) : (
        <EditProjectModal
          isOpen={isProjectModalOpen}
          onClose={closeProjectModal}
          onSubmit={handleProjectSubmit}
          initialValues={editingProject}
          loading={projectSaving}
          error={projectModalError}
        />
      )}

      {editingTask?.id ? (
        <EditTaskModal
          isOpen={isTaskModalOpen}
          onClose={closeTaskModal}
          onSubmit={handleTaskSubmit}
          projects={projects}
          initialValues={editingTaskInitialValues}
          lockProject
          loading={taskSaving}
          error={taskModalError}
        />
      ) : (
        <TaskModal
          isOpen={isTaskModalOpen}
          onClose={closeTaskModal}
          onSubmit={handleTaskSubmit}
          projects={projects}
          initialValues={editingTaskInitialValues}
          loading={taskSaving}
          error={taskModalError}
          title="Nova Tarefa"
          submitLabel="Cadastrar tarefa"
        />
      )}

      <div className="fixed bottom-4 right-4 z-[60] flex w-72 flex-col gap-2">
        {toasts.map((toast) => (
          <div key={toast.id} className="rounded-lg bg-slate-900 px-4 py-3 text-sm font-medium text-white shadow-xl">
            {toast.message}
          </div>
        ))}
      </div>
    </main>
  )
}
