"""Captura por arquivo: planilhas Excel (.xlsx) ou CSV.

Cada linha da planilha vira uma ``Entrada``. Planilhas reais vêm bagunçadas,
então a leitura é tolerante:
- CSV com ";" ou ",", em UTF-8 ou Windows-1252 (padrão do Excel no Brasil);
- linhas de título antes do cabeçalho (o cabeçalho é localizado automaticamente);
- nomes de coluna variados ("Rodovia", "KM", "Marco km", "Sentido", "Anomalia"…).

A linha inteira vai para a IA como texto; as colunas reconhecidas (rodovia, km,
sentido…) também vão em
``dados_planilha`` e prevalecem sobre a IA quando válidas.
"""

from __future__ import annotations

import hashlib
import io
import logging
import re
import shutil
import time
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from .modelos import Entrada, agora
from .utils_texto import normalizar_busca

log = logging.getLogger(__name__)

EXTENSOES = {".csv", ".xlsx", ".xlsm"}

ALIASES = {
    "rodovia": {"rodovia", "rod", "via", "estrada", "codigo rodovia"},
    "km": {"km", "km local", "quilometro", "km inicial", "marco km", "km ref", "km referencia"},
    "sentido": {"sentido", "pista", "sentido pista", "direcao"},
    "local_na_via": {"faixa", "local na via", "posicao", "local", "localizacao na via"},
    "descricao": {"descricao", "descricao problema", "descricao do problema", "ocorrencia", "problema",
                  "servico", "servico solicitado", "solicitacao", "defeito", "pendencia", "motivo",
                  "anomalia", "patologia", "relato", "manifestacao"},
    "observacoes": {"observacao", "observacoes", "obs", "comentario", "comentarios"},
    "cidade": {"cidade", "municipio", "localidade"},
    "uf": {"uf", "estado"},
    "solicitante_nome": {"solicitante", "contato", "nome", "nome solicitante", "inspetor", "responsavel",
                         "relator", "usuario", "nome usuario", "encarregado"},
    "solicitante_telefone": {"telefone", "celular", "fone", "whatsapp", "tel", "radio"},
    "solicitante_email": {"email", "e mail"},
    "equipe_origem": {"equipe", "viatura", "base", "turma"},
}
_ALIAS_PARA_CAMPO = {alias: campo for campo, aliases in ALIASES.items() for alias in aliases}


def _nome_coluna(valor) -> str:
    return re.sub(r"[^a-z0-9 ]", " ", normalizar_busca(str(valor))).strip()


def _campo(coluna: str) -> str | None:
    return _ALIAS_PARA_CAMPO.get(re.sub(r"\s+", " ", _nome_coluna(coluna)))


def _texto_celula(v) -> str:
    try:
        if v is None or pd.isna(v):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, (datetime, pd.Timestamp)):
        return v.strftime("%Y-%m-%d %H:%M") if (v.hour or v.minute) else v.strftime("%Y-%m-%d")
    if isinstance(v, date):
        return v.isoformat()
    return str(v).strip()


def _localizar_cabecalho(bruto: pd.DataFrame) -> int:
    for i in range(min(15, len(bruto))):
        reconhecidas = sum(1 for v in bruto.iloc[i].tolist() if _texto_celula(v) and _campo(_texto_celula(v)))
        if reconhecidas >= 2:
            return i
    return 0


def _ler_csv(conteudo: bytes) -> pd.DataFrame:
    for codificacao in ("utf-8-sig", "cp1252"):
        try:
            texto = conteudo.decode(codificacao)
            break
        except UnicodeDecodeError:
            continue
    primeira = next((l for l in texto.splitlines() if l.strip()), "")
    sep = ";" if primeira.count(";") >= primeira.count(",") else ","
    tabela = pd.read_csv(io.StringIO(texto), sep=sep, header=None, dtype=str, keep_default_na=False,
                         engine="python", on_bad_lines="skip", skip_blank_lines=False)
    return tabela.replace(r"^\s*$", pd.NA, regex=True)


