from motiva_rpa.modelos import formatar_km
from motiva_rpa.utils_texto import (
    converter_km,
    encontrar_km,
    encontrar_rodovias,
    encontrar_sentido,
    html_para_texto,
    mascarar_dados_sensiveis,
    normalizar_codigo_rodovia,
    normalizar_sentido,
    normalizar_uf,
    remover_citacoes,
)
from motiva_rpa.trechos import CadastroTrechos
from conftest import RAIZ


def test_codigo_de_rodovia():
    assert normalizar_codigo_rodovia("sp 280") == "SP-280"
    assert normalizar_codigo_rodovia("BR116") == "BR-116"
    assert normalizar_codigo_rodovia("SP-21") == "SP-021"
    assert normalizar_codigo_rodovia("Castello Branco") is None


def test_rodovias_no_texto_sem_confundir_telefone_e_protocolo():
    texto = "Protocolo CNS-2026-000001: SP 280 e BR-116. Ligue (11) 98765-4321, SP 98765"
    assert encontrar_rodovias(texto) == ["SP-280", "BR-116"]


def test_km_em_varios_formatos():
    assert converter_km("54+300") == 54.3
    assert converter_km("km 54,3") == 54.3
    assert converter_km("101") == 101.0
    assert converter_km(61.25) == 61.25
    assert converter_km("9999") is None
    assert encontrar_km("Bandeirantes km 72 — buraco no km 72+400") == 72.4
    assert encontrar_km("KM: 112+300") == 112.3
    assert encontrar_km("do km 101 ao 104") == 101
    assert formatar_km(54.3) == "54,300" and formatar_km(101.0) == "101"


def test_sentido():
    assert normalizar_sentido("sentido capital") == "CAPITAL"
    assert normalizar_sentido("São Paulo") == "CAPITAL"
    assert normalizar_sentido("N") == "NORTE"
    assert normalizar_sentido("rio de janeiro") == "Rio de Janeiro"
    assert encontrar_sentido("km 147, sentido Rio de Janeiro. O acidente") == "Rio de Janeiro"


def test_nomes_populares_de_rodovia():
    trechos = CadastroTrechos(RAIZ / "dados" / "trechos_motiva.csv")
    assert trechos.codigo_rodovia("Rodovia Castello Branco") == "SP-280"
    assert trechos.codigo_rodovia("Via Dutra") == "BR-116"
    assert trechos.codigo_rodovia("sp") is None
    assert trechos.rodovia_no_texto("buraco na castello perto do pedágio") == "SP-280"
    t = trechos.localizar("SP-348", 72.4)
    assert t.concessao == "AUTOBAN" and "Itupeva" in t.base_conservacao
    assert trechos.localizar("SP-348", 500) is None


def test_uf():
    assert normalizar_uf("sp") == "SP"
    assert normalizar_uf("Rio Grande do Sul") == "RS"
    assert normalizar_uf("XX") is None


def test_mascara_cpf_antes_de_enviar_para_ia():
    assert mascarar_dados_sensiveis("CPF 123.456.789-09 do usuário") == "CPF [CPF removido] do usuário"


def test_remove_historico_citado_de_respostas():
    texto = "É no km 33.\n\nEm 27/10/2026 11:21, Robô escreveu:\n> mensagem antiga"
    assert remover_citacoes(texto) == "É no km 33."


def test_html_para_texto():
    assert html_para_texto("<p>Olá<br>mundo</p><style>x{}</style>") == "Olá\nmundo"
