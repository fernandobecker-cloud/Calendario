"""Monta a planilha do agente de IA a partir das tabelas do comercial + export do site.

Entradas:
  --site      tabela "Promoção Novembro Site" (preço do site/televendas): SKU, PIX antes, Preço Final PIX, estoque, Nível 1
  --varejo    tabela "Listagem ... Varejo Preços" (preço de loja): SKU, Pix, 1x, 10x, 21x, Parcela 21x
  --produtos  produtos_site_iplace.json (script do navegador na aba Catálogo do Agente)
Saída:
  CSV com ; no formato do modelo do portal (sobe em "Subir planilha") + relatório no terminal.

Regras:
  - Só categorias de ticket alto (iPhone, iPad, Mac, Watch, fones, caixas de som), sem DEMO.
  - Entram os SKUs da tabela do site e, sem preço de site, os que só estão na tabela de varejo
    (item só de loja). Nos dois casos o SKU precisa estar ativo no site (nome, link, agrupamento;
    também tira itens descontinuados). Os demais vão para um CSV de "fora" para conferência.
  - Nome do produto, agrupamento (produto_id), link, imagem, cor e capacidade vêm do site.
  - Preço do site (preco_por = Pix, preco_de = Pix antes do período) e estoque vêm do comercial.
  - Preço e condição de loja vêm da tabela de varejo, quando o SKU está nela.

Uso:
  python3 ferramentas/montar_planilha_agente.py --site "...Site.csv" --varejo "...Varejo.csv" \\
      --produtos produtos_site_iplace.json --saida planilha_agente.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import unicodedata
from pathlib import Path

SITE = "https://www.iplace.com.br"
# Só itens de ticket alto (coluna Nível 1 do comercial); acessórios ficam de fora.
CATEGORIAS = ["iphone", "ipad", "mac", "watch", "fones de ouvido", "caixa de som", "caixas de som"]
COLUNAS = ["produto_id", "produto", "sku", "variante", "cor", "capacidade", "preco_de", "preco_por",
           "preco_loja", "condicao_loja", "estoque", "categoria", "link", "imagem", "ativo"]


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def _ler(caminho: str) -> list[list[str]]:
    p = Path(caminho)
    if p.suffix.lower() in (".xlsx", ".xlsm"):
        from openpyxl import load_workbook
        ws = load_workbook(p, read_only=True, data_only=True).worksheets[0]
        return [["" if v is None else str(v) for v in row] for row in ws.iter_rows(values_only=True)]
    texto = p.read_bytes().decode("utf-8-sig", errors="replace")
    sep = ";" if texto.count(";") > texto.count(",") else ","
    return list(csv.reader(texto.splitlines(), delimiter=sep))


def _tabela(caminho: str) -> list[dict[str, str]]:
    """Linhas como dicionário, achando a linha de cabeçalho (a que tem a coluna SKU)."""
    linhas = _ler(caminho)
    for i, linha in enumerate(linhas[:10]):
        nomes = [_norm(c) for c in linha]
        if any(n.startswith("sku") for n in nomes):
            return [dict(zip(nomes, [c.strip() for c in l])) for l in linhas[i + 1:] if any(c.strip() for c in l)]
    raise SystemExit(f"Não achei a coluna SKU em {caminho}")


def _col(linha: dict[str, str], *inicios: str) -> str:
    for ini in inicios:
        for k, v in linha.items():
            if k.startswith(ini):
                return v
    return ""


def _num(v: str) -> float | None:
    t = re.sub(r"[^0-9,.\-]", "", str(v or ""))
    if not t or not re.search(r"\d", t):
        return None
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", t):
        t = t.replace(".", "")
    try:
        return float(t)
    except ValueError:
        return None


def _brl(v: float) -> str:
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt(v: float | None) -> str:
    return "" if v is None else f"{v:.2f}".replace(".", ",")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", required=True)
    ap.add_argument("--varejo", required=True)
    ap.add_argument("--produtos", required=True)
    ap.add_argument("--saida", required=True)
    ap.add_argument("--sem-so-loja", action="store_true", help="não incluir itens que só estão na tabela de varejo")
    ap.add_argument("--incluir-demo", action="store_true", help="incluir aparelhos de demonstração (DEMO)")
    a = ap.parse_args()

    produtos = json.loads(Path(a.produtos).read_text(encoding="utf-8-sig"))
    por_sku: dict[str, tuple[dict, dict]] = {}
    for p in produtos:
        for s in p.get("skus") or []:
            s = s if isinstance(s, dict) else {"id": s}
            if s.get("id"):
                por_sku.setdefault(str(s["id"]).strip().upper(), (p, s))
    tem_detalhe = any(isinstance(s, dict) for p in produtos for s in p.get("skus") or [])

    varejo = {}
    for l in _tabela(a.varejo):
        sku = _col(l, "sku").upper()
        if sku:
            varejo[sku] = l

    def categoria_ok(nivel1: str) -> bool:
        n = _norm(nivel1)
        if "demo" in n.split() and not a.incluir_demo:
            return False
        return any(n == c or n.startswith(c + " ") for c in CATEGORIAS)

    def montar(sku: str, p: dict, s: dict, l_site: dict | None, l_var: dict | None) -> dict:
        cor, cap = s.get("cor") or "", s.get("capacidade") or ""
        desc_erp = _col(l_site or l_var, "descricao")
        linha = {
            "produto_id": p["id"],
            "produto": (p.get("nome") or "").strip(),
            "sku": sku,
            "variante": " ".join(x for x in (cap, cor) if x) or (s.get("nome") or "") or desc_erp,
            "cor": cor,
            "capacidade": cap,
            "preco_de": "",
            "preco_por": "",
            "preco_loja": "",
            "condicao_loja": "",
            "estoque": "",
            "categoria": _col(l_site or l_var, "nivel 1"),
            "link": (p["route"] if str(p.get("route", "")).startswith("http") else SITE + p["route"]) if p.get("route") else "",
            "imagem": s.get("imagem") or p.get("imagem") or "",
            "ativo": "S",
        }
        if l_site:
            por, antes = _num(_col(l_site, "preco final pix", "preco final")), _num(_col(l_site, "pix antes"))
            linha["preco_por"] = _fmt(por)
            linha["preco_de"] = _fmt(antes) if antes and por and antes > por else ""
            if _col(l_site, "volume estoque"):
                linha["estoque"] = str(int(_num(_col(l_site, "volume estoque")) or 0))
        if l_var and _num(_col(l_var, "pix")):
            pix, x1, x10 = _num(_col(l_var, "pix")), _num(_col(l_var, "1x")), _num(_col(l_var, "10x"))
            x21, p21 = _num(_col(l_var, "21x")), _num(_col(l_var, "parcela 21x"))
            linha["preco_loja"] = _fmt(pix)
            partes = [f"{_brl(pix)} no Pix"]
            if x1:
                partes.append(f"{_brl(x1)} à vista no cartão")
            if x10:
                partes.append(f"10x de {_brl(x10 / 10)} (total {_brl(x10)})")
            if p21 and x21:
                partes.append(f"21x de {_brl(p21)} (total {_brl(x21)})")
            linha["condicao_loja"] = "; ".join(partes)
        return linha

    site_rows = {}
    for l in _tabela(a.site):
        sku = _col(l, "sku").upper()
        if sku and sku not in site_rows and _num(_col(l, "preco final pix", "preco final")):
            site_rows[sku] = l

    saida, fora = [], []
    cont = {"site": 0, "so_loja": 0, "fora_categoria": 0, "fora_site": 0, "sem_loja": 0}
    for sku, l in site_rows.items():
        if not categoria_ok(_col(l, "nivel 1")):
            cont["fora_categoria"] += 1
            continue
        if sku not in por_sku:
            cont["fora_site"] += 1
            fora.append({"sku": sku, "descricao": _col(l, "descricao"), "motivo": "tabela do site, mas não ativo no site"})
            continue
        linha = montar(sku, *por_sku[sku], l, varejo.get(sku))
        cont["site"] += 1
        cont["sem_loja"] += 0 if linha["preco_loja"] else 1
        saida.append(linha)
    if not a.sem_so_loja:
        for sku, l in varejo.items():
            if sku in site_rows or not _num(_col(l, "pix")):
                continue
            if not categoria_ok(_col(l, "nivel 1")):
                cont["fora_categoria"] += 1
                continue
            if sku not in por_sku:
                cont["fora_site"] += 1
                fora.append({"sku": sku, "descricao": _col(l, "descricao"), "motivo": "só loja, não ativo no site"})
                continue
            saida.append(montar(sku, *por_sku[sku], None, l))
            cont["so_loja"] += 1
    # Mantém juntas as variantes do mesmo produto (site e só loja misturados).
    ordem = {}
    for i, l in enumerate(saida):
        ordem.setdefault(l["produto_id"], i)
    saida.sort(key=lambda l: ordem[l["produto_id"]])

    with open(a.saida, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUNAS, delimiter=";")
        w.writeheader()
        w.writerows(saida)
    arq_fora = Path(a.saida).with_name(Path(a.saida).stem + "_fora.csv")
    with open(arq_fora, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["sku", "descricao", "motivo"], delimiter=";")
        w.writeheader()
        w.writerows(fora)

    produtos_ok = len({l["produto_id"] for l in saida})
    print(f"Planilha do agente: {len(saida)} SKUs em {produtos_ok} produtos ({a.saida})")
    print(f"  -> com preço de site (tabela de promoção): {cont['site']} ({cont['sem_loja']} sem preço de loja)")
    print(f"  -> só loja (tabela de varejo): {cont['so_loja']}")
    print(f"  -> fora por categoria (acessórios etc.): {cont['fora_categoria']}")
    print(f"  -> fora por não estarem ativos no site: {cont['fora_site']} ({arq_fora})")
    print(f"  -> com imagem: {sum(1 for l in saida if l['imagem'])}")
    if not tem_detalhe:
        print("ATENÇÃO: o produtos_site_iplace.json é do script antigo (sem cor, capacidade e imagem dos SKUs).")
        print("         Rode o script novo do portal e gere de novo para ter variantes e imagens.")


if __name__ == "__main__":
    main()
