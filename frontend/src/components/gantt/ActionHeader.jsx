export default function ActionHeader({ totalProjects, totalTasks, onRefresh, onNewProject }) {
  return (
    <section className="rounded-2xl bg-gradient-to-r from-brand-500 to-brand-600 p-6 text-white shadow-soft md:p-8">
      <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight md:text-4xl">Operacao CRM</h1>
          <p className="mt-2 text-sm text-blue-100 md:text-base">Gantt de projetos e tarefas para execucao do plano CRM.</p>
          <p className="mt-3 text-xs text-blue-100/90">
            {totalProjects} projeto(s) • {totalTasks} tarefa(s)
          </p>
        </div>

        <div className="flex gap-2">
          <button
            type="button"
            onClick={onRefresh}
            className="rounded-lg border border-white/40 bg-white/10 px-4 py-2 text-sm font-semibold text-white transition hover:bg-white/20"
          >
            Atualizar
          </button>
          <button
            type="button"
            onClick={onNewProject}
            className="rounded-lg bg-white px-4 py-2 text-sm font-semibold text-brand-700 transition hover:bg-slate-100"
          >
            Novo Projeto
          </button>
        </div>
      </div>
    </section>
  )
}
