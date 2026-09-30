"""Gera o PDF do certificado de garantia estendida, pra o SAC baixar e
mandar pro cliente quando o e-mail original (ver `campaign_source.html`,
template Emarsys) nao chegou.

Recriado com reportlab (100% Python, sem depender de bibliotecas de
sistema como Pango/Cairo) em vez de converter o HTML do e-mail direto -
decisao tomada com o usuario: o Render (plano gratuito, sem Docker) nao
garante essas bibliotecas nativas, e reportlab funciona com um simples
`pip install`. O resultado fica visualmente parecido (selo, cores, cartao
de dados, cobertura em 3 faixas) mas nao e copia pixel a pixel do e-mail.
"""

from __future__ import annotations

from datetime import date, datetime
from io import BytesIO
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

_AZUL = colors.HexColor("#0071e3")
_ESCURO = colors.HexColor("#1d1d1f")
_CINZA = colors.HexColor("#86868b")
_CINZA_TEXTO = colors.HexColor("#424245")
_CINZA_CLARO = colors.HexColor("#f6f6f6")
_VERDE_MARCA = colors.HexColor("#c8d400")
_VERMELHO = colors.HexColor("#d13c3c")
_FAIXA_CDC = colors.HexColor("#d2d2d7")
_FAIXA_APPLE = colors.HexColor("#a1a1a6")
_FAIXA_IPLACE = _AZUL


def _como_date(valor: Any) -> date | None:
    if not valor:
        return None
    if isinstance(valor, str):
        try:
            valor = datetime.fromisoformat(valor.replace("Z", "+00:00"))
        except ValueError:
            return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    return None


def _formatar_data(valor: Any) -> str:
    d = _como_date(valor)
    return d.strftime("%d/%m/%Y") if d else "-"


def _campo(rotulo: str, valor: str, estilo: ParagraphStyle) -> Paragraph:
    texto = (
        f'<font size="8" color="#86868b"><b>{rotulo}</b></font><br/>'
        f'<font size="12" color="#1d1d1f"><b>{valor}</b></font>'
    )
    return Paragraph(texto, estilo)


