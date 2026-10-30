"""Configuração lida do arquivo .env (ou das variáveis de ambiente)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

# Raiz do repositório (…/motiva-conservacao-rpa)
RAIZ = Path(__file__).resolve().parents[2]
FUSO = ZoneInfo("America/Sao_Paulo")


def _bool(valor: str | None, padrao: bool = False) -> bool:
    if valor is None or valor.strip() == "":
        return padrao
    return valor.strip().lower() in {"1", "true", "sim", "yes", "on"}


def _caminho(valor: str | None, padrao: str) -> Path:
    p = Path(valor.strip() if valor and valor.strip() else padrao)
    return p if p.is_absolute() else RAIZ / p


@dataclass
class Config:
    # IA
    openai_api_key: str = ""
    openai_modelo: str = "gpt-4.1-mini"
    openai_reasoning_effort: str = ""
    confianca_minima: float = 0.6
    permitir_fallback: bool = True

    # Gmail
    gmail_usuario: str = ""
    gmail_senha_app: str = ""
    gmail_pasta_entrada: str = "INBOX"
    gmail_marcador_processados: str = ""
    gmail_marcador_erros: str = ""
    gmail_filtro_assunto: str = ""

    # Encaminhamento
    envio_modo: str = "arquivo"  # arquivo | smtp
    envio_redirecionar_para: str = ""
    enviar_confirmacao_solicitante: bool = True

    # Pastas e arquivos
    pasta_entrada: Path = field(default_factory=lambda: RAIZ / "entrada")
    pasta_saida: Path = field(default_factory=lambda: RAIZ / "saida")
    banco_dados: Path = field(default_factory=lambda: RAIZ / "dados" / "solicitacoes.db")
    cadastro_trechos: Path = field(default_factory=lambda: RAIZ / "dados" / "trechos_motiva.csv")
    matriz_roteamento: Path = field(default_factory=lambda: RAIZ / "config" / "roteamento.yaml")
    arquivo_prompt: Path = field(default_factory=lambda: RAIZ / "prompts" / "sistema_conservacao.md")
    monitor_intervalo: int = 60

    @property
    def gmail_configurado(self) -> bool:
        return bool(self.gmail_usuario and self.gmail_senha_app)

    @property
    def openai_configurada(self) -> bool:
        return bool(self.openai_api_key)

    def criar_pastas(self) -> None:
        for pasta in (
            self.pasta_entrada,
            self.pasta_entrada / "processados",
            self.pasta_entrada / "erros",
            self.pasta_saida,
            self.pasta_saida / "emails",
            self.banco_dados.parent,
        ):
            pasta.mkdir(parents=True, exist_ok=True)


def carregar_config(arquivo_env: Path | None = None) -> Config:
    load_dotenv(arquivo_env or RAIZ / ".env", override=False)
    e = os.environ.get
    return Config(
        openai_api_key=e("OPENAI_API_KEY", "").strip(),
        openai_modelo=e("OPENAI_MODEL", "gpt-4.1-mini").strip() or "gpt-4.1-mini",
        openai_reasoning_effort=e("OPENAI_REASONING_EFFORT", "").strip(),
        confianca_minima=float(e("IA_CONFIANCA_MINIMA", "0.6") or 0.6),
        permitir_fallback=_bool(e("IA_PERMITIR_FALLBACK"), True),
        gmail_usuario=e("GMAIL_USUARIO", "").strip(),
        gmail_senha_app=e("GMAIL_SENHA_APP", "").replace(" ", "").strip(),
        gmail_pasta_entrada=e("GMAIL_PASTA_ENTRADA", "INBOX").strip() or "INBOX",
        gmail_marcador_processados=e("GMAIL_MARCADOR_PROCESSADOS", "").strip(),
        gmail_marcador_erros=e("GMAIL_MARCADOR_ERROS", "").strip(),
        gmail_filtro_assunto=e("GMAIL_FILTRO_ASSUNTO", "").strip(),
        envio_modo=(e("ENVIO_MODO", "arquivo").strip().lower() or "arquivo"),
        envio_redirecionar_para=e("ENVIO_REDIRECIONAR_PARA", "").strip(),
        enviar_confirmacao_solicitante=_bool(e("ENVIAR_CONFIRMACAO_SOLICITANTE"), True),
        pasta_entrada=_caminho(e("PASTA_ENTRADA"), "entrada"),
        pasta_saida=_caminho(e("PASTA_SAIDA"), "saida"),
        banco_dados=_caminho(e("BANCO_DADOS"), "dados/solicitacoes.db"),
        cadastro_trechos=_caminho(e("CADASTRO_TRECHOS"), "dados/trechos_motiva.csv"),
        matriz_roteamento=_caminho(e("MATRIZ_ROTEAMENTO"), "config/roteamento.yaml"),
        monitor_intervalo=int(e("MONITOR_INTERVALO_SEGUNDOS", "60") or 60),
    )
