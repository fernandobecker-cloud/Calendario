import streamlit as st
import pandas as pd
from streamlit_calendar import calendar

st.set_page_config(page_title="Calendário CRM", layout="wide")

# ---- ESTILO (visual Apple) ----
st.markdown("""
<style>
body { background-color: #ffffff; }

.card {
    background-color: #ffffff;
    padding: 18px;
    border-radius: 18px;
    box-shadow: 0px 4px 18px rgba(0,0,0,0.08);
    margin-bottom: 12px;
}

.titulo { font-size: 20px; font-weight: 600; }
.canal { font-size: 14px; color: #6e6e73; }
.data { font-size: 13px; color: #8e8e93; }
</style>
""", unsafe_allow_html=True)


# ---- LER PLANILHA ----
csv_url = "https://docs.google.com/spreadsheets/d/e/2PACX-1vQaQTSv32MuaQTlGRjr9m6s5pmyK9A9iZlRTNTePX8x0G5to5j6iLSkGx89fbiQLQ/pub?output=csv"
df = pd.read_csv(csv_url)


# ---- LIMPAR NOMES DAS COLUNAS (ANTI-ERRO) ----
df.columns = (
    df.columns
    .str.strip()            # remove espaços
    .str.upper()            # tudo maiúsculo
    .str.normalize('NFKD')  # remove acentos
    .str.encode('ascii', errors='ignore')
    .str.decode('utf-8')
)

# ---- CRIAR COLUNA MES AUTOMÁTICA SE NÃO EXISTIR ----
if "MES" not in df.columns and "DATA" in df.columns:
    df["DATA"] = pd.to_datetime(df["DATA"], errors="coerce")
    df["MES"] = df["DATA"].dt.month_name()

# ---- TÍTULO ----
st.title("📅 Planejamento de Campanhas CRM")


# ---- FILTRO DE MÊS ----
if "MES" in df.columns:
    meses = df["MES"].dropna().unique()
    mes_selecionado = st.selectbox("Selecione o mês", sorted(meses))
    df_filtrado = df[df["MES"] == mes_selecionado]
else:
    st.error("A planilha precisa ter uma coluna DATA ou MES")
    st.stop()


st.write("")

# ---- CRIAR EVENTOS PARA O CALENDÁRIO ----
eventos = []

def cor_por_canal(canal):
    canal = str(canal).lower()

    if "email" in canal:
        return "#0071E3"   # azul apple
    elif "whats" in canal:
        return "#25D366"   # verde whatsapp
    elif "sms" in canal:
        return "#FF9F0A"   # laranja
    else:
        return "#8E8E93"   # cinza neutro

for _, row in df_filtrado.iterrows():
    if pd.notna(row.get("DATA")):
        eventos.append({
    "title": f"{row.get('CAMPANHA','')}",
    "start": pd.to_datetime(row["DATA"]).strftime("%Y-%m-%d"),
    "color": cor_por_canal(row.get("CANAL","")),
    "allDay": True,

    # dados escondidos do evento
    "extendedProps": {
        "canal": row.get("CANAL",""),
        "produto": row.get("PRODUTO",""),
        "observacao": row.get("OBSERVACAO",""),
        "data": str(row.get("DATA",""))
    }
})
        
# ---- ALERTA DE SATURAÇÃO ----
df_datas = df_filtrado.copy()
df_datas["DATA"] = pd.to_datetime(df_datas["DATA"], errors="coerce")

contagem = df_datas.groupby(df_datas["DATA"].dt.date).size()

dias_saturados = contagem[contagem >= 3]

if len(dias_saturados) > 0:
    st.warning("⚠️ Existem dias com 3 ou mais campanhas programadas. Risco de saturação de comunicação.")
    
    for dia, qtd in dias_saturados.items():
        st.write(f"{dia.strftime('%d/%m/%Y')} — {qtd} campanhas")

st.subheader("Visão Calendário")

calendar_options = {
    "initialView": "dayGridMonth",
    "locale": "pt-br",
    "headerToolbar": {
        "left": "prev,next today",
        "center": "title",
        "right": "dayGridMonth,timeGridWeek"
    }
}

calendar(events=eventos, options=calendar_options)
