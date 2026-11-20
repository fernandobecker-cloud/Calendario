"""Monta a planilha do agente de IA a partir das tabelas do comercial + export do site.

Entradas:
  --site      tabela "Promoção Novembro Site" (preço do site/televendas): SKU, PIX antes, Preço Final PIX, estoque, Nível 1
  --varejo    tabela "Listagem ... Varejo Preços" (preço de loja): SKU, Pix, 1x, 10x, 21x, Parcela 21x
  --produtos  produtos_site_iplace.json (script do navegador na aba Catálogo do Agente)
Saída:
  CSV com ; no formato do modelo do portal (sobe em "Subir planilha") + relatório no terminal.

Regras:
  - Entram só os SKUs da tabela do site que existem ativos no site (sem isso não há link nem
    página para o cliente comprar). Os demais vão para um CSV de "fora" para conferência.
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

    saida, fora, sem_loja, avisos = [], [], 0, []
    vistos = set()
    for l in _tabela(a.site):
        sku = _col(l, "sku").upper()
        if not sku or sku in vistos:
            continue
        vistos.add(sku)
        por = _num(_col(l, "preco final pix", "preco final"))
        if por is None:
            avisos.append(f"{sku}: sem Preço Final PIX, ficou de fora")
            continue
        if sku not in por_sku:
            fora.append({"sku": sku, "descricao": _col(l, "descricao"), "motivo": "não está ativo no site"})
            continue
        p, s = por_sku[sku]
        antes = _num(_col(l, "pix antes"))
        cor, cap = s.get("cor") or "", s.get("capacidade") or ""
        variante = " ".join(x for x in (cap, cor) if x) or (s.get("nome") or "") or _col(l, "descricao")
        linha = {
            "produto_id": p["id"],
            "produto": (p.get("nome") or "").strip(),
            "sku": sku,
            "variante": variante,
            "cor": cor,
            "capacidade": cap,
            "preco_de": _fmt(antes) if antes and antes > por else "",
            "preco_por": _fmt(por),
            "preco_loja": "",
            "condicao_loja": "",
            "estoque": str(int(_num(_col(l, "volume estoque")) or 0)) if _col(l, "volume estoque") else "",
            "categoria": _col(l, "nivel 1"),
            "link": (p["route"] if str(p.get("route", "")).startswith("http") else SITE + p["route"]) if p.get("route") else "",
            "imagem": s.get("imagem") or p.get("imagem") or "",
            "ativo": "S",
        }
        v = varejo.get(sku)
        if v and _num(_col(v, "pix")):
            pix, x1, x10 = _num(_col(v, "pix")), _num(_col(v, "1x")), _num(_col(v, "10x"))
            x21, p21 = _num(_col(v, "21x")), _num(_col(v, "parcela 21x"))
            linha["preco_loja"] = _fmt(pix)
            partes = [f"{_brl(pix)} no Pix"]
            if x1:
                partes.append(f"{_brl(x1)} à vista no cartão")
            if x10:
                partes.append(f"10x de {_brl(x10 / 10)} (total {_brl(x10)})")
            if p21 and x21:
                partes.append(f"21x de {_brl(p21)} (total {_brl(x21)})")
            linha["condicao_loja"] = "; ".join(partes)
        else:
            sem_loja += 1
        saida.append(linha)

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
    print(f"Tabela do site: {len(vistos)} SKUs")
    print(f"  -> na planilha do agente: {len(saida)} SKUs em {produtos_ok} produtos ({a.saida})")
    print(f"  -> fora (não ativos no site): {len(fora)} ({arq_fora})")
    print(f"  -> com preço de loja: {len(saida) - sem_loja}; sem preço de loja: {sem_loja}")
    print(f"  -> com preço 'de' (riscado): {sum(1 for l in saida if l['preco_de'])}")
    print(f"  -> com imagem: {sum(1 for l in saida if l['imagem'])}")
    if not tem_detalhe:
        print("ATENÇÃO: o produtos_site_iplace.json é do script antigo (sem cor, capacidade e imagem dos SKUs).")
        print("         Rode o script novo do portal e gere de novo para ter variantes e imagens.")
    for av in avisos[:10]:
        print("  aviso:", av)


if __name__ == "__main__":
    main()
