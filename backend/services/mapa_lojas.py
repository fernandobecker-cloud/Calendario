"""Le backend/data/mapeamento_lojas_sap.csv (gerado a partir da planilha
"Filiais e numero sap iPlace lojas.xlsx" que a iPlace forneceu) e calcula,
a partir do numero da FILIAL (o mesmo numero usado em
gerente829@iplace.com.br), o CENTRO SAP correspondente e os nomes
esperados dos segmentos no Emarsys.

Portado do script standalone `mapa_lojas.py` (validado contra a planilha
oficial, 89 de 108 linhas).

Padrao descoberto nas telas do Emarsys:
    FILIAL 829  ->  CENTRO SAP "LJ188"  ->  numero SAP "188"
    Segmento base:      Base_LJ{filial}-SAP{sap_numero}   ex: Base_LJ829-SAP188
    Segmento combinado: NPI_LJ{filial}-SAP{sap_numero}    ex: NPI_LJ829-SAP188

Ou seja, o "LJ829" no nome do segmento usa o numero da FILIAL, e o
"SAP188" usa o numero que vem depois do "LJ" na coluna CENTRO SAP da
planilha (que por sua vez e um numero totalmente diferente do numero da
FILIAL).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent  # backend/
MAPA_PATH = BASE_DIR / "data" / "mapeamento_lojas_sap.csv"


@dataclass
class Loja:
    filial: str
    centro_sap: str
    sap_numero: str
    descricao: str = ""
    regional: str = ""
    gerente_regional: str = ""
    # ID numerico do segmento combinado (NPI_LJ...) no Emarsys, se ja
    # descoberto manualmente - GET /filter (lista, usado pra buscar por
    # nome) da 403 nesta conta mesmo com a permissao "segment.list" ativa;
    # GET /filter/{id} direto funciona. Preencher essa coluna no CSV
    # (opcional) evita depender da busca por nome, que hoje nao funciona.
    segmento_combinado_id: str = ""

    @property
    def nome_segmento_base(self) -> str:
        return f"Base_LJ{self.filial}-SAP{self.sap_numero}"

    @property
    def nome_segmento_combinado(self) -> str:
        return f"NPI_LJ{self.filial}-SAP{self.sap_numero}"

    @property
    def email_gerente(self) -> str:
        return f"gerente{self.filial}@iplace.com.br"

    @property
    def email_subgerente(self) -> str:
        return f"subgerente{self.filial}@iplace.com.br"


_mapa_cache: dict[str, Loja] | None = None


def carregar_mapa(caminho: Path = MAPA_PATH, *, force_reload: bool = False) -> dict[str, Loja]:
    global _mapa_cache
    if _mapa_cache is not None and not force_reload:
        return _mapa_cache

    if not caminho.exists():
        raise RuntimeError(
            f"Nao encontrei {caminho.name}. Deveria estar em backend/data/ e ir junto no deploy."
        )
    mapa: dict[str, Loja] = {}
    with open(caminho, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            filial = row["filial"].strip()
            mapa[filial] = Loja(
                filial=filial,
                centro_sap=row["centro_sap"].strip(),
                sap_numero=row["sap_numero"].strip(),
                descricao=row.get("descricao", "").strip(),
                regional=row.get("regional", "").strip(),
                gerente_regional=row.get("gerente_regional", "").strip(),
                segmento_combinado_id=(row.get("segmento_combinado_id") or "").strip(),
            )
    _mapa_cache = mapa
    return mapa


def obter_loja(filial: str, mapa: dict[str, Loja] | None = None) -> Loja:
    mapa = mapa if mapa is not None else carregar_mapa()
    filial = str(filial).strip()
    if filial not in mapa:
        raise KeyError(
            f"FILIAL '{filial}' nao encontrada em {MAPA_PATH.name}. "
            f"Confira se o numero esta certo ou se essa loja falta no mapeamento."
        )
    return mapa[filial]
