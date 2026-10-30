"""Define a equipe responsável e o prazo a partir da matriz em config/roteamento.yaml."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import yaml

from .modelos import Solicitacao


@dataclass
class Destino:
    equipe_id: str
    equipe_nome: str
    email: str
    copias: list[str] = field(default_factory=list)
    sla_horas: int = 24
    prazo: datetime | None = None
    regional: str | None = None
    motivo: str = ""


class Roteador:
    def __init__(self, caminho_matriz: Path):
        with Path(caminho_matriz).open(encoding="utf-8") as f:
            self.matriz = yaml.safe_load(f)
        self.equipes: dict = self.matriz["equipes"]

    def equipe(self, equipe_id: str) -> dict:
        if equipe_id not in self.equipes:
            raise KeyError(f"Equipe '{equipe_id}' não existe em roteamento.yaml")
        return self.equipes[equipe_id]

    def definir(self, s: Solicitacao, recebido_em: datetime) -> Destino:
        regional = s.concessao or self.matriz.get("regional_padrao", "AUTOBAN")
        if s.status == "EM_TRIAGEM":
            equipe_id = self.matriz["equipe_triagem"]
            motivo = f"Triagem humana: {s.motivo_status}"
        else:
            modelo_id = self.matriz["categorias"].get(s.categoria, self.matriz["equipe_triagem"])
            equipe_id = modelo_id.replace("{regional}", regional)
            if equipe_id not in self.equipes:  # concessão sem equipe própria cadastrada
                equipe_id = modelo_id.replace("{regional}", self.matriz.get("regional_padrao", "AUTOBAN"))
            motivo = f"Categoria {s.categoria}" + (f" na concessão {regional}" if "{regional}" in modelo_id else "")
            if not s.concessao and "{regional}" in modelo_id:
                motivo += " (trecho não identificado: concessão padrão)"

        equipe = self.equipe(equipe_id)
        regras_copia = self.matriz.get("copias", {})
        copias: list[str] = []
        if s.urgencia == "CRITICA" and s.status != "EM_TRIAGEM":
            copias += [self.equipe(eq)["email"] for eq in regras_copia.get("urgencia_critica", [])]
        if s.status != "EM_TRIAGEM":
            copias += [self.equipe(eq)["email"] for eq in regras_copia.get("por_categoria", {}).get(s.categoria, [])]

        sla = int(self.matriz["sla_horas"].get(s.urgencia, 24))
        return Destino(
            equipe_id=equipe_id,
            equipe_nome=equipe["nome"],
            email=equipe["email"],
            copias=list(dict.fromkeys(c for c in copias if c and c != equipe["email"])),
            sla_horas=sla,
            prazo=recebido_em + timedelta(hours=sla),
            regional=regional,
            motivo=motivo,
        )
