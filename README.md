# CRM Campaign Planner

Sistema interno para calendário de campanhas de CRM com frontend React e backend FastAPI.

## Stack
- Backend: FastAPI
- Frontend: React + Vite + TailwindCSS + FullCalendar
- Fonte de dados: Google Sheets CSV público
- Deploy: Render (Web Service)

## Estrutura
```text
crm-calendario/
├── server.py
├── start.sh
├── render.yaml
├── backend/
│   └── server.py
├── frontend/
│   ├── index.html
│   ├── package.json
│   ├── postcss.config.js
│   ├── tailwind.config.js
│   ├── vite.config.js
│   ├── src/
│   │   ├── App.jsx
│   │   ├── index.css
│   │   └── main.jsx
│   └── dist/                 # gerado pelo npm run build
├── requirements.txt
└── README.md
```

## Como rodar localmente (backend + frontend buildado)
1. Criar e ativar ambiente virtual:
```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. Instalar dependências Python:
```bash
pip install -r requirements.txt
```

3. Instalar dependências frontend:
```bash
cd frontend
npm ci
```

4. Gerar build React:
```bash
npm run build
cd ..
```

5. Subir API + frontend pelo FastAPI:
```bash
uvicorn server:app --reload
```

6. Acessar:
- App: `http://127.0.0.1:8000/`
- API: `http://127.0.0.1:8000/api/events`
- Health: `http://127.0.0.1:8000/health`

## Desenvolvimento do frontend (hot reload)
Em outro terminal:
```bash
cd frontend
npm run dev
```

Durante o desenvolvimento você pode usar o Vite em `http://127.0.0.1:5173`.

## Deploy na Render (automático após git push)
Este repositório usa `render.yaml` com:
- Build command: `pip install -r requirements.txt && cd frontend && npm ci && npm run build`
- Start command: `bash start.sh`
- Health check: `/health`

Passos:
1. Suba o repositório no GitHub.
2. Na Render: `New +` -> `Blueprint`.
3. Selecione o repositório.
4. Deploy automático será executado a cada `git push`.

## Autenticação com usuário e senha (opcional)
Para restringir o acesso externo, você pode habilitar `Basic Auth` no backend.

Defina estas variáveis de ambiente:
- `AUTH_USERNAME`: usuário de acesso
- `AUTH_PASSWORD`: senha de acesso

Com as duas variáveis definidas, o app inteiro (frontend + `/api/events`) exige login.
A rota `/health` continua pública para o health check da Render.

Exemplo local:
```bash
export AUTH_USERNAME=admin
export AUTH_PASSWORD=sua_senha_forte
uvicorn server:app --reload
```

Na Render:
1. Abra o serviço `crm-campaign-planner`.
2. Vá em `Environment`.
3. Adicione `AUTH_USERNAME` e `AUTH_PASSWORD`.
4. Faça `Manual Deploy` (ou novo `git push`).

## API
### `GET /api/events`
Contrato preservado:
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

## Observações
- O backend serve o build React em `/`.
- Arquivos gerados pelo Vite são servidos de `frontend/dist`.
- A rota `/api/events` não foi alterada.
- Defina `CORS_ALLOWED_ORIGINS` na Render com o domínio do app (ex.: `https://calendario-39gp.onrender.com`).