def ler_planilha(conteudo: bytes, nome_arquivo: str) -> list[tuple[str, pd.DataFrame, int]]:
    """Devolve [(aba, tabela_com_cabecalho, linha_do_cabecalho_no_arquivo)]."""
    ext = Path(nome_arquivo).suffix.lower()
    if ext == ".csv":
        abas = {"csv": _ler_csv(conteudo)}
    elif ext in (".xlsx", ".xlsm"):
        abas = pd.read_excel(io.BytesIO(conteudo), header=None, sheet_name=None, engine="openpyxl")
    else:
        raise ValueError(f"Formato não suportado: {ext} (use .csv ou .xlsx)")

    tabelas = []
    for aba, bruto in abas.items():
        bruto = bruto.dropna(how="all")
        if bruto.empty:
            continue
        i = _localizar_cabecalho(bruto)
        cabecalho: list[str] = []
        for n, v in enumerate(bruto.iloc[i].tolist()):
            nome = _texto_celula(v) or f"coluna_{n + 1}"
            cabecalho.append(nome if nome not in cabecalho else f"{nome}_{n + 1}")
        dados = bruto.iloc[i + 1 :].copy()
        dados.columns = cabecalho
        tabelas.append((str(aba), dados, int(bruto.index[i])))
    return tabelas


def planilha_para_entradas(
    conteudo: bytes,
    nome_arquivo: str,
    canal: str = "arquivo",
    remetente_nome: str | None = None,
    remetente_email: str | None = None,
    contexto: str | None = None,
    recebido_em: datetime | None = None,
) -> list[Entrada]:
    hash_arquivo = hashlib.sha256(conteudo).hexdigest()[:10]
    entradas: list[Entrada] = []
    for aba, tabela, linha_cab in ler_planilha(conteudo, nome_arquivo):
        for indice, linha in tabela.iterrows():
            valores = {str(col): _texto_celula(v) for col, v in linha.items()}
            preenchidos = {c: v for c, v in valores.items() if v}
            if not preenchidos:
                continue
            reconhecidos: dict[str, str] = {}
            for coluna, valor in preenchidos.items():
                campo = _campo(coluna)
                if campo and campo not in reconhecidos:
                    reconhecidos[campo] = valor
            # Linha sem descrição e sem localização (ex.: totais, assinatura) não é solicitação
            if not ({"descricao", "observacoes", "km"} & reconhecidos.keys()) and len(preenchidos) < 3:
                continue

            numero_linha = int(indice) + 1  # número da linha como aparece no Excel
            texto = "\n".join(f"{coluna}: {valor}" for coluna, valor in preenchidos.items())
            entradas.append(
                Entrada(
                    canal=canal,
                    origem_ref=f"{nome_arquivo}#{hash_arquivo}#{aba}#L{numero_linha}",
                    texto=f"Linha {numero_linha} da planilha '{nome_arquivo}' (aba {aba}):\n{texto}",
                    assunto=f"Planilha {nome_arquivo} — linha {numero_linha}",
                    remetente_nome=remetente_nome,
                    remetente_email=remetente_email,
                    recebido_em=recebido_em or agora(),
                    arquivo_origem=f"{nome_arquivo} (linha {numero_linha})",
                    dados_planilha={k: v for k, v in reconhecidos.items() if k not in ("descricao", "observacoes")},
                    contexto=contexto,
                )
            )
    return entradas


class MonitorPasta:
    """Vigia a pasta de entrada; move cada arquivo para processados/ ou erros/."""

    def __init__(self, pasta: Path):
        self.pasta = Path(pasta)
        self.processados = self.pasta / "processados"
        self.erros = self.pasta / "erros"
        for p in (self.pasta, self.processados, self.erros):
            p.mkdir(parents=True, exist_ok=True)

    def arquivos_novos(self, idade_minima_s: float = 2.0) -> list[Path]:
        agora_ts = time.time()
        return sorted(
            p for p in self.pasta.iterdir()
            if p.is_file()
            and p.suffix.lower() in EXTENSOES
            and not p.name.startswith(("~$", "."))
            and agora_ts - p.stat().st_mtime >= idade_minima_s  # evita ler arquivo ainda sendo copiado
        )

    def _mover(self, arquivo: Path, destino: Path) -> Path:
        alvo = destino / f"{agora():%Y%m%d-%H%M%S}_{arquivo.name}"
        shutil.move(str(arquivo), alvo)
        return alvo

    def concluir(self, arquivo: Path) -> Path:
        return self._mover(arquivo, self.processados)

    def falhar(self, arquivo: Path, erro: Exception) -> Path:
        alvo = self._mover(arquivo, self.erros)
        alvo.with_suffix(alvo.suffix + ".erro.txt").write_text(f"{type(erro).__name__}: {erro}\n", encoding="utf-8")
        return alvo
