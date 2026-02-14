# CRM Campaign Planner

Sistema interno para visualizar campanhas de CRM em calendário mensal.

## Stack
- Backend: FastAPI
- Frontend: HTML + CSS + JavaScript (FullCalendar via CDN)
- Fonte de dados: CSV público do Google Sheets

## Estrutura
```text
crm-calendario/
├── server.py            # Entrypoint (uvicorn server:app --reload)
├── backend/
│   └── server.py        # API, leitura do Google Sheets e serving do frontend
├── frontend/
│   ├── index.html
│   ├── script.js
│   └── style.css
├── requirements.txt
└── README.md
```

## Executar do zero
1. Criar e ativar ambiente virtual:
```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. Instalar dependências:
```bash
pip install -r requirements.txt
```

3. Rodar aplicação:
```bash
uvicorn server:app --reload
```

4. Acessar:
```text
http://127.0.0.1:8000
```

## API
### `GET /api/events`
Retorna eventos já no formato esperado pelo FullCalendar.

Exemplo:
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
        "observacao": "Black Friday especial",
        "data_original": "14/02/2026"
      }
    }
  ],
  "total": 1
}
```

## Mapeamento de colunas do Sheets
O backend tenta identificar automaticamente estes nomes (aceita variações):
- Data: `DATA`
- Campanha: `CAMPANHA`, `ASSUNTO`, `TITULO`, `TITLE`
- Canal: `CANAL`, `CHANNEL`
- Produto: `PRODUTO`, `PRODUCT`
- Observação: `OBSERVACAO`, `OBS`, `OBSERVATION`

`DATA` e `CAMPANHA/ASSUNTO` são obrigatórias.

## Observações
- Não usa banco de dados.
- Os dados são buscados no Google Sheets a cada chamada de `/api/events`.
- Cores por canal:
  - Email: `#0071E3`
  - WhatsApp: `#25D366`
  - SMS: `#FF9F0A`
