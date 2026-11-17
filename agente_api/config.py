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
