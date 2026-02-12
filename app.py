import streamlit as st
import pandas as pd

# CONFIGURAÇÃO DA PÁGINA
st.set_page_config(
    page_title="Calendário CRM",
    layout="wide"
)

# CSS - estilo Apple
st.markdown("""
<style>
body {
    background-color: #ffffff;
}

.card {
    background-color: #ffffff;
    padding: 18px;
    border-radius: 18px;
    box-shadow: 0px 4px 18px rgba(0,0,0,0.08);
    margin-bottom: 12px;
}

.titulo {
    font-size: 20px;
    font-weight: 600;
}

.canal {
    font-size: 14px;
    color: #6e6e73;
}

.data {
    font-size: 13px;
    color: #8e8e93;
}
</style>
""", unsafe_allow_html=True)

# LENDO GOOGLE SHEETS
csv_url = "https://docs.google.com/spreadsheets/d/e/2PACX-1vQaQTSv32MuaQTlGRjr9m6s5pmyK9A9iZlRTNTePX8x0G5to5j6iLSkGx89fbiQLQ/pub?output=csv"

df = pd.read_csv(csv_url)

st.title("📅 Planejamento de Campanhas CRM")

# FILTRO DE MÊS
meses = df["MES"].dropna().unique()
mes_selecionado = st.selectbox("Selecione o mês", sorted(meses))

df_filtrado = df[df["MES"] == mes_selecionado]

st.write("")

# EXIBIÇÃO DOS CARDS
for index, row in df_filtrado.iterrows():
    st.markdown(f"""
    <div class="card">
        <div class="titulo">{row['CAMPANHA']}</div>
        <div class="canal">Canal: {row['CANAL']}</div>
        <div class="data">Data: {row['DATA']}</div>
        <div class="data">Produto: {row['PRODUTO']}</div>
    </div>
    """, unsafe_allow_html=True)
