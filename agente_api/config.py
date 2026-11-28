"""Configuracao do servico do agente de IA (Omnichat), lida das env vars.

Todas as regras de preco ficam aqui para poderem mudar na Render (Environment)
sem deploy de codigo - por exemplo, se na Black o desconto do Pix mudar.
"""

import os


def _float(nome: str, padrao: float) -> float:
    valor = os.getenv(nome, "").strip().replace(",", ".")
    return float(valor) if valor else padrao


def _int(nome: str, padrao: int) -> int:
    valor = os.getenv(nome, "").strip()
    return int(valor) if valor else padrao


def _bool(nome: str, padrao: bool) -> bool:
    valor = os.getenv(nome, "").strip().lower()
    if not valor:
        return padrao
    return valor in ("1", "true", "sim", "yes", "s")


# Token que a Omnichat manda em toda chamada (header x-api-key, Authorization:
# Bearer ou ?token= na URL). Sem ele configurado, o servico recusa tudo.
TOKEN = os.getenv("AGENTE_API_TOKEN", "").strip()

# Site da iPlace (Oracle Commerce Cloud) - API publica de vitrine, so leitura.
ORACLE_BASE_URL = os.getenv("ORACLE_BASE_URL", "https://www.iplace.com.br").strip().rstrip("/")
ORACLE_TIMEOUT_S = _float("ORACLE_TIMEOUT_S", 5.0)
ORACLE_MAX_CONCORRENTES = _int("ORACLE_MAX_CONCORRENTES", 5)
USER_AGENT = os.getenv("AGENTE_USER_AGENT", "iplace-crm-agente-ia/1.0").strip()

# O Akamai na frente do site bloqueia (403) chamadas de servidor que nao vem de
# navegador. A liberacao e feita pelo TI com uma regra de excecao; se a regra
# for por cabecalho, o nome e o valor combinados com o TI entram aqui.
# Ex.: ORACLE_HEADER_LIBERACAO_NOME=X-Iplace-Agente  ORACLE_HEADER_LIBERACAO_VALOR=<segredo>
ORACLE_HEADER_LIBERACAO_NOME = os.getenv("ORACLE_HEADER_LIBERACAO_NOME", "").strip()
ORACLE_HEADER_LIBERACAO_VALOR = os.getenv("ORACLE_HEADER_LIBERACAO_VALOR", "").strip()

# Regras de pagamento, conferidas em 13/11/2026 contra 4 paginas de produto do
# site (iPhone 17 Pro Max, Apple Watch SE, AirPods Pro 3, MacBook Air M5):
#   Pix    = preco de venda - 10%
#   Cartao = preco de venda em ate 21x com juros de 1,05% a.m. (tabela Price)
PIX_DESCONTO = _float("PIX_DESCONTO", 0.10)
CARTAO_MAX_PARCELAS = _int("CARTAO_MAX_PARCELAS", 21)
CARTAO_JUROS_MENSAL_PCT = _float("CARTAO_JUROS_MENSAL_PCT", 1.05)
# Valor minimo de cada parcela; abaixo disso o numero de parcelas diminui.
PARCELA_MINIMA = _float("PARCELA_MINIMA", 5.0)
# Site: o preco no cartao sai em ate 10x sem juros (alem do 21x com juros). 0 = desliga.
CARTAO_SEM_JUROS_PARCELAS = _int("CARTAO_SEM_JUROS_PARCELAS", 10)

# Cache em memoria das respostas do site. Preco/estoque atualizam em ate TTL.
CACHE_TTL_S = _int("CACHE_TTL_S", 120)
CACHE_MAX_ITENS = _int("CACHE_MAX_ITENS", 2000)

# Produto sem estoque em nenhuma variante: por padrao nao vai para o agente.
MOSTRAR_SEM_ESTOQUE = _bool("MOSTRAR_SEM_ESTOQUE", False)

