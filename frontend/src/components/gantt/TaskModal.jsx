import { useEffect, useState } from 'react'

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

const EMPTY_FORM = {
  project_id: '',
  title: '',
  description: '',
  start_date: '',
  end_date: '',
  status: 'planned',
  priority: 'medium',
  progress: 0
}

export default function TaskModal({
  isOpen,
  onClose,
  onSubmit,
  projects,
  tasksByProject,
  initialValues,
  currentTaskId,
  lockProject = false,
  loading,
  error,
  title = 'Nova Tarefa',
  submitLabel = 'Cadastrar tarefa'
}) {
  const [form, setForm] = useState(EMPTY_FORM)

  useEffect(() => {
    if (!isOpen) return
    const firstProjectId = projects[0] ? String(projects[0].id) : ''
    setForm({
      project_id: initialValues?.project_id ? String(initialValues.project_id) : firstProjectId,
      title: initialValues?.title || '',
      description: initialValues?.description || '',
      start_date: initialValues?.start_date || '',
      end_date: initialValues?.end_date || '',
      status: initialValues?.status || 'planned',
      priority: initialValues?.priority || 'medium',
      progress: Number(initialValues?.progress || 0),
      depends_on_task_id: initialValues?.depends_on_task_id ? String(initialValues.depends_on_task_id) : ''
    })
  }, [initialValues, isOpen, projects])

  if (!isOpen) return null

  const selectableDependencies = (tasksByProject?.[Number(form.project_id)] || []).filter(
    (task) => task.id !== currentTaskId
  )

  const handleSubmit = (event) => {
    event.preventDefault()
    onSubmit({
      project_id: Number(form.project_id),
      title: form.title.trim(),
      description: form.description.trim() || null,
      start_date: form.start_date || null,
      end_date: form.end_date || null,
      status: form.status,
      priority: form.priority,
      progress: Number(form.progress) || 0,
      depends_on_task_id: form.depends_on_task_id ? Number(form.depends_on_task_id) : null
    })
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 p-4" onClick={onClose}>
      <div className="w-full max-w-3xl rounded-2xl border border-slate-200 bg-white p-5 shadow-2xl md:p-6" onClick={(event) => event.stopPropagation()}>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-xl font-semibold text-slate-900">{title}</h2>
          <button type="button" onClick={onClose} className="rounded-md px-2 py-1 text-slate-500 hover:bg-slate-100">
            X
          </button>
        </div>

        <form className="grid gap-3 md:grid-cols-4" onSubmit={handleSubmit}>
          <label className="text-sm text-slate-700">
            Projeto
            <select
              value={form.project_id}
              disabled={lockProject || projects.length === 0}
              onChange={(event) => setForm((prev) => ({ ...prev, project_id: event.target.value }))}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
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
              value={form.title}
              onChange={(event) => setForm((prev) => ({ ...prev, title: event.target.value }))}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
            />
          </label>

          <label className="text-sm text-slate-700">
            Progresso (%)
            <input
              type="number"
              min="0"
              max="100"
              value={form.progress}
              onChange={(event) => setForm((prev) => ({ ...prev, progress: event.target.value }))}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
            />
          </label>

          <label className="text-sm text-slate-700 md:col-span-4">
            Descricao
            <input
              value={form.description}
              onChange={(event) => setForm((prev) => ({ ...prev, description: event.target.value }))}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
            />
          </label>

          <label className="text-sm text-slate-700">
            Inicio
            <input
              type="date"
              value={form.start_date}
              onChange={(event) => setForm((prev) => ({ ...prev, start_date: event.target.value }))}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
            />
          </label>

          <label className="text-sm text-slate-700">
            Fim
            <input
              type="date"
              value={form.end_date}
              onChange={(event) => setForm((prev) => ({ ...prev, end_date: event.target.value }))}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
            />
          </label>

          <label className="text-sm text-slate-700">
            Status
            <select
              value={form.status}
              onChange={(event) => setForm((prev) => ({ ...prev, status: event.target.value }))}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
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
              value={form.priority}
              onChange={(event) => setForm((prev) => ({ ...prev, priority: event.target.value }))}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
            >
              {TASK_PRIORITY_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>

          <label className="text-sm text-slate-700">
            Depende de
            <select
              value={form.depends_on_task_id}
              onChange={(event) => setForm((prev) => ({ ...prev, depends_on_task_id: event.target.value }))}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
              disabled={projects.length === 0}
            >
              <option value="">Nenhuma</option>
              {selectableDependencies.map((task) => (
                <option key={task.id} value={task.id}>
                  #{task.id} - {task.title}
                </option>
              ))}
            </select>
          </label>

          <div className="flex items-end">
            <button
              type="submit"
              disabled={loading || projects.length === 0}
              className="w-full rounded-lg bg-brand-500 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-600 disabled:cursor-not-allowed disabled:bg-slate-400"
            >
              {loading ? 'Salvando...' : submitLabel}
            </button>
          </div>
        </form>

        {error && <p className="mt-3 text-sm text-rose-700">{error}</p>}
      </div>
    </div>
  )
}
