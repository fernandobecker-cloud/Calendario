import { useMemo, useState } from 'react'

const ELEMENTS = [
  // ── LOGIN ─────────────────────────────────────────────────────────────────
  { code: 'LOGIN.LOGO',   type: 'Imagem',   name: 'Logo iPlace',               location: 'Login',                description: 'Logo exibida acima do formulário de login e na tela de inatividade' },
  { code: 'LOGIN.USER',   type: 'Campo',    name: 'Usuário',                   location: 'Login',                description: 'Campo de texto para inserir o nome de usuário' },
  { code: 'LOGIN.PASS',   type: 'Campo',    name: 'Senha',                     location: 'Login',                description: 'Campo de senha para autenticação' },
  { code: 'LOGIN.BTN',    type: 'Botão',    name: 'Entrar',                    location: 'Login',                description: 'Botão que envia as credenciais e autentica o usuário' },
  { code: 'LOGIN.ERR',    type: 'Alerta',   name: 'Erro de login',             location: 'Login',                description: 'Mensagem em vermelho exibida quando usuário/senha estão incorretos' },
  { code: 'LOGIN.INACT',  type: 'Alerta',   name: 'Sessão expirada',           location: 'Login',                description: 'Mensagem âmbar exibida após 14min 30s de inatividade — instrui o usuário a recarregar a página' },

  // ── NAV – Barra de navegação superior ─────────────────────────────────────
  { code: 'NAV.TAB.RG',   type: 'Aba',      name: 'Resultado Geral',           location: 'Nav → Topo',           description: 'Aba de navegação para /resultado-geral; visível a todos os usuários com permissão' },
  { code: 'NAV.TAB.CAL',  type: 'Aba',      name: 'Campanhas',                 location: 'Nav → Topo',           description: 'Aba de navegação para /campanhas; visível a todos com permissão' },
  { code: 'NAV.TAB.GNT',  type: 'Aba',      name: 'Projetos',                  location: 'Nav → Topo',           description: 'Aba de navegação para /gantt' },
  { code: 'NAV.TAB.AUD',  type: 'Aba',      name: 'Auditoria',                 location: 'Nav → Topo',           description: 'Aba de navegação para /auditoria' },
  { code: 'NAV.TAB.ADM',  type: 'Aba',      name: 'Adm',                       location: 'Nav → Topo',           description: 'Aba de navegação para /adm — visível somente ao usuário admin' },
  { code: 'NAV.TAB.MAP',  type: 'Aba',      name: 'Mapa do Portal',            location: 'Nav → Topo',           description: 'Esta aba — visível somente ao usuário admin, rota /mapa-portal' },
  { code: 'NAV.USER',     type: 'Info',     name: 'Nome do usuário logado',    location: 'Nav → Topo (direita)', description: 'Texto com o username atual, visível em telas médias/grandes' },
  { code: 'NAV.LOGOUT',   type: 'Botão',    name: 'Sair',                      location: 'Nav → Topo (direita)', description: 'Botão que encerra a sessão e retorna ao login' },

  // ── CAL – Campanhas → Calendário CRM ──────────────────────────────────────
  { code: 'CAL.NAV',           type: 'Nav',      name: 'Sidebar de navegação',      location: 'Campanhas → Sidebar',              description: 'Menu lateral com "Calendário CRM", "Gerador de Tags UTM" e "Checklist de Campanha" (desabilitado)' },
  { code: 'CAL.CAL',           type: 'Seção',    name: 'Calendário FullCalendar',   location: 'Campanhas → Calendário CRM',       description: 'Grade mensal de eventos com blocos coloridos por canal' },
  { code: 'CAL.CAL.EVT',       type: 'Elemento', name: 'Evento (bloco colorido)',   location: 'Campanhas → Calendário → Grade',   description: 'Bloco de campanha no calendário; cor conforme canal (azul=Email, verde=WhatsApp, laranja=SMS)' },
  { code: 'CAL.CAL.PREV',      type: 'Botão',    name: 'Mês anterior',             location: 'Campanhas → Calendário → Toolbar', description: 'Navega para o mês anterior no calendário' },
  { code: 'CAL.CAL.NEXT',      type: 'Botão',    name: 'Próximo mês',              location: 'Campanhas → Calendário → Toolbar', description: 'Navega para o próximo mês no calendário' },
  { code: 'CAL.CAL.TODAY',     type: 'Botão',    name: 'Hoje',                     location: 'Campanhas → Calendário → Toolbar', description: 'Volta o calendário para o mês atual' },
  { code: 'CAL.MOD',           type: 'Modal',    name: 'Modal de campanha',         location: 'Campanhas → Calendário → Modal',   description: 'Modal de criação/edição de campanha aberto ao clicar em um evento ou em um dia vazio' },
  { code: 'CAL.MOD.NOME',      type: 'Campo',    name: 'Nome da campanha',          location: 'Campanhas → Modal',                description: 'Campo de texto com o título/nome da campanha' },
  { code: 'CAL.MOD.CANAL',     type: 'Campo',    name: 'Canal',                     location: 'Campanhas → Modal',                description: 'Seletor de canal: Email, SMS, WhatsApp' },
  { code: 'CAL.MOD.STATUS',    type: 'Campo',    name: 'Status',                    location: 'Campanhas → Modal',                description: 'Seletor de status: Planejada, Briefing Enviado, Programada, Finalizada' },
  { code: 'CAL.MOD.DATA',      type: 'Campo',    name: 'Data de envio',             location: 'Campanhas → Modal',                description: 'Campo de data (YYYY-MM-DD) da campanha — parseado como data local para evitar desvio de timezone' },
  { code: 'CAL.MOD.DESC',      type: 'Campo',    name: 'Descrição',                 location: 'Campanhas → Modal',                description: 'Área de texto com descrição/notas adicionais da campanha' },
  { code: 'CAL.MOD.SALVAR',    type: 'Botão',    name: 'Salvar',                    location: 'Campanhas → Modal',                description: 'Persiste a campanha na planilha Google Sheets (via API /api/events)' },
  { code: 'CAL.MOD.EXCLUIR',   type: 'Botão',    name: 'Excluir',                   location: 'Campanhas → Modal',                description: 'Remove a linha da planilha Google Sheets — exige confirmação' },
  { code: 'CAL.MOD.FECHAR',    type: 'Botão',    name: 'Fechar / X',                location: 'Campanhas → Modal',                description: 'Fecha o modal sem salvar alterações' },

  // ── UTM – Gerador de Tags UTM ──────────────────────────────────────────────
  { code: 'UTM.FORM',     type: 'Formulário', name: 'Formulário de UTM',       location: 'Campanhas → Gerador de Tags UTM', description: 'Campos para preencher os parâmetros UTM (source, medium, campaign, content, term)' },
  { code: 'UTM.OUT',      type: 'Saída',      name: 'URL com UTM gerada',      location: 'Campanhas → Gerador de Tags UTM', description: 'Campo de exibição (read-only) da URL final com os parâmetros UTM montados' },
  { code: 'UTM.COPY',     type: 'Botão',      name: 'Copiar URL',              location: 'Campanhas → Gerador de Tags UTM', description: 'Copia a URL gerada para a área de transferência' },

  // ── BRF – Campanhas → Briefings de Criação ────────────────────────────────
  { code: 'BRF.ALERTA',       type: 'Alerta',   name: 'Banner de urgência',        location: 'Campanhas → Briefings de Criação',          description: 'Caixa vermelha listando briefings de E-mail Planejada cujo prazo já venceu ou vence hoje' },
  { code: 'BRF.FLT',          type: 'Filtro',   name: 'Filtros de status',         location: 'Campanhas → Briefings de Criação',          description: 'Chips: Todas | Briefing Urgente | Planejada | Briefing Enviado | Programada' },
  { code: 'BRF.TAB',          type: 'Tabela',   name: 'Tabela de briefings',       location: 'Campanhas → Briefings de Criação',          description: 'Lista todas as campanhas não-finalizadas com colunas de prazo de briefing' },
  { code: 'BRF.TAB.DOT',      type: 'Indicador','name': 'Bolinha de urgência',     location: 'Campanhas → Briefings → Tabela',            description: 'Vermelho = vencido; Amarelo = vence em ≤ 2 dias; Verde = ok; Cinza = não se aplica (não é E-mail Planejada)' },
  { code: 'BRF.TAB.DATA',     type: 'Coluna',   name: 'Data envio',                location: 'Campanhas → Briefings → Tabela',            description: 'Data de envio da campanha formatada dd/mm/aaaa' },
  { code: 'BRF.TAB.NOME',     type: 'Coluna',   name: 'Nome da campanha',          location: 'Campanhas → Briefings → Tabela',            description: 'Título original da campanha vindo da planilha' },
  { code: 'BRF.TAB.CANAL',    type: 'Coluna',   name: 'Canal',                     location: 'Campanhas → Briefings → Tabela',            description: 'Canal da campanha: Email, SMS, WhatsApp, etc.' },
  { code: 'BRF.TAB.STATUS',   type: 'Coluna',   name: 'Status',                    location: 'Campanhas → Briefings → Tabela',            description: 'Status atual da campanha (Planejada, Briefing Enviado, Programada…)' },
  { code: 'BRF.TAB.DL',       type: 'Coluna',   name: 'Data limite briefing',      location: 'Campanhas → Briefings → Tabela',            description: 'Data limite = data de envio − 10 dias; exibida apenas para E-mail com status Planejada' },
  { code: 'BRF.TAB.DIAS',     type: 'Coluna',   name: 'Dias restantes',            location: 'Campanhas → Briefings → Tabela',            description: 'Dias até o prazo de briefing; "Vence hoje" ou "Xd vencido" quando ≤ 0' },
  { code: 'BRF.TAB.EDIT',     type: 'Botão',    name: 'Editar',                    location: 'Campanhas → Briefings → Tabela',            description: 'Abre o modal de edição (CAL.MOD) pré-preenchido com os dados da campanha' },

  // ── GNT – Projetos (Gantt) ─────────────────────────────────────────────────
  { code: 'GNT.CAL',     type: 'Seção',  name: 'Diagrama de Gantt',         location: 'Projetos',    description: 'Visualização em Gantt das tarefas/projetos CRM' },

  // ── RG – Resultado Geral (compartilhado) ──────────────────────────────────
  { code: 'RG.NAV',           type: 'Nav',    name: 'Sidebar de sub-visões',    location: 'Resultado Geral → Sidebar',    description: 'Botões Executivo | Atribuída Detalhada | Direta Detalhada para alternar sub-visualizações' },
  { code: 'RG.FILTRO',        type: 'Seção',  name: 'Filtro de datas',          location: 'Resultado Geral → Filtros',    description: 'Caixa com campos de data inicial e final e botão Atualizar — compartilhada pelas 3 sub-visões' },
  { code: 'RG.FILTRO.INI',    type: 'Campo',  name: 'Data inicial',             location: 'Resultado Geral → Filtros',    description: 'Input de data de início do período a ser consultado' },
  { code: 'RG.FILTRO.FIM',    type: 'Campo',  name: 'Data final',               location: 'Resultado Geral → Filtros',    description: 'Input de data de fim do período a ser consultado' },
  { code: 'RG.FILTRO.BTN',    type: 'Botão',  name: 'Atualizar',                location: 'Resultado Geral → Filtros',    description: 'Dispara as chamadas de API para a sub-visão ativa com o período selecionado' },

  // ── RGE – Resultado Geral → Executivo ─────────────────────────────────────
  { code: 'RGE.EMARSYS',          type: 'Seção',    name: 'Receita Emarsys',           location: 'Resultado Geral → Executivo',                  description: 'Card com Total iPlace e Atribuída CRM + breakdown por categoria' },
  { code: 'RGE.EMARSYS.TIPL',     type: 'Card',     name: 'Total iPlace',              location: 'Resultado Geral → Executivo → Receita Emarsys', description: 'Total de compras com CPF (campo total_crm); fonte: BigQuery si_purchases + revenue_attribution' },
  { code: 'RGE.EMARSYS.ACRM',     type: 'Card',     name: 'Atribuída CRM',             location: 'Resultado Geral → Executivo → Receita Emarsys', description: 'Receita atribuída ao CRM pelo Emarsys (campo reportado); percentual do Total iPlace' },
  { code: 'RGE.EMARSYS.CAT',      type: 'Cards',    name: 'Cards por categoria',       location: 'Resultado Geral → Executivo → Receita Emarsys', description: 'Mini-cards: Marketing (verde), Transacional (âmbar), NPS / Pesquisa (azul), Serviço / AT (cinza)' },
  { code: 'RGE.DIRETA',           type: 'Seção',    name: 'Receita Direta GA4',        location: 'Resultado Geral → Executivo',                  description: 'Card com receita total consolidada, CRM e Não-CRM via GA4' },
  { code: 'RGE.DIRETA.CONS',      type: 'Card',     name: 'Total Consolidado',         location: 'Resultado Geral → Executivo → Receita Direta',  description: 'Soma de purchaseCrm + purchaseNonCrm do GA4' },
  { code: 'RGE.DIRETA.CRM',       type: 'Card',     name: 'Receita CRM',               location: 'Resultado Geral → Executivo → Receita Direta',  description: 'purchaseRevenue de sessões com origem CRM (GA4 /api/ga4/crm/monthly)' },
  { code: 'RGE.DIRETA.NCRM',      type: 'Card',     name: 'Receita Não-CRM',           location: 'Resultado Geral → Executivo → Receita Direta',  description: 'purchaseRevenue de cupons de carrinho abandonado não-CRM (/api/ga4/abandoned-cart-coupons)' },
  { code: 'RGE.COMP',             type: 'Seção',    name: 'Comparativo de Período',    location: 'Resultado Geral → Executivo',                  description: 'Box com datas de comparativo (padrão = YoY) e boxes de resultado por canal' },
  { code: 'RGE.COMP.INI',         type: 'Campo',    name: 'Data inicial comparativo',  location: 'Resultado Geral → Executivo → Comparativo',    description: 'Input de data inicial do período comparativo; inicializa em YoY da data principal' },
  { code: 'RGE.COMP.FIM',         type: 'Campo',    name: 'Data final comparativo',    location: 'Resultado Geral → Executivo → Comparativo',    description: 'Input de data final do período comparativo; inicializa em YoY da data principal' },
  { code: 'RGE.COMP.BTN',         type: 'Botão',    name: 'Comparar',                  location: 'Resultado Geral → Executivo → Comparativo',    description: 'Busca dados do período comparativo via /api/ga4/crm/range com as datas exatas' },
  { code: 'RGE.COMP.CANAIS',      type: 'Cards',    name: 'Resultado por canal',       location: 'Resultado Geral → Executivo → Comparativo',    description: 'Um card por canal (Email, SMS, WhatsApp) com receita e variação % em relação ao período comparativo' },
  { code: 'RGE.CHT',              type: 'Seção',    name: 'Gráfico diário de receita', location: 'Resultado Geral → Executivo',                  description: 'Gráfico de linhas (Recharts) mostrando evolução diária de Total iPlace e Receita Atribuída' },
  { code: 'RGE.CHT.TIPL',         type: 'Série',    name: 'Linha Total iPlace',        location: 'Resultado Geral → Executivo → Gráfico',        description: 'Série roxa (violeta) representando total_iplace por dia; fonte: /api/open-data/emarsys/daily-revenue' },
  { code: 'RGE.CHT.RATR',         type: 'Série',    name: 'Linha Receita Atribuída',   location: 'Resultado Geral → Executivo → Gráfico',        description: 'Série azul representando receita_atribuida por dia; fonte: /api/open-data/emarsys/daily-revenue' },
  { code: 'RGE.CHT.TOOLTIP',      type: 'Elemento', name: 'Tooltip do gráfico',        location: 'Resultado Geral → Executivo → Gráfico',        description: 'Popup ao passar o mouse: exibe data e valores de Total iPlace (primeiro) e Receita Atribuída em R$' },
  { code: 'RGE.CHT.TIPL_TOT',     type: 'Card',     name: 'Total iPlace (soma)',        location: 'Resultado Geral → Executivo → Gráfico',        description: 'Card abaixo do gráfico com soma total de Total iPlace no período em formato MM/K' },
  { code: 'RGE.CHT.RATR_TOT',     type: 'Card',     name: 'Receita Atribuída (soma)',   location: 'Resultado Geral → Executivo → Gráfico',        description: 'Card abaixo do gráfico com soma total de Receita Atribuída no período em formato MM/K' },

  // ── RGA – Resultado Geral → Atribuída Detalhada ───────────────────────────
  { code: 'RGA.EMARSYS',      type: 'Seção',  name: 'Resumo Emarsys',            location: 'Resultado Geral → Atribuída Detalhada',           description: 'Mesmos cards de Total iPlace e Atribuída CRM + categorias (mesmo componente ResumoAtribuicao)' },
  { code: 'RGA.FLT_CAT',      type: 'Filtro', name: 'Filtro por categoria',      location: 'Resultado Geral → Atribuída Detalhada',           description: 'Chips: Todos | Marketing | Transacional | NPS / Pesquisa | Serviço / AT' },
  { code: 'RGA.TAB',          type: 'Tabela', name: 'Tabela de campanhas',       location: 'Resultado Geral → Atribuída Detalhada → Tabela',  description: 'Lista campanhas atribuídas com colunas de categoria, canal, receita e nº de pedidos' },
  { code: 'RGA.TAB.NOME',     type: 'Coluna', name: 'Nome da campanha',          location: 'Resultado Geral → Atribuída Detalhada → Tabela',  description: 'Nome da campanha Emarsys' },
  { code: 'RGA.TAB.CAT',      type: 'Coluna', name: 'Categoria',                 location: 'Resultado Geral → Atribuída Detalhada → Tabela',  description: 'Badge de categoria: Marketing, Transacional, NPS/Pesquisa, Serviço/AT' },
  { code: 'RGA.TAB.CANAL',    type: 'Coluna', name: 'Canal',                     location: 'Resultado Geral → Atribuída Detalhada → Tabela',  description: 'Canal do disparo: Email, SMS, WhatsApp' },
  { code: 'RGA.TAB.RECEITA',  type: 'Coluna', name: 'Receita Atribuída',         location: 'Resultado Geral → Atribuída Detalhada → Tabela',  description: 'Valor em R$ atribuído à campanha pelo Emarsys (receita_influenciada)' },
  { code: 'RGA.TAB.PEDIDOS',  type: 'Coluna', name: 'Pedidos',                   location: 'Resultado Geral → Atribuída Detalhada → Tabela',  description: 'Número de pedidos atribuídos à campanha' },

  // ── RGD – Resultado Geral → Direta Detalhada ──────────────────────────────
  { code: 'RGD.GA4',          type: 'Seção',  name: 'Receita Direta GA4',        location: 'Resultado Geral → Direta Detalhada',              description: 'Boxes de receita CRM e não-CRM por canal com variação vs período comparativo' },
  { code: 'RGD.GA4.COMP',     type: 'Seção',  name: 'Comparativo GA4',           location: 'Resultado Geral → Direta Detalhada',              description: 'Inputs de período de comparação e botão Comparar para buscar dados históricos' },
  { code: 'RGD.GA4.COMP.INI', type: 'Campo',  name: 'Data inicial comparativo',  location: 'Resultado Geral → Direta Detalhada → Comparativo','description': 'Input de data inicial do comparativo — inicializa em YoY' },
  { code: 'RGD.GA4.COMP.FIM', type: 'Campo',  name: 'Data final comparativo',    location: 'Resultado Geral → Direta Detalhada → Comparativo','description': 'Input de data final do comparativo' },
  { code: 'RGD.GA4.CANAIS',   type: 'Cards',  name: 'Cards por canal',           location: 'Resultado Geral → Direta Detalhada',              description: 'Um card por canal (Email, SMS, WhatsApp) com métricas de GA4 e variação percentual' },
  { code: 'RGD.CARR',         type: 'Seção',  name: 'Carrinho Abandonado',       location: 'Resultado Geral → Direta Detalhada',              description: 'Box de cupons de carrinho abandonado não-CRM com receita GA4' },
  { code: 'RGD.CARR.TAB',     type: 'Tabela', name: 'Tabela de cupons',          location: 'Resultado Geral → Direta Detalhada → Carrinho',   description: 'Lista de cupons não-CRM com receita e pedidos associados' },

  // ── AUD – Auditoria ────────────────────────────────────────────────────────
  { code: 'AUD.FILTRO',       type: 'Seção',  name: 'Filtro de datas',           location: 'Auditoria → Filtros',                    description: 'Campos de data inicial e final + botão Consultar para disparar as consultas de auditoria' },
  { code: 'AUD.REC',          type: 'Seção',  name: 'Receita por Campanha',      location: 'Auditoria',                              description: 'Tabela de campanhas com receita atribuída e cruzamento com si_purchases' },
  { code: 'AUD.CRUZ',         type: 'Seção',  name: 'Cruzamento de Atribuição',  location: 'Auditoria',                              description: 'Detalhe de pedidos que o Emarsys atribuiu, com valor original na si_purchases' },
  { code: 'AUD.CRUZ.TAB',     type: 'Tabela', name: 'Tabela de cruzamento',      location: 'Auditoria → Cruzamento',                 description: 'Colunas: campanha, order_id, receita Emarsys, receita si_purchases, diferença' },
  { code: 'AUD.DEV',          type: 'Seção',  name: '"Deveria Atribuir"',         location: 'Auditoria',                              description: 'Pedidos presentes na si_purchases que o Emarsys não atribuiu mas deveria — botão "Carregar" sob demanda' },
  { code: 'AUD.CANAIS',       type: 'Seção',  name: 'Apuração por Canal',        location: 'Auditoria',                              description: 'Dois blocos independentes (SMS e E-mail) com detalhamento de campanhas por canal' },
  { code: 'AUD.CANAIS.SMS',   type: 'Bloco',  name: 'Bloco SMS',                 location: 'Auditoria → Apuração por Canal',         description: 'Tabela de campanhas SMS com receita, pedidos e percentual de atribuição' },
  { code: 'AUD.CANAIS.EMAIL', type: 'Bloco',  name: 'Bloco E-mail',              location: 'Auditoria → Apuração por Canal',         description: 'Tabela de campanhas E-mail com receita, pedidos e percentual de atribuição' },
  { code: 'AUD.EXP',          type: 'Botão',  name: 'Exportar CSV',              location: 'Auditoria',                              description: 'Botão que baixa os dados da auditoria em formato CSV' },

  // ── ADM – Administração ────────────────────────────────────────────────────
  { code: 'ADM.NAV',         type: 'Nav',    name: 'Sidebar de navegação Adm',   location: 'Adm → Sidebar',                  description: 'Menu lateral com todas as sub-seções administrativas' },
  { code: 'ADM.OPEN',        type: 'Seção',  name: 'Open Data Emarsys',          location: 'Adm → Open Data Emarsys',        description: 'Tabela de raw data do Emarsys com limite de 200 linhas; filtros por campo' },
  { code: 'ADM.AUTO',        type: 'Seção',  name: 'Resultados de Automações',   location: 'Adm → Resultados de Automações', description: 'Resultados da automação de aniversário (3 partes: 7d antes, dia, 12d depois) com cupom IPLACEANIVER' },
  { code: 'ADM.EXP',         type: 'Seção',  name: 'Explorador de Tabelas',      location: 'Adm → Explorador de Tabelas',    description: 'Interface para explorar tabelas do BigQuery ad-hoc' },
  { code: 'ADM.RECTEST',     type: 'Seção',  name: 'Receita Teste',              location: 'Adm → Receita Teste',            description: 'Área de testes para novas consultas de receita antes de promover para produção' },
  { code: 'ADM.COMP',        type: 'Seção',  name: 'Comparativo CRM',            location: 'Adm → Comparativo CRM',         description: 'Comparativo detalhado de métricas CRM entre dois períodos' },
  { code: 'ADM.APURC',       type: 'Seção',  name: 'Apuração de Campanhas',      location: 'Adm → Apuração de Campanhas',   description: 'Detalhamento de campanhas dividido em dois blocos: SMS e E-mail' },
  { code: 'ADM.APURC.SMS',   type: 'Bloco',  name: 'Bloco SMS',                  location: 'Adm → Apuração de Campanhas',   description: 'Campanhas SMS com receita, pedidos, taxa de atribuição e comparativo de períodos' },
  { code: 'ADM.APURC.EMAIL', type: 'Bloco',  name: 'Bloco E-mail',               location: 'Adm → Apuração de Campanhas',   description: 'Campanhas E-mail com mesmas métricas do bloco SMS' },
  { code: 'ADM.PERM',        type: 'Seção',  name: 'Permissões de Acesso',       location: 'Adm → Permissões de Acesso',    description: 'Gerenciamento de usuários e controle de quais abas (Resultado Geral, Campanhas, Projetos, Auditoria) cada usuário pode ver' },
  { code: 'ADM.PERM.TAB',    type: 'Tabela', name: 'Tabela de usuários',         location: 'Adm → Permissões de Acesso',    description: 'Lista de usuários com toggles por aba; permite habilitar/desabilitar o acesso a cada seção do portal' },
]

