from conftest import RAIZ, analise

from motiva_rpa.ia import ResultadoIA
from motiva_rpa.modelos import Entrada
from motiva_rpa.regras_negocio import construir_registro
from motiva_rpa.trechos import CadastroTrechos

TRECHOS = CadastroTrechos(RAIZ / "dados" / "trechos_motiva.csv")


def registro(texto="texto qualquer", canal="email", email="inspetor@exemplo.example", dados=None, **campos):
    entrada = Entrada(canal=canal, origem_ref="t", texto=texto, remetente_email=email, dados_planilha=dados or {})
    return construir_registro(entrada, ResultadoIA(analise(**campos), "falsa", 0.1), TRECHOS, 0.6)


def test_dados_completos_sao_encaminhados_e_enriquecidos():
    s = registro()
    assert s.status == "ENCAMINHADA" and s.campos_faltantes == []
    assert s.concessao == "VIAOESTE" and s.sentido == "INTERIOR" and s.uf == "SP"
    assert s.localizacao == "SP-280 km 45,300 sentido Interior (acostamento)"


def test_nome_popular_vira_codigo():
    assert registro(rodovia="Castello Branco").rodovia == "SP-280"


def test_obstrucao_ou_risco_imediato_elevam_para_critica():
    assert registro(obstrucao_pista=True, urgencia="ALTA").urgencia == "CRITICA"
    assert registro(risco_imediato=True, urgencia="MEDIA").urgencia == "CRITICA"


def test_termo_de_seguranca_eleva_mesmo_se_a_ia_errar():
    s = registro(texto="Queda de barreira com terra ocupando a faixa", urgencia="BAIXA")
    assert s.urgencia == "CRITICA" and any("segurança" in a for a in s.avisos)


def test_negacao_nao_dispara_a_regra_de_seguranca():
    assert registro(texto="Tachas soltas, nada na pista além disso", urgencia="MEDIA").urgencia == "MEDIA"


def test_buraco_no_acostamento_sem_risco_continua_media():
    assert registro(texto="buraco no acostamento", urgencia="MEDIA").urgencia == "MEDIA"


def test_interdicao_necessaria_eleva_para_alta():
    assert registro(interdicao_necessaria=True, urgencia="MEDIA").urgencia == "ALTA"


def test_confianca_baixa_vai_para_triagem():
    assert registro(confianca=0.4).status == "EM_TRIAGEM"
    assert registro(confianca=0.4, categoria="FORA_ESCOPO").status == "EM_TRIAGEM"


def test_falta_km_com_email_pede_informacao():
    s = registro(km=None)
    assert s.status == "PENDENTE_INFORMACAO" and s.campos_faltantes == ["km do local"]


def test_km_encontrado_no_texto_quando_a_ia_nao_extrai():
    s = registro(texto="Buraco na Castello km 45+300", km=None)
    assert s.km == 45.3 and s.status == "ENCAMINHADA"


def test_falta_local_sem_contato_vai_para_triagem():
    assert registro(rodovia=None, km=None, email=None).status == "EM_TRIAGEM"


def test_critica_sem_km_e_encaminhada_assim_mesmo():
    s = registro(km=None, urgencia="CRITICA")
    assert s.status == "ENCAMINHADA" and any("faltantes" in a for a in s.avisos)


def test_ocorrencia_de_trafego_sempre_segue_para_o_cco():
    s = registro(categoria="OCORRENCIA_TRAFEGO", urgencia="CRITICA", km=None, rodovia=None, email=None)
    assert s.status == "ENCAMINHADA"


def test_km_fora_dos_trechos_da_concessao_gera_aviso():
    s = registro(km=500)
    assert s.concessao is None and any("fora dos trechos" in a for a in s.avisos)


def test_colunas_da_planilha_prevalecem_sobre_a_ia():
    s = registro(canal="arquivo", rodovia="SP-280", km=45.3, dados={"rodovia": "sp 270", "km": "71+400"})
    assert s.rodovia == "SP-270" and s.km == 71.4 and s.concessao == "VIAOESTE"
    assert any("coluna" in a for a in s.avisos)


def test_fora_do_escopo_nao_exige_local():
    s = registro(categoria="FORA_ESCOPO", urgencia="BAIXA", rodovia=None, km=None)
    assert s.status == "ENCAMINHADA" and s.campos_faltantes == []
