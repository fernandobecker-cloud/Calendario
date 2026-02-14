# CRM Campaign Planner

Sistema interno para calendário de campanhas de CRM.

## Stack
- Backend: FastAPI
- Frontend: HTML + CSS + JavaScript + FullCalendar (CDN)
- Fonte de dados: Google Sheets CSV público
- Deploy: Render (Web Service)

## Estrutura do projeto
```text
crm-calendario/
├── server.py               # Entrypoint ASGI (uvicorn server:app)
├── start.sh                # Start script para Render (usa $PORT)
├── render.yaml             # Infra as code para deploy automático na Render
├── backend/
│   └── server.py           # API + serving de frontend estático
├── frontend/
│   ├── index.html
│   ├── script.js
│   └── style.css
├── requirements.txt
└── README.md
```

## Executar localmente
1. Criar ambiente virtual:
```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. Instalar dependências:
```bash
pip install -r requirements.txt
```

3. Rodar servidor:
```bash
uvicorn server:app --reload
```

4. Acessar:
- App: `http://127.0.0.1:8000/`
- API: `http://127.0.0.1:8000/api/events`
- Healthcheck: `http://127.0.0.1:8000/health`

## Deploy na Render (automático após push)
### Opção recomendada: Blueprint com `render.yaml`
1. Suba o repositório no GitHub.
2. Na Render, clique em `New +` -> `Blueprint`.
3. Selecione o repositório.
4. A Render criará o serviço com:
   - Build command: `pip install -r requirements.txt`
   - Start command: `bash start.sh`
   - Health check path: `/health`
   - Auto deploy: `true`

Depois disso, cada `git push` na branch conectada dispara novo deploy automaticamente.

### Opção manual (sem Blueprint)
Configure no Web Service:
- Build Command: `pip install -r requirements.txt`
- Start Command: `bash start.sh`
- Environment: `Python`

## API
### `GET /api/events`
Retorna JSON padronizado:
```json
{
  "events": [
    {
      "id": "2026-02-14_Valentine Sale",
      "title": "Valentine Sale",
      "start": "2026-02-14",
      "allDay": true,
      "backgroundColor": "#0071E3",
      "borderColor": "#0071E3",
      "extendedProps": {
        "canal": "Email",
        "produto": "Roupas",
        "observacao": "Texto opcional",
        "data_original": "14/02/2026"
      }
    }
  ],
  "total": 1
}
```

## Mapeamento de colunas do Google Sheets
Mapeamento tolerante a acento/caixa e aliases:
- Data: `DATA`
- Campanha: `CAMPANHA`, `ASSUNTO`, `TITULO`, `TITLE`
- Canal: `CANAL`, `CHANNEL`
- Produto: `PRODUTO`, `PRODUCT`
- Observação: `OBSERVACAO`, `OBS`, `OBSERVATION`

Colunas obrigatórias: `DATA` e `CAMPANHA/ASSUNTO`.

## Observações de produção
- A rota `/` serve `frontend/index.html`.
- Arquivos estáticos são servidos em `/static`.
- A API consulta o CSV do Google Sheets a cada chamada em `/api/events`.
- Não há banco de dados.
