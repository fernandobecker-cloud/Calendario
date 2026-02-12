import streamlit as st
import pandas as pd
from streamlit_calendar import calendar

st.set_page_config(page_title="Calendário CRM", layout="wide")

# ---------------- ESTILO ----------------
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
</style>
""", unsafe_allow_html=True)

# tooltip lib
st.markdown("""
""", unsafe_allow_html=True)

# ---------------- DADOS ----------------
csv_url = "https://docs.google.com/spreadsheets/d/e/2PACX-1vQaQTSv32MuaQTlGRjr9m6s5pmyK9A9iZlRTNTePX8x0G5to5j6iLSkGx89fbiQLQ/pub?output=csv"
df = pd.read_csv(csv_url)

# limpar colunas
df.columns = (
    df.columns
    .str.strip()
    .str.upper()
    .str.normalize('NFKD')
    .str.encode('ascii', errors='ignore')
    .str.decode('utf-8')
)

# criar MES
if "MES" not in df.columns and "DATA" in df.columns:
    df["DATA"] = pd.to_datetime(df["DATA"], errors="coerce")
    df["MES"] = df["DATA"].dt.month_name()

st.title("📅 Planejamento de Campanhas CRM")

# filtro
meses = df["MES"].dropna().unique()
mes_selecionado = st.selectbox("Selecione o mês", sorted(meses))
df_filtrado = df[df["MES"] == mes_selecionado]

# alerta
df_datas = df_filtrado.copy()
df_datas["DATA"] = pd.to_datetime(df_datas["DATA"], errors="coerce")
contagem = df_datas.groupby(df_datas["DATA"].dt.date).size()
dias_saturados = contagem[contagem >= 3]

if len(dias_saturados) > 0:
    st.warning("⚠️ Existem dias com 3 ou mais campanhas programadas. Risco de saturação de comunicação.")
    for dia, qtd in dias_saturados.items():
        st.write(f"{dia.strftime('%d/%m/%Y')} — {qtd} campanhas")

# ---------------- CORES ----------------
def cor_por_canal(canal):
    canal = str(canal).lower()
    if "email" in canal:
        return "#0071E3"
    elif "whats" in canal:
        return "#25D366"
    elif "sms" in canal:
        return "#FF9F0A"
    else:
        return "#8E8E93"

# ---------------- EVENTOS ----------------
eventos = []

for _, row in df_filtrado.iterrows():
    if pd.notna(row.get("DATA")):
        eventos.append({
            "title": f"{row.get('CAMPANHA','')}",
            "start": pd.to_datetime(row["DATA"]).strftime("%Y-%m-%d"),
            "color": cor_por_canal(row.get("CANAL","")),
            "allDay": True,
            "extendedProps": {
                "canal": row.get("CANAL",""),
                "produto": row.get("PRODUTO",""),
                "observacao": row.get("OBSERVACAO",""),
                "data": str(row.get("DATA",""))
            }
        })

# ---------------- CALENDARIO ----------------
st.subheader("Visão Calendário")

calendar_options = {
    "initialView": "dayGridMonth",
    "locale": "pt-br",
    "dayMaxEventRows": 3,

    "eventContent": """
    function(arg) {

        let canal = arg.event.extendedProps.canal || '';
        let produto = arg.event.extendedProps.produto || '';
        let obs = arg.event.extendedProps.observacao || '';

        let cor = arg.event.backgroundColor;

        let container = document.createElement("div");
        container.style.padding = "4px 6px";
        container.style.borderRadius = "8px";
        container.style.fontSize = "11px";
        container.style.lineHeight = "1.2";
        container.style.color = "white";
        container.style.background = cor;

        container.innerHTML = `
            <div style="font-weight:600">${arg.event.title}</div>
            <div style="opacity:0.85">${canal}</div>
            <div style="opacity:0.75">${produto}</div>
        `;

        return { domNodes: [container] };
    }
    """,

    "headerToolbar": {
        "left": "prev,next today",
        "center": "title",
        "right": "dayGridMonth,timeGridWeek"
    }
}

calendar(events=eventos, options=calendar_options)
