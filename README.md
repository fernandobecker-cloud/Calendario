# 📅 CRM Campaign Planner

Um sistema web interno completo para gerenciar um calendário editorial de campanhas de CRM. Aplicação desenvolvida com FastAPI (backend) e HTML + CSS + JavaScript puro (frontend), utilizando a biblioteca FullCalendar para visualização interativa.

## 🎯 Características

✅ **Calendário Visual Interativo** - Visualize todas as campanhas em um calendário mensal bonito e intuitivo  
✅ **Sincronização Automática** - Dados carregados diretamente do Google Sheets CSV público  
✅ **Design Apple-like** - Interface limpa, moderna e responsiva  
✅ **Color-coded Channels** - Cores diferentes para cada canal (Email, WhatsApp, SMS)  
✅ **Detecção de Saturação** - Alerta visual quando há mais de 3 campanhas no mesmo dia  
✅ **Informações Completas** - Ao clicar em uma campanha, veja todos os detalhes (data, canal, produto, observações)  
✅ **Sem Banco de Dados** - Dados armazenados apenas em memória, atualizados a cada carregamento  

## 📋 Requisitos

- **Python 3.8+**
- **pip** (gerenciador de pacotes Python)
- **Navegador moderno** (Chrome, Firefox, Safari, Edge)

## 🚀 Como Executar

### 1. Clonar ou Descarregar o Projeto

```bash
cd /Users/fernando.becker/Desktop/crm-calendario
```

### 2. Criar um Ambiente Virtual (Recomendado)

```bash
# Criar ambiente virtual
python3 -m venv venv

# Ativar ambiente virtual
# No macOS/Linux:
source venv/bin/activate

# No Windows:
# venv\Scripts\activate
```

### 3. Instalar Dependências

```bash
pip install -r requirements.txt
```

### 4. Executar o Servidor

```bash
python3 server.py
```

Você verá uma mensagem como:
```
INFO:     Uvicorn running on http://127.0.0.1:8000
```

### 5. Abrir no Navegador

Acesse a aplicação em seu navegador:
```
http://localhost:8000
```

## 📊 Dados do Google Sheets

A aplicação busca dados automaticamente deste CSV público:
```
https://docs.google.com/spreadsheets/d/e/2PACX-1vQaQTSv32MuaQTlGRjr9m6s5pmyK9A9iZlRTNTePX8x0G5to5j6iLSkGx89fbiQLQ/pub?output=csv
```

### Formato Esperado do CSV

O CSV deve conter as seguintes colunas:

| DATA | CAMPANHA | CANAL | PRODUTO | OBSERVACAO |
|------|----------|-------|---------|-----------|
| 14/02/2026 | Valentine Sale | Email | Roupas | Black Friday especial |
| 14/02/2026 | Love Promo | WhatsApp | Cosméticos | Acompanhar entrega |
| 15/02/2026 | Feedback Survey | SMS | Serviços | Resposta até 5 dias |

**Formatos de data suportados:**
- `DD/MM/YYYY` (14/02/2026)
- `YYYY-MM-DD` (2026-02-14)
- `DD-MM-YYYY` (14-02-2026)

## 🎨 Codificação por Canal

| Canal | Cor | Código |
|-------|-----|--------|
| 📧 Email | Azul | #0071E3 |
| 💚 WhatsApp | Verde | #25D366 |
| 📱 SMS | Laranja | #FF9F0A |

## 🏗️ Arquitetura do Projeto

```
crm-calendario/
├── server.py          # Backend FastAPI - API e roteamento
├── index.html         # Frontend HTML - Estrutura da página
├── script.js          # Lógica do calendário e interações
├── style.css          # Estilos (design Apple-like)
├── requirements.txt   # Dependências Python
└── README.md          # Esta documentação
```

### server.py
- **Função**: Servidor FastAPI que fornece a API
- **Endpoint `/api/events`**: Retorna lista de eventos em JSON
- **Função**: Busca, valida e converte CSV do Google Sheets

### index.html
- **Função**: Estrutura HTML da aplicação
- **Componentes**: 
  - Header com branding
  - Alerta de saturação
  - Calendário (container para FullCalendar)
  - Modal de detalhes de evento