const TYPE_COLORS = {
  'Aba':        'bg-blue-50 text-blue-700',
  'Alerta':     'bg-rose-50 text-rose-700',
  'Bloco':      'bg-slate-100 text-slate-600',
  'Botão':      'bg-emerald-50 text-emerald-700',
  'Campo':      'bg-amber-50 text-amber-700',
  'Card':       'bg-violet-50 text-violet-700',
  'Cards':      'bg-violet-50 text-violet-700',
  'Coluna':     'bg-slate-100 text-slate-600',
  'Elemento':   'bg-slate-100 text-slate-600',
  'Filtro':     'bg-amber-50 text-amber-700',
  'Formulário': 'bg-amber-50 text-amber-700',
  'Imagem':     'bg-pink-50 text-pink-700',
  'Indicador':  'bg-orange-50 text-orange-700',
  'Info':       'bg-slate-100 text-slate-600',
  'Modal':      'bg-purple-50 text-purple-700',
  'Nav':        'bg-indigo-50 text-indigo-700',
  'Saída':      'bg-teal-50 text-teal-700',
  'Seção':      'bg-sky-50 text-sky-700',
  'Série':      'bg-cyan-50 text-cyan-700',
  'Tabela':     'bg-slate-100 text-slate-600',
}

const ALL_SCREENS = ['Todos', 'LOGIN', 'NAV', 'CAL', 'UTM', 'BRF', 'GNT', 'RG', 'RGE', 'RGA', 'RGD', 'AUD', 'ADM']

