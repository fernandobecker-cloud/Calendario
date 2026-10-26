import { useSearchParams } from 'react-router-dom'
import SacDemaisDisparos from './SacDemaisDisparos'
import SacGarantiaEstendida from './SacGarantiaEstendida'

// Tela de entrada do SAC: o atendente escolhe o tipo de reclamacao antes de
// buscar o CPF. A escolha fica na URL (?tipo=...) pra sobreviver a um F5.
const OPCOES = [
  {
    tipo: 'garantia',
    titulo: 'Garantia estendida',
    texto: 'Cliente não recebeu a garantia estendida: roteiro de atendimento, dados do contrato e certificado em PDF.',
  },
  {
    tipo: 'disparos',
    titulo: 'Demais disparos',
    texto: 'Cliente não recebeu o cupom de primeira compra ou outra mensagem: cupom e últimos 10 disparos de e-mail, SMS e WhatsApp.',
  },
]

export default function SacUltimosDisparosPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const tipo = searchParams.get('tipo')
  const voltar = () => setSearchParams({})

  if (tipo === 'garantia') return <SacGarantiaEstendida onVoltar={voltar} />
  if (tipo === 'disparos') return <SacDemaisDisparos onVoltar={voltar} />

  return (
    <div className="mx-auto max-w-4xl px-4 py-8 md:px-6 lg:px-8">
      <section className="mb-6 rounded-2xl bg-gradient-to-r from-indigo-600 to-violet-500 p-6 text-white shadow-soft md:p-8">
        <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">Últimos disparos (SAC)</h1>
        <p className="mt-2 text-sm text-indigo-100 md:text-base">Sobre o que é o atendimento?</p>
      </section>

      <div className="grid gap-4 md:grid-cols-2">
        {OPCOES.map((opcao) => (
          <button
            key={opcao.tipo}
            type="button"
            onClick={() => setSearchParams({ tipo: opcao.tipo })}
            className="flex flex-col gap-2 rounded-2xl border border-slate-200 bg-white p-6 text-left shadow-soft transition hover:border-indigo-300 hover:bg-indigo-50"
          >
            <span className="text-lg font-semibold text-slate-900">{opcao.titulo}</span>
            <span className="text-sm text-slate-600">{opcao.texto}</span>
          </button>
        ))}
      </div>
    </div>
  )
}
