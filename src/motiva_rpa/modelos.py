"""Modelos de dados do processo de Conservação Rodoviária.

- ``AnaliseSolicitacao``: o "formulário" que a IA preenche. É enviado à OpenAI
  como JSON Schema (Structured Outputs), então a resposta sempre vem nesse formato.
- ``Entrada``: uma solicitação capturada (um e-mail, uma linha de planilha, uma ligação).
- ``Solicitacao``: o registro estruturado que fica no banco.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

from .config import FUSO

# ---------------------------------------------------------------------------
# Domínio
# ---------------------------------------------------------------------------

CATEGORIAS: dict[str, str] = {
    "PAVIMENTO": "Pavimento (buraco, trinca, afundamento, desnível)",
    "SINALIZACAO": "Sinalização vertical ou horizontal (placas, pintura, tachas)",
    "DISPOSITIVOS_SEGURANCA": "Dispositivos de segurança (defensa metálica, barreira, atenuador, cerca)",
    "DRENAGEM_TALUDES": "Drenagem e taludes (bueiro, alagamento, erosão, deslizamento)",
    "ILUMINACAO": "Iluminação e rede elétrica (postes, trevos, túneis, passarelas)",
    "VEGETACAO_LIMPEZA": "Vegetação e limpeza (roçada, árvore, entulho, lixo, obstáculo)",
    "OCORRENCIA_TRAFEGO": "Ocorrência de tráfego (acidente, veículo parado, animal na pista)",
    "FORA_ESCOPO": "Fora do escopo de conservação (pedágio, cobrança, elogio, outros)",
}

URGENCIAS: dict[str, str] = {
    "CRITICA": "Crítica",
    "ALTA": "Alta",
    "MEDIA": "Média",
    "BAIXA": "Baixa",
}
ORDEM_URGENCIA = ["BAIXA", "MEDIA", "ALTA", "CRITICA"]

TIPOS_SOLICITANTE = {
    "INSPECAO_TRAFEGO": "Inspetor de tráfego / equipe de inspeção de pista",
    "EQUIPE_CAMPO": "Equipe de conservação ou manutenção em campo",
    "CCO": "Centro de Controle Operacional (CCO)",
    "USUARIO": "Usuário da rodovia (0800, ouvidoria, e-mail)",
    "OUTRO": "Outro",
}

SENTIDOS = {
    "NORTE": "Norte", "SUL": "Sul", "LESTE": "Leste", "OESTE": "Oeste",
    "CAPITAL": "Capital", "INTERIOR": "Interior", "LITORAL": "Litoral",
    "AMBOS": "Ambos os sentidos",
}

# Status do ciclo de vida da solicitação
STATUS = {
    "ENCAMINHADA": "Encaminhada ao responsável",
    "PENDENTE_INFORMACAO": "Aguardando informação do solicitante",
    "EM_TRIAGEM": "Em triagem humana",
    "CONCLUIDA": "Concluída",
    "CANCELADA": "Cancelada",
}
STATUS_ABERTOS = ("ENCAMINHADA", "PENDENTE_INFORMACAO", "EM_TRIAGEM")

Categoria = Literal[
    "PAVIMENTO",
    "SINALIZACAO",
    "DISPOSITIVOS_SEGURANCA",
    "DRENAGEM_TALUDES",
    "ILUMINACAO",
    "VEGETACAO_LIMPEZA",
    "OCORRENCIA_TRAFEGO",
    "FORA_ESCOPO",
]
Urgencia = Literal["CRITICA", "ALTA", "MEDIA", "BAIXA"]
TipoSolicitante = Literal["INSPECAO_TRAFEGO", "EQUIPE_CAMPO", "CCO", "USUARIO", "OUTRO"]


def agora() -> datetime:
    return datetime.now(FUSO).replace(microsecond=0)


# ---------------------------------------------------------------------------
# Saída estruturada da IA
# ---------------------------------------------------------------------------


class AnaliseSolicitacao(BaseModel):
    """Classificação e dados extraídos de UMA solicitação de conservação rodoviária."""

    categoria: Categoria = Field(description="Categoria da solicitação, conforme as definições do prompt.")
    urgencia: Urgencia = Field(description="Urgência operacional, conforme os critérios do prompt.")
    confianca: float = Field(description="Confiança na classificação, de 0.0 a 1.0.")
    justificativa: str = Field(description="Até 2 frases explicando a categoria e a urgência escolhidas.")
    resumo: str = Field(description="Resumo objetivo para a equipe, até 200 caracteres.")

    rodovia: Optional[str] = Field(description="Código da rodovia (ex.: SP-280, BR-116) ou nome citado. null se não houver.")
    km: Optional[float] = Field(description="Quilômetro do local em número decimal (km 54+300 -> 54.3). null se não houver.")
    sentido: Optional[str] = Field(
        description="Sentido da pista como citado: capital, interior, litoral, norte, sul, leste, oeste, ambos, "
        "ou a cidade de destino (ex.: 'Rio de Janeiro'). null se não citado."
    )
    local_na_via: Optional[str] = Field(description="Posição na via: faixa 1/2/3, acostamento, canteiro central, marginal, trevo, ponte, túnel, alça…")
    referencia: Optional[str] = Field(description="Ponto de referência citado (praça de pedágio, viaduto, posto, cidade próxima).")
    cidade: Optional[str] = Field(description="Município do local, se citado.")
    uf: Optional[str] = Field(description="Sigla da UF do local, se citada ou óbvia.")

    obstrucao_pista: bool = Field(description="true se algo bloqueia ou invade a pista de rolamento (faixas onde os veículos circulam).")
    risco_imediato: bool = Field(
        description="true só se há risco IMEDIATO a usuários ou trabalhadores (ver critérios do prompt)."
    )
    interdicao_necessaria: Optional[bool] = Field(
        description="true se o texto indica que é preciso interditar/sinalizar faixa ou acostamento; null se não der para saber."
    )
    multiplos_locais: bool = Field(description="true se a mensagem trata de dois ou mais locais/problemas diferentes.")
    dimensao: Optional[str] = Field(description="Tamanho ou extensão citada (ex.: 'buraco de 1 m', '50 m de defensa').")
    problemas: list[str] = Field(description="Problemas relatados, em frases curtas.")
    servicos_solicitados: list[str] = Field(description="Serviços pedidos explicitamente (ex.: tapa-buraco, roçada, troca de placa).")
    data_preferencial: Optional[str] = Field(
        description="Só se o solicitante pedir ou sugerir uma data (AAAA-MM-DD). Caso contrário null."
    )

    tipo_solicitante: TipoSolicitante = Field(description="Quem está pedindo.")
    solicitante_nome: Optional[str] = Field(description="Nome de quem pediu.")
    solicitante_email: Optional[str] = Field(description="E-mail de contato informado no texto.")
    solicitante_telefone: Optional[str] = Field(description="Telefone ou rádio de contato informado no texto.")
    equipe_origem: Optional[str] = Field(description="Equipe, base ou viatura de quem relatou (ex.: 'Inspeção 03', 'Base km 48').")


# ---------------------------------------------------------------------------
# Entrada capturada
# ---------------------------------------------------------------------------


@dataclass
class Entrada:
    """Uma solicitação recebida, antes de qualquer interpretação."""

    canal: str  # email | arquivo | voz | api
    origem_ref: str  # identificador único da origem (Message-ID, arquivo#linha…)
    texto: str
    assunto: Optional[str] = None
    remetente_nome: Optional[str] = None
    remetente_email: Optional[str] = None
    recebido_em: datetime = field(default_factory=agora)
    arquivo_origem: Optional[str] = None
    # Colunas reconhecidas da planilha (rodovia, km, sentido…) ou campos da
    # ligação. Quando válidas, prevalecem sobre o que a IA extraiu do texto.
    dados_planilha: dict[str, str] = field(default_factory=dict)
    # Texto de apoio, ex.: corpo do e-mail que trouxe a planilha em anexo
    contexto: Optional[str] = None


# ---------------------------------------------------------------------------
# Registro estruturado
# ---------------------------------------------------------------------------


@dataclass
class Solicitacao:
    id: Optional[int] = None
    protocolo: Optional[str] = None
    criado_em: Optional[str] = None
    atualizado_em: Optional[str] = None
    recebido_em: Optional[str] = None

    canal: str = ""
    origem_ref: str = ""
    arquivo_origem: Optional[str] = None
    assunto: Optional[str] = None
    remetente_nome: Optional[str] = None
    remetente_email: Optional[str] = None
    texto_original: str = ""

    categoria: str = ""
    urgencia: str = ""
    confianca: float = 0.0
    justificativa: str = ""
    resumo: str = ""

    rodovia: Optional[str] = None
    km: Optional[float] = None
    sentido: Optional[str] = None
    local_na_via: Optional[str] = None
    referencia: Optional[str] = None
    cidade: Optional[str] = None
    uf: Optional[str] = None
    concessao: Optional[str] = None  # do cadastro de trechos
    trecho: Optional[str] = None
    base_conservacao: Optional[str] = None

    obstrucao_pista: bool = False
    risco_imediato: bool = False
    interdicao_necessaria: Optional[bool] = None
    dimensao: Optional[str] = None
    data_preferencial: Optional[str] = None

    tipo_solicitante: str = "OUTRO"
    solicitante_nome: Optional[str] = None
    solicitante_email: Optional[str] = None
    solicitante_telefone: Optional[str] = None
    equipe_origem: Optional[str] = None

    possivel_duplicata: Optional[str] = None  # protocolo de solicitação aberta no mesmo local
    campos_faltantes: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    motor_ia: str = ""
    dados_ia: dict = field(default_factory=dict)
    dados_estruturados: dict = field(default_factory=dict)  # colunas da planilha / campos da ligação

    status: str = ""
    motivo_status: str = ""
    equipe_id: Optional[str] = None
    equipe_nome: Optional[str] = None
    equipe_email: Optional[str] = None
    copias: list[str] = field(default_factory=list)
    sla_horas: Optional[int] = None
    prazo_retorno: Optional[str] = None

    def como_dict(self) -> dict:
        return asdict(self)

    @property
    def categoria_descricao(self) -> str:
        return CATEGORIAS.get(self.categoria, self.categoria)

    @property
    def urgencia_descricao(self) -> str:
        return URGENCIAS.get(self.urgencia, self.urgencia)

    @property
    def localizacao(self) -> str:
        """Ex.: 'SP-280 km 45,300 sentido Interior (faixa 1)'."""
        if not self.rodovia and self.km is None:
            return self.referencia or self.cidade or "local não informado"
        partes = [self.rodovia or "rodovia não informada"]
        if self.km is not None:
            partes.append(f"km {formatar_km(self.km)}")
        if self.sentido:
            partes.append(f"sentido {SENTIDOS.get(self.sentido, self.sentido)}")
        texto = " ".join(partes)
        return f"{texto} ({self.local_na_via})" if self.local_na_via else texto


def formatar_km(km: float | None) -> str:
    """54.3 -> '54,300'; 101.0 -> '101'."""
    if km is None:
        return "—"
    if float(km).is_integer():
        return str(int(km))
    return f"{km:.3f}".replace(".", ",")


@dataclass
class Resultado:
    """O que o pipeline devolve depois de processar uma entrada."""

    protocolo: Optional[str]
    status: str
    categoria: Optional[str] = None
    urgencia: Optional[str] = None
    equipe: Optional[str] = None
    prazo_retorno: Optional[str] = None
    motor_ia: Optional[str] = None
    origem_ref: str = ""
    duplicado: bool = False
    complemento: bool = False
    avisos: list[str] = field(default_factory=list)
    erro: Optional[str] = None

    def como_dict(self) -> dict:
        return asdict(self)