function screenPrefix(code) {
  return code.split('.')[0]
}

export default function PortalMapPage() {
  const [search, setSearch] = useState('')
  const [screenFilter, setScreenFilter] = useState('Todos')

  const rows = useMemo(() => {
    const q = search.toLowerCase().trim()
    return ELEMENTS.filter((el) => {
      const matchScreen = screenFilter === 'Todos' || screenPrefix(el.code) === screenFilter
      if (!matchScreen) return false
      if (!q) return true
      return (
        el.code.toLowerCase().includes(q) ||
        el.name.toLowerCase().includes(q) ||
        el.type.toLowerCase().includes(q) ||
        el.location.toLowerCase().includes(q) ||
        el.description.toLowerCase().includes(q)
      )
    })
  }, [search, screenFilter])

  return (
    <div className="mx-auto max-w-7xl px-4 py-8 md:px-6 lg:px-8">
      <div className="mb-6">
        <h1 className="text-xl font-bold text-slate-900">Mapa do Portal</h1>
        <p className="mt-1 text-sm text-slate-500">
          Referência de todos os elementos do portal com seus códigos semânticos.
          Atualize este arquivo sempre que adicionar, remover ou renomear um elemento.
        </p>
      </div>

      <section className="mb-5 rounded-2xl border border-slate-200 bg-white p-4 shadow-soft">
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1 text-sm text-slate-600">
            Buscar
            <input
              type="text"
              placeholder="código, nome, tipo ou descrição…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-72 rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 outline-none focus:border-slate-500 focus:ring-2 focus:ring-slate-200"
            />
          </label>

          <div className="flex flex-wrap gap-2">
            {ALL_SCREENS.map((s) => (
              <button
                key={s}
                onClick={() => setScreenFilter(s)}
                className={`rounded-full px-3 py-1 text-xs font-semibold transition ${
                  screenFilter === s
                    ? 'bg-slate-900 text-white'
                    : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                }`}
              >
                {s}
              </button>
            ))}
          </div>
        </div>

        <p className="mt-3 text-xs text-slate-400">
          {rows.length} de {ELEMENTS.length} elementos
        </p>
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white shadow-soft">
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200">
                <th className="whitespace-nowrap px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">Código</th>
                <th className="whitespace-nowrap px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">Tipo</th>
                <th className="whitespace-nowrap px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">Nome</th>
                <th className="whitespace-nowrap px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">Localização</th>
                <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">Descrição</th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-4 py-6 text-center text-sm text-slate-400">
                    Nenhum elemento encontrado.
                  </td>
                </tr>
              ) : (
                rows.map((el, i) => (
                  <tr key={el.code} className={i % 2 === 0 ? 'bg-white' : 'bg-slate-50'}>
                    <td className="whitespace-nowrap px-4 py-2.5">
                      <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs text-slate-800">
                        {el.code}
                      </code>
                    </td>
                    <td className="whitespace-nowrap px-4 py-2.5">
                      <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${TYPE_COLORS[el.type] ?? 'bg-slate-100 text-slate-600'}`}>
                        {el.type}
                      </span>
                    </td>
                    <td className="whitespace-nowrap px-4 py-2.5 font-medium text-slate-800">{el.name}</td>
                    <td className="whitespace-nowrap px-4 py-2.5 text-slate-500">{el.location}</td>
                    <td className="px-4 py-2.5 text-slate-600">{el.description}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
