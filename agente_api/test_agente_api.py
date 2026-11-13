"""Testes do servico do agente (sem rede). Rodar:
    python -m unittest agente_api.test_agente_api -v
"""

import os
import unittest

os.environ.setdefault("AGENTE_API_TOKEN", "segredo-teste")

from fastapi import HTTPException  # noqa: E402

from agente_api import conversao, main, oracle  # noqa: E402


class RegrasDePagamento(unittest.TestCase):
    # Valores copiados das paginas do site em 13/11/2026: (preco de venda, Pix, parcela em 21x).
    CASOS_DO_SITE = [
        (10921.11, 9829.00, 582.20),   # iPhone 17 Pro Max 512GB
        (2587.78, 2329.00, 137.95),    # Apple Watch SE
        (2643.33, 2379.00, 140.91),    # AirPods Pro 3
        (14865.56, 13379.00, 792.48),  # MacBook Air 13 M5
    ]

    def test_bate_com_o_site(self):
        for venda, pix, parcela in self.CASOS_DO_SITE:
            cartao, opcao_pix = conversao.opcoes_de_pagamento(venda)
            self.assertEqual(opcao_pix["oneTimePayment"], pix, venda)
            self.assertEqual(cartao["maxInstallments"], 21)
            self.assertEqual(cartao["installmentPrice"], parcela, venda)
            self.assertEqual(cartao["oneTimePayment"], venda)


PRODUTO = {
    "id": "100544PR",
    "displayName": "iPhone 17 Pro Max",
    "route": "/apple-iphone-17-pro-max/100544PR",
    "primaryFullImageURL": "/ccstore/v1/images/?source=/file/x.jpg",
    "x_caracteristicasHtml": "<style>.a{color:red}</style><h3>Descrição</h3><ul><li>O iPhone mais potente<sup>1</sup></li></ul>"
                             "<h3>Avisos legais</h3><ul><li>nota longa</li></ul>",
    "childSKUs": [
        {"repositoryId": "A", "displayName": "256GB Laranja", "listPrice": 12499.0, "salePrice": 9732.22,
         "x_cor": "Laranja", "x_capacidade": "256GB", "active": True},
        {"repositoryId": "B", "displayName": "256GB Prata", "listPrice": 12499.0, "salePrice": 9732.22,
         "x_cor": "Prata", "x_capacidade": "256GB", "active": True},
        {"repositoryId": "C", "displayName": "1TB Prata", "listPrice": 18499.0, "salePrice": 14443.33, "active": True},
    ],
}
ESTOQUE = {
    "A": {"status": "OUT_OF_STOCK", "quantidade": 0},
    "B": {"status": "IN_STOCK", "quantidade": 3},
    "C": {"status": "IN_STOCK", "quantidade": 5},
}


class Conversao(unittest.TestCase):
    def test_formato_omnichat(self):
        item = conversao.produto_omnichat(PRODUTO, ESTOQUE)
        self.assertEqual(item["objectId"], "100544PR")
        self.assertTrue(item["externalUrl"].startswith("https://www.iplace.com.br/apple-iphone-17-pro-max/100544PR?utm_source="))
        self.assertEqual(item["mainVariant"]["objectId"], "B")  # mais barata COM estoque
        self.assertEqual(len(item["variants"]), 3)
        sem_estoque = next(v for v in item["variants"] if v["objectId"] == "A")
        self.assertEqual((sem_estoque["quantity"], sem_estoque["visible"]), (0, False))
        self.assertIn({"key": "Cor", "value": "Prata"}, item["mainVariant"]["variations"])
        self.assertTrue(item["mainVariant"]["externalImageURL"].startswith("https://www.iplace.com.br/ccstore/"))
        self.assertEqual(item["productDescription"], "Descrição\nO iPhone mais potente")

    def test_sem_estoque_nenhum_fica_de_fora(self):
        vazio = {k: {"status": "OUT_OF_STOCK", "quantidade": 0} for k in ESTOQUE}
        self.assertIsNone(conversao.produto_omnichat(PRODUTO, vazio))

    def test_somente_sku(self):
        item = conversao.produto_omnichat(PRODUTO, ESTOQUE, somente_sku="C")
        self.assertEqual([v["objectId"] for v in item["variants"]], ["C"])


def chamar(query="iphone", searchType="TEXT", size=10, token=None, x_api_key=None, authorization=None):
    """Chama a funcao do endpoint direto (sem servidor HTTP)."""
    return main.buscar_produtos(query=query, inicio=0, size=size, searchType=searchType,
                                token=token, x_api_key=x_api_key, authorization=authorization)


class Endpoint(unittest.TestCase):
    def setUp(self):
        self._orig = (oracle.buscar_ids_por_texto, oracle.carregar_produtos, oracle.carregar_estoque, oracle.produto_do_sku)
        oracle.buscar_ids_por_texto = lambda termo, inicio, qtd: ["100544PR", "999PR"]
        oracle.carregar_produtos = lambda ids: {"100544PR": PRODUTO} if "100544PR" in ids else {}
        oracle.carregar_estoque = lambda pares: ESTOQUE
        oracle.produto_do_sku = lambda sku: "100544PR" if sku in ESTOQUE else None

    def tearDown(self):
        (oracle.buscar_ids_por_texto, oracle.carregar_produtos, oracle.carregar_estoque, oracle.produto_do_sku) = self._orig

    def test_sem_token_recusa(self):
        for kwargs in ({}, {"token": "errado"}, {"authorization": "Bearer errado"}):
            with self.assertRaises(HTTPException) as ctx:
                chamar(**kwargs)
            self.assertEqual(ctx.exception.status_code, 401)

    def test_busca_texto(self):
        r = chamar(x_api_key="segredo-teste", size=5)
        self.assertEqual([p["objectId"] for p in r], ["100544PR"])

    def test_token_na_url_e_bearer(self):
        self.assertEqual(len(chamar(token="segredo-teste")), 1)
        self.assertEqual(len(chamar(authorization="Bearer segredo-teste")), 1)

    def test_busca_por_sku_e_url(self):
        r = chamar(searchType="SKUID", query="C", x_api_key="segredo-teste")
        self.assertEqual([v["objectId"] for v in r[0]["variants"]], ["C"])
        url = "https://www.iplace.com.br/apple-iphone-17-pro-max/100544PR?x=1"
        r = chamar(searchType="URL", query=url, x_api_key="segredo-teste")
        self.assertEqual(r[0]["objectId"], "100544PR")

    def test_site_fora_do_ar_responde_502(self):
        def falha(*_):
            raise oracle.OracleErro("timeout")
        oracle.buscar_ids_por_texto = falha
        self.assertEqual(chamar(x_api_key="segredo-teste").status_code, 502)


if __name__ == "__main__":
    unittest.main()
