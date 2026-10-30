"""Cadastro de trechos (simula o sistema de ativos rodoviários da concessionária).

No protótipo o cadastro é um CSV em ``dados/trechos_motiva.csv``: cada linha é um
trecho de rodovia (km inicial–final) com a concessão e a base de conservação
responsável. Na operação real este módulo seria trocado por uma consulta ao
sistema de gestão de ativos.

Também converte nomes populares em códigos ("Castello Branco" -> SP-280).
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from pathlib import Path

from .utils_texto import normalizar_busca, normalizar_codigo_rodovia

log = logging.getLogger(__name__)


@dataclass
class Trecho:
    rodovia: str
    nome_rodovia: str
    km_inicial: float
    km_final: float
    concessao: str  # id da regional/concessão usado na matriz de roteamento
    nome_concessao: str
    base_conservacao: str
    cidade_base: str
    uf: str

    @property
    def descricao(self) -> str:
        return f"{self.rodovia} km {self.km_inicial:g}–{self.km_final:g} ({self.nome_concessao})"


class CadastroTrechos:
    def __init__(self, caminho: Path | None):
        self.trechos: list[Trecho] = []
        self.apelidos: dict[str, str] = {}  # nome normalizado -> código
        if caminho and Path(caminho).exists():
            self._carregar(Path(caminho))
        elif caminho:
            log.warning("Cadastro de trechos não encontrado em %s; seguindo sem enriquecimento.", caminho)

    def _carregar(self, caminho: Path) -> None:
        with caminho.open(encoding="utf-8-sig", newline="") as f:
            for linha in csv.DictReader(f, delimiter=";"):
                codigo = normalizar_codigo_rodovia(linha.get("rodovia"))
                if not codigo:
                    continue
                t = Trecho(
                    rodovia=codigo,
                    nome_rodovia=(linha.get("nome_rodovia") or "").strip(),
                    km_inicial=float(linha["km_inicial"]),
                    km_final=float(linha["km_final"]),
                    concessao=(linha.get("concessao") or "").strip().upper(),
                    nome_concessao=(linha.get("nome_concessao") or "").strip(),
                    base_conservacao=(linha.get("base_conservacao") or "").strip(),
                    cidade_base=(linha.get("cidade_base") or "").strip(),
                    uf=(linha.get("uf") or "").strip().upper(),
                )
                self.trechos.append(t)
                for apelido in [t.nome_rodovia, *(linha.get("apelidos") or "").split("|")]:
                    if apelido.strip():
                        self.apelidos[normalizar_busca(apelido)] = codigo

    def codigo_rodovia(self, valor: str | None) -> str | None:
        """Aceita código ('sp 280') ou nome ('Rodovia Castello Branco')."""
        if not valor:
            return None
        codigo = normalizar_codigo_rodovia(valor)
        if codigo:
            return codigo
        t = normalizar_busca(valor)
        t = t.replace("rodovia ", "").replace("rod ", "").strip()
        for apelido, codigo in sorted(self.apelidos.items(), key=lambda kv: -len(kv[0])):
            if apelido and (apelido in t or (len(t) >= 5 and t in apelido)):
                return codigo
        return None

    def rodovia_no_texto(self, texto: str) -> str | None:
        """Procura um nome popular de rodovia em texto livre."""
        t = normalizar_busca(texto)
        for apelido, codigo in sorted(self.apelidos.items(), key=lambda kv: -len(kv[0])):
            if apelido and len(apelido) >= 5 and apelido in t:
                return codigo
        return None

    def localizar(self, rodovia: str | None, km: float | None) -> Trecho | None:
        if not rodovia:
            return None
        candidatos = [t for t in self.trechos if t.rodovia == rodovia]
        if km is None:
            return candidatos[0] if len(candidatos) == 1 else None
        return next((t for t in candidatos if t.km_inicial <= km <= t.km_final), None)

    def opera_rodovia(self, rodovia: str | None) -> bool:
        return any(t.rodovia == rodovia for t in self.trechos)

    def __len__(self) -> int:
        return len(self.trechos)
