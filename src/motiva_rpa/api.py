"""API HTTP (FastAPI) — porta de entrada do agente de voz e de outros sistemas.

Rodar:  python main.py api      →  documentação interativa em http://localhost:8000/docs
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import Body, FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from . import agente_voz
from .pipeline import Pipeline


class RelatoVoz(BaseModel):
    descricao: str = Field(..., examples=["Buraco grande na faixa da direita, uns 80 centímetros, carros desviando"])
    rodovia: Optional[str] = Field(None, examples=["SP-348"])
    km: Optional[str] = Field(None, examples=["72+400"])
    sentido: Optional[str] = Field(None, examples=["capital"])
    local_na_via: Optional[str] = None
    referencia: Optional[str] = None
    nome_profissional: Optional[str] = None
    equipe_origem: Optional[str] = Field(None, examples=["Inspeção 03"])
    telefone: Optional[str] = None
    id_chamada: Optional[str] = None


class Complemento(BaseModel):
    informacao: str = Field(..., examples=["É no km 45+300, sentido interior"])
    id_chamada: Optional[str] = None


def criar_app(pipeline: Pipeline | None = None) -> FastAPI:
    if pipeline is not None:
        agente_voz.configurar(pipeline)

    app = FastAPI(
        title="Motiva — Robô de Conservação Rodoviária",
        description="Sprint 1: registro e encaminhamento de solicitações de conservação. "
                    "Endpoints /voz/* são as funções que o agente de voz chama.",
        version="1.0.0",
    )

    @app.get("/saude", tags=["sistema"])
    def saude() -> dict:
        p = agente_voz._p()
        return {"ok": True, "motor_ia": p.motor.nome, "envio": p.config.envio_modo, "trechos": len(p.trechos)}

    @app.get("/voz/ferramentas", tags=["agente de voz"])
    def listar_ferramentas() -> list[dict]:
        """Definições das ferramentas no formato da OpenAI (Realtime / Responses)."""
        return agente_voz.FERRAMENTAS

    @app.post("/voz/ferramentas/{nome}", tags=["agente de voz"])
    def executar(nome: str, argumentos: dict[str, Any] = Body(default_factory=dict)) -> dict:
        """Despachante genérico: para plataformas de voz que chamam um webhook por ferramenta."""
        resposta = agente_voz.executar_ferramenta(nome, argumentos)
        if resposta.get("erro", "").startswith("Ferramenta desconhecida"):
            raise HTTPException(404, resposta["erro"])
        return resposta

    @app.post("/voz/solicitacoes", tags=["agente de voz"])
    def registrar(relato: RelatoVoz) -> dict:
        return agente_voz.registrar_solicitacao_conservacao(**relato.model_dump())

    @app.get("/voz/solicitacoes/{protocolo}", tags=["agente de voz"])
    def consultar(protocolo: str) -> dict:
        resposta = agente_voz.consultar_solicitacao(protocolo)
        if not resposta["encontrada"]:
            raise HTTPException(404, resposta["mensagem_para_falar"])
        return resposta

    @app.get("/voz/pendencias", tags=["agente de voz"])
    def pendencias(rodovia: str = Query(..., examples=["SP-280"]), km: str = Query(..., examples=["45"]),
                   raio_km: float = 5.0) -> dict:
        return agente_voz.consultar_pendencias_trecho(rodovia, km, raio_km)

    @app.post("/voz/solicitacoes/{protocolo}/complemento", tags=["agente de voz"])
    def complementar(protocolo: str, c: Complemento) -> dict:
        resposta = agente_voz.complementar_solicitacao(protocolo, c.informacao, c.id_chamada)
        if not resposta.get("sucesso"):
            raise HTTPException(404, resposta["mensagem_para_falar"])
        return resposta

    @app.get("/solicitacoes", tags=["registro"])
    def listar(status: Optional[str] = None, limite: int = 50) -> list[dict]:
        campos = ["protocolo", "recebido_em", "canal", "status", "categoria", "urgencia", "confianca",
                  "rodovia", "km", "sentido", "concessao", "resumo", "equipe_nome", "prazo_retorno", "motor_ia"]
        return [{c: getattr(s, c) for c in campos} for s in agente_voz._p().repo.listar(status, limite)]

    @app.get("/solicitacoes/{protocolo}/historico", tags=["registro"])
    def historico(protocolo: str) -> list[dict]:
        return agente_voz._p().repo.historico(protocolo.upper())

    return app


app = criar_app()
