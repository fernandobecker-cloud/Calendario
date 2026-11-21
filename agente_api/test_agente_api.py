"""Testes do servico do agente (sem rede). Rodar:
    python -m unittest agente_api.test_agente_api -v
"""

import os
import unittest

os.environ.setdefault("AGENTE_API_TOKEN", "segredo-teste")

from fastapi import HTTPException  # noqa: E402

from agente_api import config, conversao, main, oracle, planilha  # noqa: E402


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
        self._fonte = config.FONTE
        config.FONTE = "site"
        self._orig = (oracle.buscar_ids_por_texto, oracle.carregar_produtos, oracle.carregar_estoque, oracle.produto_do_sku)
        oracle.buscar_ids_por_texto = lambda termo, inicio, qtd: ["100544PR", "999PR"]
        oracle.carregar_produtos = lambda ids: {"100544PR": PRODUTO} if "100544PR" in ids else {}
        oracle.carregar_estoque = lambda pares: ESTOQUE
        oracle.produto_do_sku = lambda sku: "100544PR" if sku in ESTOQUE else None

    def tearDown(self):
        config.FONTE = self._fonte
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


LINHAS_PLANILHA = [
    {"produto_id": "100544PR", "produto": "iPhone 17 Pro Max", "sku": "100072474", "variante": "256GB Laranja-cósmico",
     "cor": "Laranja-cósmico", "capacidade": "256GB", "preco_de": 12499.0, "preco_por": 9829.0,
     "preco_loja": 10499.0, "condicao_loja": "10x sem juros", "estoque": 3,
     "link": "https://www.iplace.com.br/apple-iphone-17-pro-max/100544PR", "ativo": True},
    {"produto_id": "100544PR", "produto": "iPhone 17 Pro Max", "sku": "100072475", "variante": "256GB Prata",
     "cor": "Prata", "capacidade": "256GB", "preco_por": 9829.0, "estoque": 0, "ativo": True},
    {"produto_id": "", "produto": "iPhone 17", "sku": "200", "variante": "128GB Preto", "preco_por": 5000.0,
     "preco_pix": 4400.0, "preco_cartao": 5000.0, "parcelas": 10, "juros_mes": 0, "estoque": None, "ativo": True},
    {"produto_id": "", "produto": "AirPods Pro 3", "sku": "300", "preco_por": 2643.33, "ativo": False},
]