### script.js
- **Função**: Lógica interativa do frontend
- **Responsabilidades**:
  - Buscar eventos da API
  - Inicializar FullCalendar
  - Detectar saturação (3+ eventos/dia)
  - Manipular modal de detalhes
  - Tratamento de erros

### style.css
- **Função**: Estilos completos da aplicação
- **Design**: Apple-inspired com variáveis CSS
- **Responsivo**: Funciona em desktop, tablet e mobile

## 🔧 Endpoints da API

### GET /api/events
Retorna todos os eventos/campanhas

**Resposta de exemplo:**
```json
{
  "events": [
    {
      "id": "14/02/2026_Valentine Sale",
      "date": "2026-02-14",
      "title": "Valentine Sale",
      "channel": "email",
      "product": "Roupas",
      "observation": "Black Friday especial",
      "raw_date": "14/02/2026"
    }
  ]
}
```

## 💻 Dependências

- **fastapi**: Framework web moderno para Python
- **uvicorn**: Servidor ASGI para FastAPI
- **requests**: Biblioteca para requisições HTTP
- **FullCalendar**: Biblioteca JavaScript para calendário

## 🎓 Uso

### Navegando no Calendário
- ⬅️ **Anterior/Próximo**: Navegue entre meses
- 📅 **Hoje**: Volta para o mês atual
- 📊 **Mês/Semana**: Alterne entre visualizações

### Interagindo com Eventos
- **Clique em um evento** para ver todos os detalhes
- **Passe o mouse** sobre um evento para ver preview
- **Atualize** clicando no botão "🔄 Atualizar"

### Entendendo os Alertas
- **⚠️ Risco de saturação**: Aparece quando há mais de 3 campanhas no mesmo dia
  - Isso indica que pode haver excesso de comunicação naquele dia
  - Considere redistribuir algumas campanhas

## 🐛 Troubleshooting

### "Erro ao buscar dados do Google Sheets"
- Verifique sua conexão com a internet
- Confirme que o link do Google Sheets está acessível
- Tente atualizar a página (🔄)

### Nenhum evento aparece
- Verifique se o CSV tem dados
- Confirme que as datas estão em um dos formatos suportados
- Abra o DevTools (F12) e verifique o Console para erros

### Servidor não inicia
```bash
# Certifique-se de estar no ambiente virtual ativado
source venv/bin/activate  # macOS/Linux

# Reinstale as dependências
pip install -r requirements.txt

# Execute novamente
python3 server.py
```

### Porta 8000 já está em uso
Você pode usar outra porta:
```bash
python3 server.py --port 8001
```

## 📱 Responsividade

A aplicação foi otimizada para:
- 🖥️ **Desktop** (1024px+)
- 💻 **Tablet** (768px - 1023px)
- 📱 **Mobile** (320px - 767px)

## 🔐 Notas de Segurança

- A aplicação é destinada para uso **interno apenas**
- Não requer autenticação por padrão
- Para ambiente de produção, considere adicionar:
  - Autenticação
  - Validação CORS restrita
  - HTTPS
  - Rate limiting

## 📝 Comentários no Código

Todo o código foi documentado com:
- Docstrings em funções
- Comentários explicativos
- Nomes de variáveis descritivos
- Organização lógica do código

## 🚀 Melhorias Futuras

- [ ] Adicionar filtros por canal
- [ ] Busca de campanhas
- [ ] Exportar calendário (iCal)
- [ ] Notificações de campanhas
- [ ] Dashboard de estatísticas
- [ ] Suporte a múltiplas planilhas

## 📞 Suporte

Para dúvidas ou problemas:
1. Verifique o console do navegador (F12 → Console)
2. Verifique os logs do servidor (terminal)
3. Confirme que todos os arquivos estão presentes
4. Tente limpar o cache (Ctrl+Shift+Del)

## 📄 Licença

Projeto desenvolvido para uso interno.

---

**Versão**: 1.0  
**Data de Criação**: Fevereiro de 2026  
**Autor**: Engenheiro de Software Senior