# Parametros anexados ao link do produto, para medir as vendas do agente no GA.
UTM = os.getenv(
    "AGENTE_UTM",
    "utm_source=omnichat&utm_medium=agente_ia&utm_campaign=whizz",
).strip().lstrip("?")

# Limite de produtos por busca (a Omnichat pede 10 por padrao).
MAX_ITENS_POR_BUSCA = _int("MAX_ITENS_POR_BUSCA", 20)

# De onde vem o catalogo:
#   "planilha" = planilha da campanha que o CRM sobe no portal (aba Catalogo do
#                agente). Plano B enquanto o Akamai bloqueia o site.
#   "site"     = API publica do Oracle Commerce (precisa da liberacao do TI).
# Para trocar, basta mudar AGENTE_FONTE no Environment da Render.
FONTE = os.getenv("AGENTE_FONTE", "planilha").strip().lower()

# Onde a planilha e lida: endpoint do portal que devolve as linhas ja
# validadas. Autenticado com o mesmo AGENTE_API_TOKEN.
PLANILHA_URL = os.getenv(
    "AGENTE_PLANILHA_URL",
    "https://calendario-39gp.onrender.com/api/agente-ia/planilha/feed",
).strip()
# A planilha e relida a cada PLANILHA_TTL_S; se o portal cair, segue com a
# ultima copia boa.
PLANILHA_TTL_S = _int("PLANILHA_TTL_S", 60)
PLANILHA_TIMEOUT_S = _float("PLANILHA_TIMEOUT_S", 20.0)

# Fila do televendas (ver fila.py). A Omnichat manda os eventos de atendimento
# para POST /omnichat/webhook com este token no header Authorization (Bearer).
OMNI_WEBHOOK_TOKEN = os.getenv("OMNI_WEBHOOK_TOKEN", "").strip()
# Modo, time do televendas e limites são escolhidos no portal e lidos daqui.
TELEVENDAS_CONFIG_URL = os.getenv(
    "AGENTE_TELEVENDAS_CONFIG_URL",
    "https://calendario-39gp.onrender.com/api/agente-ia/televendas/config",
).strip()
TELEVENDAS_CONFIG_TTL_S = _int("TELEVENDAS_CONFIG_TTL_S", 30)
# Espera mais longa que isso sai da conta (evento perdido não trava a fila).
ESPERA_MAX_S = _int("FILA_ESPERA_MAX_MIN", 120) * 60
# Os eventos vão para o portal (histórico no BigQuery e painel das filas por loja).
FILA_EVENTOS_URL = os.getenv(
    "AGENTE_FILA_EVENTOS_URL",
    "https://calendario-39gp.onrender.com/api/agente-ia/fila/eventos",
).strip()
FILA_ENVIO_S = _int("FILA_ENVIO_S", 30)
# Status das mensagens de campanha (webhook message-status) vão para cá (ver campanha_status.py).
CAMPANHA_STATUS_URL = os.getenv(
    "AGENTE_CAMPANHA_STATUS_URL",
    FILA_EVENTOS_URL.replace("/fila/eventos", "/campanhas/status") if FILA_EVENTOS_URL else "",
).strip()

# API v1 da Omnichat (ver omni_interacoes.py): origem do atendimento (campanha x
# orgânico) e o momento em que o vendedor assumiu, que o webhook não manda.
# Sem as duas chaves, fica desligado. A Omnichat limita a 10 req/s somando todas
# as integrações da loja; aqui fica bem abaixo disso.
OMNI_API_URL = os.getenv("OMNI_API_URL", "https://api.omni.chat/v1").strip().rstrip("/")
OMNI_API_KEY = os.getenv("OMNI_API_KEY", "").strip()
OMNI_API_SECRET = os.getenv("OMNI_API_SECRET", "").strip()
OMNI_API_RPS = _float("OMNI_API_RPS", 1.0)
# A cada quanto reconsultar quem ainda espera na fila (para saber quando foi assumido).
OMNI_RECONSULTA_S = _int("OMNI_RECONSULTA_S", 90)
