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
<link rel="stylesheet" href="https://unpkg.com/tippy.js@6/themes/light-border.css">
<script src="https://unpkg.com/@popperjs/core@2"></script>
<script src="https://unpkg.com/tippy.js@6"></script>
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
    "eventDidMount": """
    function(info) {
        let props = info.event.extendedProps;

        let tooltip = `
        <div style="padding:12px;border-radius:12px;background:white;box-shadow:0 8px 30px rgba(0,0,0,0.15);font-size:13px;line-height:1.5;">
            <b>${info.event.title}</b><br>
            <b>Canal:</b> ${props.canal || '-'}<br>
            <b>Produto:</b> ${props.produto || '-'}<br>
            <b>Data:</b> ${props.data || '-'}<br>
            <b>Obs:</b> ${props.observacao || '-'}
        </div>
        `;

        tippy(info.el, {
            content: tooltip,
            allowHTML: true,
            placement: 'top',
            animation: 'scale',
            theme: 'light-border',
        });
    }
    """,
    "headerToolbar": {
        "left": "prev,next today",
        "center": "title",
        "right": "dayGridMonth,timeGridWeek"
    }
}

calendar(events=eventos, options=calendar_options)
