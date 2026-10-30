import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from motiva_rpa.config import Config  # noqa: E402
from motiva_rpa.ia import ClassificadorRegras, MotorIA  # noqa: E402
from motiva_rpa.modelos import AnaliseSolicitacao  # noqa: E402
from motiva_rpa.pipeline import Pipeline  # noqa: E402


def analise(**alteracoes) -> AnaliseSolicitacao:
    """AnaliseSolicitacao com valores padrão — os testes mudam só o que importa."""
    base = dict(
        categoria="PAVIMENTO", urgencia="MEDIA", confianca=0.92,
        justificativa="teste", resumo="Buraco no acostamento", rodovia="SP-280", km=45.3, sentido="interior",
        local_na_via="acostamento", referencia=None, cidade=None, uf=None, obstrucao_pista=False,
        risco_imediato=False, interdicao_necessaria=None, multiplos_locais=False, dimensao=None, problemas=[],
        servicos_solicitados=[], data_preferencial=None, tipo_solicitante="INSPECAO_TRAFEGO",
        solicitante_nome="Fulano", solicitante_email=None, solicitante_telefone=None, equipe_origem=None,
    )
    base.update(alteracoes)
    return AnaliseSolicitacao(**base)


class IAFalsa:
    """Classificador de teste: devolve sempre a mesma análise."""

    nome = "falsa"

    def __init__(self, resposta: AnaliseSolicitacao | None = None, erro: Exception | None = None):
        self.resposta = resposta or analise()
        self.erro = erro
        self.chamadas = []

    def analisar(self, entrada):
        self.chamadas.append(entrada)
        if self.erro:
            raise self.erro
        return self.resposta


@pytest.fixture
def config(tmp_path) -> Config:
    return Config(
        pasta_entrada=tmp_path / "entrada",
        pasta_saida=tmp_path / "saida",
        banco_dados=tmp_path / "dados" / "teste.db",
        cadastro_trechos=RAIZ / "dados" / "trechos_motiva.csv",
        matriz_roteamento=RAIZ / "config" / "roteamento.yaml",
        arquivo_prompt=RAIZ / "prompts" / "sistema_conservacao.md",
    )


@pytest.fixture
def pipeline_regras(config) -> Pipeline:
    return Pipeline(config, motor=MotorIA(None, ClassificadorRegras()))


@pytest.fixture
def criar_pipeline(config):
    def _criar(classificador, reserva=None) -> Pipeline:
        return Pipeline(config, motor=MotorIA(classificador, reserva))

    return _criar


@pytest.fixture
def emails_gerados(config):
    def _lista(tipo: str | None = None) -> list[Path]:
        arquivos = sorted((config.pasta_saida / "emails").glob("*.eml"))
        return [a for a in arquivos if tipo is None or a.stem.endswith(tipo)]

    return _lista