class Planilha(unittest.TestCase):
    def setUp(self):
        self._fonte = config.FONTE
        config.FONTE = "planilha"
        planilha._estado.update(feed={"linhas": LINHAS_PLANILHA}, lido_em=1e18)

    def tearDown(self):
        config.FONTE = self._fonte
        planilha._estado.update(feed=None, lido_em=0.0)

    def test_busca_texto_ordem_e_formato(self):
        r = chamar(query="quero o iphone 17", x_api_key="segredo-teste")
        self.assertEqual([p["name"] for p in r], ["iPhone 17", "iPhone 17 Pro Max"])
        pro = r[1]
        self.assertEqual(pro["objectId"], "100544PR")
        self.assertEqual(pro["mainVariant"]["objectId"], "100072474")
        cartao, pix = pro["mainVariant"]["installmentOptions"]
        self.assertEqual(pro["mainVariant"]["salePrice"], 9829.0)  # preco grande do site = Pix
        self.assertEqual((cartao["oneTimePayment"], cartao["installmentPrice"], pix["oneTimePayment"]),
                         (10921.11, 582.20, 9829.0))
        self.assertIn("PREÇO NA LOJA FÍSICA", pro["productDescription"])
        self.assertIn("R$ 10.499,00, 10x sem juros", pro["productDescription"])
        self.assertTrue(pro["externalUrl"].endswith("?" + config.UTM))

    def test_regras_por_linha_e_estoque_em_branco(self):
        r = chamar(query="iphone 17 128", x_api_key="segredo-teste")
        self.assertEqual(len(r), 1)
        cartao, pix = r[0]["mainVariant"]["installmentOptions"]
        self.assertEqual((cartao["maxInstallments"], cartao["installmentPrice"], cartao["interest"]), (10, 500.0, 0))
        self.assertEqual(pix["oneTimePayment"], 4400.0)
        self.assertFalse(r[0]["trackInventory"])

    def test_inativo_e_sem_acento(self):
        self.assertEqual(chamar(query="airpods", x_api_key="segredo-teste"), [])
        r = chamar(query="laranja cosmico", x_api_key="segredo-teste")
        self.assertEqual(r[0]["objectId"], "100544PR")

    def test_item_so_de_loja(self):
        grupo = {"chave": "W", "linhas": [
            {"produto": "Apple Watch SE", "produto_id": "W", "sku": "1", "variante": "40mm", "preco_por": 2329.0,
             "preco_loja": 2551.12, "link": "https://www.iplace.com.br/x/WPR", "ativo": True},
            {"produto": "Apple Watch SE", "produto_id": "W", "sku": "2", "variante": "44mm", "preco_por": None,
             "preco_loja": 2903.12, "condicao_loja": "10x de R$ 329,90", "ativo": True},
        ]}
        self.assertEqual(len(planilha.agrupar(grupo["linhas"])[0]["linhas"]), 2)
        item = planilha.produto_omnichat(grupo)
        so = next(v for v in item["variants"] if v["objectId"] == "2")
        self.assertEqual(so["salePrice"], 2903.12)
        self.assertEqual(so["installmentOptions"], [])
        self.assertIn({"key": "Preço", "value": "somente loja física"}, so["variations"])
        self.assertIn("não tem preço de site/televendas", item["productDescription"])
        self.assertEqual(item["mainVariant"]["objectId"], "1")
        sem_site = planilha.produto_omnichat({"chave": "x", "linhas": [
            {"produto": "IPHONE 13 MIDNIGHT 128GB MLPF3BR/A", "sku": "9", "preco_loja": 2287.12, "ativo": True}]})
        self.assertIsNone(sem_site["externalUrl"])
        self.assertIn("SOMENTE NA LOJA FÍSICA", sem_site["productDescription"])
        # Sem preço nenhum a linha não entra.
        self.assertEqual(planilha.agrupar([{"produto": "X", "sku": "3", "ativo": True}]), [])

    def test_orcamento_e_palavras_de_conversa(self):
        self.assertEqual(planilha.orcamento("iphone ate 5 mil")[0], 5000)
        self.assertEqual(planilha.orcamento("iphone até R$ 4.500,00")[0], 4500)
        self.assertEqual(planilha.orcamento("iphone 5k")[0], 5000)
        self.assertIsNone(planilha.orcamento("iphone 17 256")[0])
        linhas = [
            {"produto": "iPhone 17", "produto_id": "A", "sku": "1", "preco_por": 5399.0, "ativo": True, "categoria": "IPHONE"},
            {"produto": "iPhone 17e", "produto_id": "B", "sku": "2", "preco_por": 4259.0, "ativo": True, "categoria": "IPHONE"},
            {"produto": "iPhone 16e", "produto_id": "C", "sku": "3", "preco_por": 3129.0, "ativo": True, "categoria": "IPHONE"},
        ]
        planilha._estado.update(feed={"linhas": linhas}, lido_em=1e18)
        nomes = [p["name"] for p in planilha.buscar_texto("iphone mais em conta ate 5 mil", 0, 10)]
        self.assertEqual(nomes, ["iPhone 16e", "iPhone 17e"])
        self.assertEqual(len(planilha.buscar_texto("iphone baratinho", 0, 10)), 3)

    def test_regra_do_site_pix_e_cartao(self):
        # Paginas do site em 17/11/2026: (preco no Pix, parcelas, valor da parcela)
        for pix, n, parcela in [(5399.0, 21, 319.80), (99.0, 21, 5.86), (69.0, 16, None)]:
            cartao, opcao_pix = planilha.produto_omnichat(
                {"chave": "x", "linhas": [{"produto": "X", "sku": "1", "preco_por": pix, "ativo": True}]}
            )["mainVariant"]["installmentOptions"]
            self.assertEqual(opcao_pix["oneTimePayment"], pix)
            self.assertEqual(cartao["maxInstallments"], n, pix)
            if parcela:
                self.assertEqual(cartao["installmentPrice"], parcela, pix)

    def test_nomes_do_erp_e_aparelho_antes_de_acessorio(self):
        linhas = [
            {"produto": "CAPA APPLE IPH 17 PRO LARANJA", "sku": "1", "preco_por": 499.0,
             "descricao": "Categoria: CAPAS IPHONE APPLE | Ação: BF", "ativo": True},
            {"produto": "IPHONE 17 PRO COS ORANGE 256GB", "sku": "2", "preco_por": 7999.0,
             "variante": "IPHONE 17 PRO COS ORANGE 256GB MG8H4BE/A",
             "descricao": "Categoria: IPHONE | Ação: BF", "ativo": True},
        ]
        planilha._estado.update(feed={"linhas": linhas}, lido_em=1e18)
        r = chamar(query="iphone 17 pro laranja cosmico", x_api_key="segredo-teste")
        self.assertEqual([p["objectId"] for p in r][0], planilha.normalizar("IPHONE 17 PRO COS ORANGE 256GB"))
        self.assertEqual(r[0]["mainVariant"]["name"], "IPHONE 17 PRO COS ORANGE 256GB MG8H4BE/A")
        r = chamar(query="capa iphone 17", x_api_key="segredo-teste")
        self.assertEqual(r[0]["name"], "CAPA APPLE IPH 17 PRO LARANJA")

    def test_sku_id_url(self):
        r = chamar(searchType="SKUID", query="100072475", x_api_key="segredo-teste")
        self.assertEqual(r, [])  # unica variante pedida esta sem estoque
        r = chamar(searchType="ID", query="100544pr", x_api_key="segredo-teste")
        self.assertEqual(len(r[0]["variants"]), 2)
        r = chamar(searchType="URL", query="https://www.iplace.com.br/x/100544PR?utm=1", x_api_key="segredo-teste")
        self.assertEqual(r[0]["objectId"], "100544PR")

    def test_sem_planilha_responde_502(self):
        planilha._estado.update(feed=None, lido_em=0.0)
        orig = planilha._baixar_feed

        def falha():
            raise planilha.PlanilhaErro("nenhuma planilha da campanha foi carregada no portal ainda")
        planilha._baixar_feed = falha
        try:
            self.assertEqual(chamar(x_api_key="segredo-teste").status_code, 502)
        finally:
            planilha._baixar_feed = orig

    def test_portal_fora_usa_ultima_copia(self):
        planilha._estado["lido_em"] = 0.0
        orig = planilha._baixar_feed

        def falha():
            raise planilha.PlanilhaErro("timeout")
        planilha._baixar_feed = falha
        try:
            self.assertEqual(len(chamar(query="iphone", x_api_key="segredo-teste")), 2)
        finally:
            planilha._baixar_feed = orig


if __name__ == "__main__":
    unittest.main()
