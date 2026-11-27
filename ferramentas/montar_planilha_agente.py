"""Monta a planilha do agente de IA a partir das tabelas do comercial + export do site.

Entradas:
  --site      tabela "Promoção Novembro Site" (preço do site/televendas): SKU, PIX antes, Preço Final PIX, estoque, Nível 1
  --varejo    tabela "Listagem ... Varejo Preços" (preço de loja): SKU, Pix, 1x, 10x, 21x, Parcela 21x
  --produtos  produtos_site_iplace.json (script do navegador na aba Catálogo do Agente)
Saída:
  CSV com ; no formato do modelo do portal (sobe em "Subir planilha") + relatório no terminal.

Regras:
  - Só categorias de ticket alto (iPhone, iPad, Mac, Watch, fones, caixas de som), com DEMO.
  - Entram os SKUs da tabela do site e, sem preço de site, os que só estão na tabela de varejo
    (item só de loja). Item que não está ativo no site entra como só loja, com a descrição do
    comercial como nome e sem link. Sem preço nenhum vai para o CSV de "fora".
  - Nome do produto, agrupamento (produto_id), link, imagem, cor e capacidade vêm do site.
  - Preço do site (preco_por = Pix, preco_de = Pix antes do período, preco_cartao = coluna 10x)
    e estoque vêm do comercial.
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
# Só loja SEM página no site abaixo deste preço (Pix) é cadastro antigo com preço simbólico
# (ex.: iPhone 6S a R$ 51,92): fica de fora para o agente não oferecer.
PISO_FORA_SITE = {"iphone": 1000, "ipad": 800, "mac": 1500, "watch": 600}
TEXTO_DEMO = (
    "APARELHO DE DEMONSTRAÇÃO (usado na vitrine da loja), vendido somente na loja física, com preço "
    "menor por ser de demonstração. Ofereça só se o cliente pedir uma opção mais barata ou perguntar "
    "por demonstração/vitrine. Sempre que citar este item, deixe claro que é aparelho de demonstração, "
    "não um aparelho novo. Nunca apresente como versão ou cor diferente do produto novo."
)
COLUNAS = ["produto_id", "produto", "sku", "variante", "cor", "capacidade", "preco_de", "preco_por",
           "preco_cartao", "preco_loja", "condicao_loja", "estoque", "categoria", "link", "imagem", "descricao", "ativo"]


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


_CORES = {"black": "preto", "white": "branco", "blue": "azul", "green": "verde", "pink": "rosa",
          "yellow": "amarelo", "purple": "roxo", "red": "vermelho", "product red": "vermelho",
          "midnight": "meia noite", "starlight": "estelar", "ultramarine": "ultramarino", "teal": "verde acinzentado"}


def _cor(t: str) -> str:
    n = _norm(t)
    return _CORES.get(n, n)


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
    ap.add_argument("--sem-demo", action="store_true", help="tirar os aparelhos de demonstração (DEMO)")
    a = ap.parse_args()

    produtos = json.loads(Path(a.produtos).read_text(encoding="utf-8-sig"))
    por_sku: dict[str, tuple[dict, dict]] = {}
    for p in produtos:
        for s in p.get("skus") or []:
            s = s if isinstance(s, dict) else {"id": s}
            if s.get("id"):
                por_sku.setdefault(str(s["id"]).strip().upper(), (p, s))
    tem_detalhe = any(isinstance(s, dict) for p in produtos for s in p.get("skus") or [])
    # Páginas antigas do site (ex.: iPhone 15) usam códigos próprios nos SKUs (227963) e não o
    # código do comercial (100031967). Para iPhone, cruza também por modelo + capacidade + cor.
    por_modelo: dict[tuple[str, str, str], tuple[dict, dict]] = {}
    for p in produtos:
        nome = _norm(p.get("nome")).removeprefix("apple ")
        if not re.fullmatch(r"iphone [0-9a-z ]+", nome) or len(nome.split()) > 4:
            continue
        for s in p.get("skus") or []:
            if isinstance(s, dict) and s.get("capacidade") and s.get("cor"):
                por_modelo.setdefault((nome, _norm(s["capacidade"]).replace(" ", ""), _cor(s["cor"])), (p, s))

    def no_site(sku: str, desc: str, por_modelo_ok: bool = True) -> tuple[dict, dict] | None:
        """Página do SKU no site. O cruzamento por modelo/cor vale só para itens da tabela do site
        (os de loja duplicariam a variante) e nunca para aparelho de demonstração."""
        if sku in por_sku:
            return por_sku[sku]
        if not por_modelo_ok or re.search(r"\b(dm|demo)\b", _norm(desc)):
            return None
        m = re.match(r"iphone (.+?) ([a-z ]+?) (\d+(?:gb|tb))\b", _norm(desc))
        if not m:
            return None
        return por_modelo.get((f"iphone {m.group(1)}", m.group(3), _cor(m.group(2))))

    varejo = {}
    for l in _tabela(a.varejo):
        sku = _col(l, "sku").upper()
        if sku:
            varejo[sku] = l

    def categoria_ok(nivel1: str) -> bool:
        n = _norm(nivel1)
        if "demo" in n.split() and a.sem_demo:
            return False
        return any(n == c or n.startswith(c + " ") for c in CATEGORIAS)

    def montar(sku: str, p: dict | None, s: dict | None, l_site: dict | None, l_var: dict | None) -> dict:
        """p/s = produto e SKU no site; None quando o item não está no site (só loja):
        aí vale a descrição do comercial, sem link nem imagem."""
        p, s = p or {}, s or {}
        cor, cap = s.get("cor") or "", s.get("capacidade") or ""
        desc_erp = _col(l_site or l_var, "descricao")
        linha = {
            "produto_id": p.get("id", ""),
            "produto": (p.get("nome") or "").strip() or desc_erp,
            "sku": sku,
            "variante": (" ".join(x for x in (cap, cor) if x) or (s.get("nome") or "") or desc_erp) if p else "",
            "cor": cor,
            "capacidade": cap,
            "preco_de": "",
            "preco_por": "",
            "preco_cartao": "",
            "preco_loja": "",
            "condicao_loja": "",
            "estoque": "",
            "categoria": _col(l_site or l_var, "nivel 1"),
            "link": (p["route"] if str(p.get("route", "")).startswith("http") else SITE + p["route"]) if p.get("route") else "",
            "imagem": s.get("imagem") or p.get("imagem") or "",
            "descricao": "",
            "ativo": "S",
            "_nome_sku": (s.get("nome") or "").strip(),
        }
        # Demonstração: categoria DEMO ou "DM"/"DEMO" na descrição do comercial.
        if "demo" in _norm(linha["categoria"]).split() or re.search(r"\b(dm|demo)\b", _norm(desc_erp)):
            linha["produto"] = f"{linha['produto']} (DEMONSTRAÇÃO - VITRINE)"
            linha["descricao"] = TEXTO_DEMO
        if l_site:
            por, antes = _num(_col(l_site, "preco final pix", "preco final")), _num(_col(l_site, "pix antes"))
            linha["preco_por"] = _fmt(por)
            linha["preco_de"] = _fmt(antes) if antes and por and antes > por else ""
            # Coluna 10x do comercial = preço no cartão (base do 21x a 1,05% a.m.).
            # Sem ela, o agente usa Pix / 0,9, que difere alguns centavos em parte dos SKUs.
            cartao = _num(_col(l_site, "10x"))
            linha["preco_cartao"] = _fmt(cartao) if cartao and por and cartao >= por else ""
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

    def preco_simbolico(l_var: dict) -> bool:
        n = _norm(_col(l_var, "nivel 1")).split()
        piso = PISO_FORA_SITE.get(n[0]) if n else None
        return piso is not None and (_num(_col(l_var, "pix")) or 0) < piso

    saida, fora = [], []
    cont = {"site": 0, "so_loja": 0, "so_loja_fora_site": 0, "fora_categoria": 0, "fora_site": 0, "sem_loja": 0, "simbolico": 0}
    for sku, l in site_rows.items():
        if not categoria_ok(_col(l, "nivel 1")):
            cont["fora_categoria"] += 1
            continue
        pagina = no_site(sku, _col(l, "descricao"))
        if not pagina:
            # Não dá para vender no site: se tiver preço de loja, entra como só loja.
            l_var = varejo.get(sku)
            if l_var and _num(_col(l_var, "pix")) and preco_simbolico(l_var):
                cont["simbolico"] += 1
                fora.append({"sku": sku, "descricao": _col(l, "descricao"),
                             "motivo": "só loja sem página no site, preço simbólico (cadastro antigo)"})
            elif l_var and _num(_col(l_var, "pix")):
                saida.append(montar(sku, None, None, None, l_var))
                cont["so_loja_fora_site"] += 1
            else:
                cont["fora_site"] += 1
                fora.append({"sku": sku, "descricao": _col(l, "descricao"),
                             "motivo": "tabela do site, não ativo no site e sem preço de loja"})
            continue
        linha = montar(sku, *pagina, l, varejo.get(sku))
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
            pagina = no_site(sku, _col(l, "descricao"), por_modelo_ok=False)
            if not pagina:
                if preco_simbolico(l):
                    cont["simbolico"] += 1
                    fora.append({"sku": sku, "descricao": _col(l, "descricao"),
                                 "motivo": "só loja sem página no site, preço simbólico (cadastro antigo)"})
                    continue
                saida.append(montar(sku, None, None, None, l))
                cont["so_loja_fora_site"] += 1
                continue
            saida.append(montar(sku, *pagina, None, l))
            cont["so_loja"] += 1
    # Cor + capacidade nem sempre separam as variantes (Watch: tamanho e pulseira).
    # Se repetir dentro do produto, usa o nome completo do SKU no site.
    por_produto: dict[str, list[dict]] = {}
    for l in saida:
        if l["produto_id"]:
            por_produto.setdefault(l["produto_id"], []).append(l)
    for linhas_p in por_produto.values():
        nomes = [l["variante"] for l in linhas_p]
        if len(set(nomes)) < len(nomes):
            for l in linhas_p:
                l["variante"] = l["_nome_sku"] or l["variante"]
    for l in saida:
        l.pop("_nome_sku", None)
    # Mantém juntas as variantes do mesmo produto (site e só loja misturados).
    ordem = {}
    for i, l in enumerate(saida):
        ordem.setdefault(l["produto_id"] or l["sku"], i)
    saida.sort(key=lambda l: ordem[l["produto_id"] or l["sku"]])

    with open(a.saida, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUNAS, delimiter=";")
        w.writeheader()
        w.writerows(saida)
    arq_fora = Path(a.saida).with_name(Path(a.saida).stem + "_fora.csv")
    with open(arq_fora, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["sku", "descricao", "motivo"], delimiter=";")
        w.writeheader()
        w.writerows(fora)

    produtos_ok = len({l["produto_id"] or l["sku"] for l in saida})
    print(f"Planilha do agente: {len(saida)} SKUs em {produtos_ok} produtos ({a.saida})")
    print(f"  -> com preço de site (tabela de promoção): {cont['site']} ({cont['sem_loja']} sem preço de loja)")
    print(f"  -> só loja, com página no site: {cont['so_loja']}")
    print(f"  -> só loja, sem página no site (nome do comercial, sem link): {cont['so_loja_fora_site']}")
    print(f"  -> DEMO: {sum(1 for l in saida if 'demo' in _norm(l['categoria']).split())}")
    print(f"  -> fora por categoria (acessórios etc.): {cont['fora_categoria']}")
    print(f"  -> fora por não estarem ativos no site: {cont['fora_site']} ({arq_fora})")
    print(f"  -> fora por preço simbólico (cadastro antigo sem página no site): {cont['simbolico']}")
    print(f"  -> com imagem: {sum(1 for l in saida if l['imagem'])}")
    if not tem_detalhe:
        print("ATENÇÃO: o produtos_site_iplace.json é do script antigo (sem cor, capacidade e imagem dos SKUs).")
        print("         Rode o script novo do portal e gere de novo para ter variantes e imagens.")


if __name__ == "__main__":
    main()
