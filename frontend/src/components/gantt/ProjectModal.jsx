import { useEffect, useState } from 'react'

const PROJECT_STATUS_OPTIONS = [
  { value: 'planned', label: 'Planejado' },
  { value: 'active', label: 'Em andamento' },
  { value: 'done', label: 'Concluido' },
  { value: 'cancelled', label: 'Cancelado' }
]

const EMPTY_FORM = {
  name: '',
  owner: '',
  description: '',
  start_date: '',
  end_date: '',
  status: 'planned'
}

export default function ProjectModal({
  isOpen,
  onClose,
  onSubmit,
  initialValues,
  loading,
  error,
  title = 'Novo Projeto',
  submitLabel = 'Cadastrar projeto'
}) {
  const [form, setForm] = useState(EMPTY_FORM)

  useEffect(() => {
    if (!isOpen) return
    setForm({
      name: initialValues?.name || '',
      owner: initialValues?.owner || '',
      description: initialValues?.description || '',
      start_date: initialValues?.start_date || '',
      end_date: initialValues?.end_date || '',
      status: initialValues?.status || 'planned'
    })
  }, [initialValues, isOpen])

  if (!isOpen) return null

  const handleSubmit = (event) => {
    event.preventDefault()
    onSubmit({
      name: form.name.trim(),
      owner: form.owner.trim() || null,
      description: form.description.trim() || null,
      start_date: form.start_date || null,
      end_date: form.end_date || null,
      status: form.status
    })
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 p-4" onClick={onClose}>
      <div className="w-full max-w-2xl rounded-2xl border border-slate-200 bg-white p-5 shadow-2xl md:p-6" onClick={(event) => event.stopPropagation()}>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-xl font-semibold text-slate-900">{title}</h2>
          <button type="button" onClick={onClose} className="rounded-md px-2 py-1 text-slate-500 hover:bg-slate-100">
            X
          </button>
        </div>

        <form className="grid gap-3 md:grid-cols-3" onSubmit={handleSubmit}>
          <label className="text-sm text-slate-700">
            Nome
            <input
              required
              value={form.name}
              onChange={(event) => setForm((prev) => ({ ...prev, name: event.target.value }))}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
            />
          </label>
          <label className="text-sm text-slate-700">
            Responsavel
            <input
              value={form.owner}
              onChange={(event) => setForm((prev) => ({ ...prev, owner: event.target.value }))}
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
          <div className="flex items-end">
            <button
              type="submit"
              disabled={loading}
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