def gerar_certificado_pdf(item: dict[str, Any]) -> bytes:
    """Recebe um registro da tabela garantia_estendida (mesmos campos que
    GET /comercial/garantia-estendida devolve) e gera o PDF em bytes."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        leftMargin=24 * mm,
        rightMargin=24 * mm,
    )

    base = ParagraphStyle("base", fontName="Helvetica", fontSize=9.5, textColor=_CINZA_TEXTO, leading=14)
    marca = ParagraphStyle("marca", fontName="Helvetica-Bold", fontSize=14, textColor=_ESCURO, alignment=TA_CENTER)
    tag = ParagraphStyle("tag", fontName="Helvetica-Bold", fontSize=10, textColor=_CINZA, alignment=TA_CENTER, spaceBefore=6, spaceAfter=2)
    headline = ParagraphStyle("headline", fontName="Helvetica-Bold", fontSize=22, textColor=_ESCURO, alignment=TA_CENTER, spaceAfter=10)
    campo_estilo = ParagraphStyle("campo", parent=base, spaceAfter=4)
    secao_titulo = ParagraphStyle("secao_titulo", fontName="Helvetica-Bold", fontSize=11, textColor=_ESCURO, spaceAfter=4, spaceBefore=8)
    legal = ParagraphStyle("legal", fontName="Helvetica", fontSize=7.5, textColor=_CINZA, alignment=TA_CENTER, leading=10, spaceBefore=8)
    contato_titulo = ParagraphStyle("contato_titulo", fontName="Helvetica-Bold", fontSize=9, textColor=_ESCURO, alignment=TA_CENTER, spaceAfter=6)
    contato_texto = ParagraphStyle("contato_texto", fontName="Helvetica", fontSize=9, textColor=_CINZA_TEXTO, alignment=TA_CENTER, leading=13)

    nome = str(item.get("ge_Nome") or "-")
    produto = str(item.get("ge_produto") or "-")
    serial = str(item.get("ge_serial") or "-")
    imei = str(item.get("GE_IMEI") or "-")
    contrato = str(item.get("ge_contrato") or "-")
    data_compra = _formatar_data(item.get("ge_data_venda"))
    validade_date = _como_date(item.get("ge_data_validade"))
    validade_str = _formatar_data(item.get("ge_data_validade"))
    ativa = validade_date is None or validade_date >= date.today()

    elementos: list[Any] = []

    elementos.append(HRFlowable(width="100%", thickness=3, color=_VERDE_MARCA, spaceAfter=16))
    elementos.append(Paragraph("iPlace", marca))
    elementos.append(Paragraph("Apple Premium Reseller", ParagraphStyle("sub", fontName="Helvetica", fontSize=9, textColor=_CINZA, alignment=TA_CENTER, spaceAfter=4)))

    elementos.append(Paragraph("CERTIFICADO DE GARANTIA ESTENDIDA", tag))
    elementos.append(Paragraph("+12 meses de cobertura", headline))

    dados_tabela = [
        [_campo("CLIENTE", nome, campo_estilo), _campo("PRODUTO", produto, campo_estilo)],
        [_campo("Nº DE SÉRIE / IMEI", f"{serial} / {imei}", campo_estilo), _campo("DATA DA COMPRA", data_compra, campo_estilo)],
        [_campo("COBERTURA VÁLIDA ATÉ", f"{validade_str} (24 meses após a compra)", campo_estilo), _campo("Nº DO CERTIFICADO", contrato, campo_estilo)],
    ]
    tabela = Table(dados_tabela, colWidths=[80 * mm, 80 * mm])
    tabela.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#e5e5e5")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e5e5e5")),
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("TOPPADDING", (0, 0), (-1, -1), 12),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
        ("LEFTPADDING", (0, 0), (-1, -1), 14),
        ("RIGHTPADDING", (0, 0), (-1, -1), 14),
    ]))
    elementos.append(tabela)
    elementos.append(Spacer(1, 6))

    cor_status = colors.HexColor("#0a8a3f") if ativa else _VERMELHO
    texto_status = "✓ Garantia ativa" if ativa else "Garantia expirada"
    selo_status = Table([[Paragraph(f'<font color="#ffffff"><b>{texto_status}</b></font>', ParagraphStyle("selo", fontName="Helvetica-Bold", fontSize=9, alignment=TA_CENTER))]], colWidths=[45 * mm])
    selo_status.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), cor_status),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
    ]))
    envolucro_status = Table([[selo_status]], colWidths=[160 * mm])
    envolucro_status.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER")]))
    elementos.append(envolucro_status)

    elementos.append(Paragraph("Sua garantia soma 24 meses de cobertura", secao_titulo))
    barra = Table([[""] * 3], colWidths=[20 * mm, 60 * mm, 80 * mm], rowHeights=[6])
    barra.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), _FAIXA_CDC),
        ("BACKGROUND", (1, 0), (1, 0), _FAIXA_APPLE),
        ("BACKGROUND", (2, 0), (2, 0), _FAIXA_IPLACE),
    ]))
    elementos.append(barra)
    elementos.append(Spacer(1, 5))
    legenda = (
        '<font color="#424245">'
        '<b>3 meses</b> de garantia legal (CDC) &nbsp;•&nbsp; '
        '<b>9 meses</b> de garantia adicional Apple &nbsp;•&nbsp; '
        '<b>12 meses</b> de garantia extra iPlace'
        '</font>'
    )
    elementos.append(Paragraph(legenda, ParagraphStyle("legenda", parent=base, alignment=TA_CENTER)))

    elementos.append(Paragraph("Diferenciais da Garantia Estendida", secao_titulo))
    elementos.append(Paragraph(
        "✓ Proteção contra defeitos funcionais de origem mecânica, elétrica ou eletrônica<br/>"
        "✓ Atendimento na Assistência Técnica iPlace ou em rede credenciada<br/>"
        "✓ Sem carência nem franquia<br/>"
        "✓ Peças originais Apple e mão de obra especializada",
        base,
    ))

    elementos.append(Paragraph("Não contempla", secao_titulo))
    elementos.append(Paragraph(
        "✗ Danos acidentais (telas quebradas, quedas, líquidos ou esmagamentos)<br/>"
        "✗ Desgaste natural de consumíveis, como baterias (salvo defeito de material)<br/>"
        "✗ Riscos, amassados ou danos estéticos que não afetem o funcionamento<br/>"
        "✗ Danos por componentes de terceiros ou softwares não oficiais<br/>"
        "✗ Modificações ou serviços por assistências não autorizadas<br/>"
        "✗ Roubo ou furto do aparelho",
        base,
    ))

    caixa_contato = Table([[
        Paragraph(
            "CONTATOS DO SEGURO (HERVAL SEGURADORA)".upper(),
            contato_titulo,
        )
    ], [
        Paragraph(
            "SAC: <b>0800-7992515</b> ou <b>contato@hervalseguradora.com.br</b><br/>"
            "Acionamento: <b>www.hervalseguradora.com.br</b> ou WhatsApp <b>(51) 99799-2515</b>",
            contato_texto,
        )
    ]], colWidths=[160 * mm])
    caixa_contato.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _CINZA_CLARO),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING", (0, 0), (-1, -1), 14),
        ("RIGHTPADDING", (0, 0), (-1, -1), 14),
    ]))
    elementos.append(Spacer(1, 8))
    elementos.append(caixa_contato)

    elementos.append(Paragraph(
        "<b>Termos da Garantia Estendida iPlace:</b> serviço fornecido em parceria com a Herval Seguradora "
        "para compras de iPhone novo realizadas em lojas físicas ou no site oficial iPlace, ativado "
        "automaticamente e sem custo adicional. Cobre defeitos funcionais de origem mecânica, elétrica ou "
        "eletrônica, sem carência nem franquia, com peças originais Apple e mão de obra especializada. Não "
        "contempla danos acidentais, desgaste natural de consumíveis, danos estéticos que não afetem o "
        "funcionamento, uso de componentes ou softwares não oficiais, modificações ou serviços por "
        "assistências não autorizadas, nem roubo ou furto do aparelho. Vinculada ao número de série do "
        "aparelho e à nota fiscal de compra. Em caso de dúvidas, fale com o nosso SAC.",
        legal,
    ))

    elementos.append(Paragraph(
        "iPlace é uma empresa do Grupo Herval — CNPJ: 89.237.911/0001-40<br/>"
        "atendimento@iplace.com.br · www.iplace.com.br",
        ParagraphStyle("rodape", fontName="Helvetica", fontSize=7.5, textColor=_CINZA, alignment=TA_CENTER, leading=11, spaceBefore=6),
    ))

    doc.build(elementos)
    return buffer.getvalue()
