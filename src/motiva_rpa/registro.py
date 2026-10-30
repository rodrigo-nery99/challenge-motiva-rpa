"""Registro estruturado das solicitações em SQLite (arquivo dados/solicitacoes.db).

Tabelas:
- ``solicitacoes``: uma linha por solicitação, com protocolo, dados extraídos,
  classificação, status e responsável.
- ``historico``: trilha de auditoria (recebida, classificada, encaminhada…).
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import fields
from pathlib import Path

from .modelos import STATUS_ABERTOS, Solicitacao, agora

COLUNAS_JSON = {"campos_faltantes", "avisos", "dados_ia", "copias", "dados_estruturados"}
COLUNAS_BOOL = {"obstrucao_pista", "risco_imediato", "interdicao_necessaria"}

_TIPOS_SQL = {"id": "INTEGER PRIMARY KEY AUTOINCREMENT", "confianca": "REAL", "km": "REAL", "sla_horas": "INTEGER",
              "obstrucao_pista": "INTEGER", "risco_imediato": "INTEGER", "interdicao_necessaria": "INTEGER"}


def _colunas() -> list[str]:
    return [f.name for f in fields(Solicitacao)]


class Repositorio:
    def __init__(self, caminho: Path):
        self.caminho = Path(caminho)
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        self._criar_tabelas()

    @contextmanager
    def _conexao(self):
        con = sqlite3.connect(self.caminho)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        finally:
            con.close()

    def _criar_tabelas(self) -> None:
        defs = ", ".join(f"{c} {_TIPOS_SQL.get(c, 'TEXT')}" for c in _colunas())
        with self._conexao() as con:
            con.execute(f"CREATE TABLE IF NOT EXISTS solicitacoes ({defs})")
            # Banco criado por uma versão anterior: acrescenta as colunas novas
            existentes = {r["name"] for r in con.execute("PRAGMA table_info(solicitacoes)")}
            for c in _colunas():
                if c not in existentes:
                    con.execute(f"ALTER TABLE solicitacoes ADD COLUMN {c} {_TIPOS_SQL.get(c, 'TEXT')}")
            con.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_origem ON solicitacoes(origem_ref)")
            con.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_protocolo ON solicitacoes(protocolo)")
            con.execute("CREATE INDEX IF NOT EXISTS ix_local ON solicitacoes(rodovia, km)")
            con.execute(
                """CREATE TABLE IF NOT EXISTS historico (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    solicitacao_id INTEGER, protocolo TEXT, data TEXT, evento TEXT, detalhe TEXT)"""
            )

    # -- conversão ---------------------------------------------------------
    @staticmethod
    def _para_linha(s: Solicitacao) -> dict:
        linha = s.como_dict()
        for c in COLUNAS_JSON:
            linha[c] = json.dumps(linha[c], ensure_ascii=False)
        for c in COLUNAS_BOOL:
            if linha[c] is not None:
                linha[c] = int(bool(linha[c]))
        return linha

    @staticmethod
    def _de_linha(row: sqlite3.Row) -> Solicitacao:
        d = dict(row)
        for c in COLUNAS_JSON:
            d[c] = json.loads(d[c]) if d.get(c) else ({} if c in ("dados_ia", "dados_estruturados") else [])
        for c in COLUNAS_BOOL:
            if d.get(c) is not None:
                d[c] = bool(d[c])
        return Solicitacao(**d)

    # -- escrita -----------------------------------------------------------
    def inserir(self, s: Solicitacao) -> Solicitacao:
        momento = agora()
        s.criado_em = s.atualizado_em = momento.isoformat()
        linha = self._para_linha(s)
        linha.pop("id")
        linha.pop("protocolo")
        cols = ", ".join(linha)
        marc = ", ".join(f":{c}" for c in linha)
        with self._conexao() as con:
            cur = con.execute(f"INSERT INTO solicitacoes ({cols}) VALUES ({marc})", linha)
            s.id = cur.lastrowid
            s.protocolo = f"CNS-{momento.year}-{s.id:06d}"
            con.execute("UPDATE solicitacoes SET protocolo = ? WHERE id = ?", (s.protocolo, s.id))
        return s

    def atualizar(self, s: Solicitacao) -> Solicitacao:
        s.atualizado_em = agora().isoformat()
        linha = self._para_linha(s)
        sets = ", ".join(f"{c} = :{c}" for c in linha if c != "id")
        with self._conexao() as con:
            con.execute(f"UPDATE solicitacoes SET {sets} WHERE id = :id", linha)
        return s

    def registrar_evento(self, s: Solicitacao, evento: str, detalhe: str = "") -> None:
        with self._conexao() as con:
            con.execute(
                "INSERT INTO historico (solicitacao_id, protocolo, data, evento, detalhe) VALUES (?, ?, ?, ?, ?)",
                (s.id, s.protocolo, agora().isoformat(), evento, detalhe),
            )

    # -- leitura -----------------------------------------------------------
    def existe_origem(self, origem_ref: str) -> Solicitacao | None:
        with self._conexao() as con:
            row = con.execute("SELECT * FROM solicitacoes WHERE origem_ref = ?", (origem_ref,)).fetchone()
        return self._de_linha(row) if row else None

    def origem_ja_registrada_no_historico(self, origem_ref: str) -> bool:
        """Usado para não aplicar duas vezes o mesmo complemento."""
        with self._conexao() as con:
            row = con.execute(
                "SELECT 1 FROM historico WHERE detalhe LIKE ? LIMIT 1", (f"%origem={origem_ref}%",)
            ).fetchone()
        return row is not None

    def por_protocolo(self, protocolo: str) -> Solicitacao | None:
        with self._conexao() as con:
            row = con.execute(
                "SELECT * FROM solicitacoes WHERE upper(protocolo) = upper(?)", (protocolo.strip(),)
            ).fetchone()
        return self._de_linha(row) if row else None

    def abertas_proximas(self, rodovia: str, km: float, raio_km: float = 1.0,
                         excluir_id: int | None = None, limite: int = 10) -> list[Solicitacao]:
        """Solicitações em aberto na mesma rodovia, a até ``raio_km`` do km informado."""
        with self._conexao() as con:
            rows = con.execute(
                """SELECT * FROM solicitacoes
                   WHERE rodovia = ? AND km BETWEEN ? AND ? AND status IN (?, ?, ?) AND id IS NOT ?
                   ORDER BY abs(km - ?), id DESC LIMIT ?""",
                (rodovia, km - raio_km, km + raio_km, *STATUS_ABERTOS, excluir_id, km, limite),
            ).fetchall()
        return [self._de_linha(r) for r in rows]

    def listar(self, status: str | None = None, limite: int = 200) -> list[Solicitacao]:
        sql, params = "SELECT * FROM solicitacoes", []
        if status:
            sql += " WHERE status = ?"
            params.append(status)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limite)
        with self._conexao() as con:
            rows = con.execute(sql, params).fetchall()
        return [self._de_linha(r) for r in rows]

    def historico(self, protocolo: str | None = None) -> list[dict]:
        sql, params = "SELECT * FROM historico", []
        if protocolo:
            sql += " WHERE protocolo = ?"
            params.append(protocolo)
        sql += " ORDER BY id"
        with self._conexao() as con:
            return [dict(r) for r in con.execute(sql, params).fetchall()]

    # -- exportação --------------------------------------------------------
    def exportar_excel(self, destino: Path) -> Path:
        import pandas as pd

        colunas = [
            "protocolo", "recebido_em", "canal", "status", "categoria", "urgencia", "confianca",
            "rodovia", "km", "sentido", "local_na_via", "referencia", "cidade", "uf", "concessao",
            "base_conservacao", "obstrucao_pista", "risco_imediato", "interdicao_necessaria", "dimensao",
            "resumo", "equipe_nome", "equipe_email", "prazo_retorno", "possivel_duplicata",
            "solicitante_nome", "solicitante_email", "solicitante_telefone", "tipo_solicitante",
            "equipe_origem", "campos_faltantes", "avisos", "motor_ia", "justificativa", "origem_ref",
        ]
        linhas = []
        for s in reversed(self.listar(limite=100_000)):
            d = s.como_dict()
            d["campos_faltantes"] = "; ".join(d["campos_faltantes"])
            d["avisos"] = " | ".join(d["avisos"])
            linhas.append({c: d.get(c) for c in colunas})
        destino = Path(destino)
        destino.parent.mkdir(parents=True, exist_ok=True)
        with pd.ExcelWriter(destino, engine="openpyxl") as xl:
            pd.DataFrame(linhas, columns=colunas).to_excel(xl, sheet_name="solicitacoes", index=False)
            pd.DataFrame(self.historico()).to_excel(xl, sheet_name="historico", index=False)
            for aba in xl.sheets.values():
                aba.freeze_panes = "B2"
                for col in aba.columns:
                    largura = max((len(str(c.value)) for c in col[:200] if c.value is not None), default=8)
                    aba.column_dimensions[col[0].column_letter].width = min(max(10, largura + 2), 60)
        return destino
