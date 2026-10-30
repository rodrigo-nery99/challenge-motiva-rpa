import inspect

import pytest
from fastapi.testclient import TestClient

from conftest import IAFalsa, analise

from motiva_rpa import agente_voz
from motiva_rpa.api import criar_app


@pytest.fixture
def ia(criar_pipeline):
    falsa = IAFalsa(analise(rodovia="SP-348", km=72.4, sentido="capital", local_na_via="faixa 3",
                            obstrucao_pista=True, urgencia="CRITICA"))
    agente_voz.configurar(criar_pipeline(falsa))
    yield falsa
    agente_voz.configurar(None)


def test_textos_para_fala():
    assert agente_voz.soletrar("CNS-2026-000042") == "C N S, 2 0 2 6, 0 0 0 0 4 2"
    assert agente_voz.km_falado(54.3) == "quilômetro 54 mais 300"
    assert agente_voz.km_falado(101) == "quilômetro 101"
    assert agente_voz.rodovia_falada("SP-021") == "S P 21"


def test_registrar_por_voz(ia, emails_gerados):
    r = agente_voz.registrar_solicitacao_conservacao(
        "Buraco grande na faixa da direita", rodovia="Bandeirantes", km="72+400", sentido="capital",
        nome_profissional="Rogério", equipe_origem="Inspeção 03")
    assert r["sucesso"] and r["status"] == "ENCAMINHADA" and r["localizacao"].startswith("SP-348 km 72,400")
    assert r["protocolo_soletrado"] in r["mensagem_para_falar"]
    assert "S P 348, quilômetro 72 mais 400" in r["mensagem_para_falar"]
    assert "CCO foi avisado" in r["mensagem_para_falar"]  # orientação em urgência crítica
    assert ia.chamadas[0].canal == "voz" and ia.chamadas[0].dados_planilha["km"] == "72+400"
    assert not emails_gerados("confirmacao")  # por voz a confirmação é falada, não enviada


def test_voz_sem_km_pede_e_depois_complementa(ia):
    ia.resposta = analise(km=None)
    r = agente_voz.registrar_solicitacao_conservacao("placa caída", rodovia="Castello")
    assert r["status"] == "PENDENTE_INFORMACAO" and "km do local" in r["mensagem_para_falar"]

    ia.resposta = analise(km=45.3)
    c = agente_voz.complementar_solicitacao(r["protocolo"], "É no km 45 mais 300")
    assert c["sucesso"] and c["status"] == "ENCAMINHADA" and "45,300" in c["localizacao"]


def test_pendencias_no_trecho_e_aviso_de_duplicata(ia):
    primeiro = agente_voz.registrar_solicitacao_conservacao("buraco", rodovia="SP-348", km="72+400")
    pend = agente_voz.consultar_pendencias_trecho("Bandeirantes", "70", raio_km=5)
    assert pend["total"] == 1 and pend["solicitacoes"][0]["protocolo"] == primeiro["protocolo"]
    assert "Há 1 solicitação aberta" in pend["mensagem_para_falar"]

    segundo = agente_voz.registrar_solicitacao_conservacao("outro buraco no mesmo ponto", rodovia="SP-348", km="72")
    assert segundo["possivel_duplicata"] == primeiro["protocolo"]
    assert "já existe a solicitação" in segundo["mensagem_para_falar"]

    vazio = agente_voz.consultar_pendencias_trecho("SP-348", "150", raio_km=2)
    assert vazio["total"] == 0 and "Não há solicitações abertas" in vazio["mensagem_para_falar"]


def test_consultar_por_protocolo(ia):
    r = agente_voz.registrar_solicitacao_conservacao("buraco", rodovia="SP-348", km="72+400")
    c = agente_voz.consultar_solicitacao(r["protocolo"].lower())
    assert c["encontrada"] and c["protocolo"] == r["protocolo"]
    assert agente_voz.consultar_solicitacao("CNS-1999-000001")["encontrada"] is False


def test_despachante_de_ferramentas(ia):
    r = agente_voz.executar_ferramenta("registrar_solicitacao_conservacao", '{"descricao": "buraco", "rodovia": "SP-348", "km": "72"}')
    assert r["sucesso"]
    assert agente_voz.executar_ferramenta("apagar_tudo", {})["sucesso"] is False
    assert agente_voz.executar_ferramenta("consultar_solicitacao", {"parametro_errado": 1})["sucesso"] is False


def test_definicoes_das_ferramentas_batem_com_as_funcoes():
    for ferramenta in agente_voz.FERRAMENTAS:
        funcao = getattr(agente_voz, ferramenta["name"])
        parametros = set(inspect.signature(funcao).parameters)
        assert set(ferramenta["parameters"]["properties"]) <= parametros
        assert set(ferramenta["parameters"].get("required", [])) <= parametros
    nomes = [f["function"]["name"] for f in agente_voz.ferramentas_chat_completions()]
    assert nomes == ["registrar_solicitacao_conservacao", "consultar_solicitacao",
                     "consultar_pendencias_trecho", "complementar_solicitacao"]


def test_api_http(criar_pipeline):
    cliente = TestClient(criar_app(criar_pipeline(IAFalsa())))
    assert cliente.get("/saude").json()["trechos"] > 0
    r = cliente.post("/voz/solicitacoes", json={"descricao": "buraco no acostamento", "rodovia": "SP-280", "km": "45+300"}).json()
    assert r["status"] == "ENCAMINHADA"
    assert cliente.get(f"/voz/solicitacoes/{r['protocolo']}").json()["localizacao"].startswith("SP-280")
    assert cliente.get("/voz/solicitacoes/CNS-1999-000001").status_code == 404
    assert cliente.get("/voz/pendencias", params={"rodovia": "SP-280", "km": "45"}).json()["total"] == 1
    assert cliente.post("/voz/ferramentas/consultar_solicitacao", json={"protocolo": r["protocolo"]}).json()["encontrada"]
    assert cliente.post("/voz/ferramentas/nao_existe", json={}).status_code == 404
    assert len(cliente.get("/solicitacoes").json()) == 1
    agente_voz.configurar(None)
