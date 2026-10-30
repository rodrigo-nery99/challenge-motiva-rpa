"""Funções de texto usadas na captura, na validação e no motor de regras."""

from __future__ import annotations

import html
import re
import unicodedata

UFS = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA",
    "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
}

NOMES_UF = {
    "acre": "AC", "alagoas": "AL", "amapa": "AP", "amazonas": "AM", "bahia": "BA",
    "ceara": "CE", "distrito federal": "DF", "espirito santo": "ES", "goias": "GO",
    "maranhao": "MA", "mato grosso do sul": "MS", "mato grosso": "MT", "minas gerais": "MG",
    "para": "PA", "paraiba": "PB", "parana": "PR", "pernambuco": "PE", "piaui": "PI",
    "rio de janeiro": "RJ", "rio grande do norte": "RN", "rio grande do sul": "RS",
    "rondonia": "RO", "roraima": "RR", "santa catarina": "SC", "sao paulo": "SP",
    "sergipe": "SE", "tocantins": "TO",
}

# Rodovia: SP-280, SP 280, sp280, BR-116, BR 116/SP
_RE_RODOVIA = re.compile(r"\b(SP|BR|RJ|RS|SC|PR|MG|MS|MT|GO|BA|PE|ES)\s?[-–]?\s?(\d{2,3})\b", re.IGNORECASE)
# km 54+300 | km 54,3 | km 54.300 | km54 | quilômetro 54
_RE_KM = re.compile(
    r"\b(?:km|quil[oô]metro)\s*[.:]?\s*(\d{1,4})(?:\s*(?:(?:\+|\bmais\b)\s*(\d{1,3})|[,.](\d{1,3})))?",
    re.IGNORECASE,
)
_RE_CPF = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")
RE_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
RE_TELEFONE = re.compile(r"(?:\+?55\s?)?\(?\b\d{2}\)?[\s.-]?9?\d{4}[\s.-]?\d{4}\b")
RE_PROTOCOLO = re.compile(r"\bCNS-\d{4}-\d{6}\b", re.IGNORECASE)

SENTIDOS_TEXTO = [
    ("capital", "CAPITAL"), ("sao paulo", "CAPITAL"), ("interior", "INTERIOR"), ("litoral", "LITORAL"),
    ("norte", "NORTE"), ("sul", "SUL"), ("leste", "LESTE"), ("oeste", "OESTE"),
    ("ambos", "AMBOS"), ("dois sentidos", "AMBOS"),
]


def sem_acentos(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalizar_busca(texto: str) -> str:
    """Minúsculas, sem acentos e com espaços simples — para comparar termos."""
    t = sem_acentos(texto or "").lower()
    t = re.sub(r"[-_/]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


# ---------------------------------------------------------------------------
# Rodovia, km e sentido
# ---------------------------------------------------------------------------


def normalizar_codigo_rodovia(valor: object) -> str | None:
    """'sp 280' -> 'SP-280'; 'BR116' -> 'BR-116'. Nomes ('Castello Branco') devolvem None."""
    if valor is None:
        return None
    m = _RE_RODOVIA.search(str(valor))
    if not m:
        return None
    return f"{m.group(1).upper()}-{int(m.group(2)):03d}"


def encontrar_rodovias(texto: str) -> list[str]:
    achadas: list[str] = []
    for uf, numero in _RE_RODOVIA.findall(texto or ""):
        codigo = f"{uf.upper()}-{int(numero):03d}"
        if codigo not in achadas:
            achadas.append(codigo)
    return achadas


def converter_km(valor: object) -> float | None:
    """'km 54+300' -> 54.3; '54,3' -> 54.3; 101 -> 101.0; '54.300' -> 54.3. Fora de 0–1500: None."""
    if valor is None:
        return None
    if isinstance(valor, (int, float)) and not isinstance(valor, bool):
        if valor != valor:  # NaN
            return None
        km = float(valor)
    else:
        t = str(valor).strip().lower().replace("km", "").replace(" ", "")
        if not t:
            return None
        m = re.fullmatch(r"(\d{1,4})(?:\+(\d{1,3}))?", t)
        if m:
            km = int(m.group(1)) + (int(m.group(2).ljust(3, "0")) / 1000 if m.group(2) else 0)
        else:
            m = re.fullmatch(r"(\d{1,4})[,.](\d{1,3})", t)
            if not m:
                return None
            km = int(m.group(1)) + int(m.group(2).ljust(3, "0")) / 1000
    km = round(km, 3)
    return km if 0 <= km <= 1500 else None


def encontrar_km(texto: str) -> float | None:
    """Primeiro km do texto, preferindo o mais preciso ('km 72' no assunto e 'km 72+400' no corpo -> 72.4)."""
    valores = []
    for inteiro, metros_mais, decimal in _RE_KM.findall(texto or ""):
        fracao = metros_mais or decimal
        km = converter_km(f"{inteiro}+{fracao}" if fracao else inteiro)
        if km is not None:
            valores.append((km, bool(fracao)))
    if not valores:
        return None
    primeiro = valores[0][0]
    preciso = next((km for km, tem_fracao in valores if tem_fracao and int(km) == int(primeiro)), None)
    return preciso if preciso is not None else primeiro


_MINUSCULAS = {"de", "da", "do", "das", "dos", "e"}


def _titulo(texto: str) -> str:
    palavras = texto.strip().split()
    return " ".join(p if (p in _MINUSCULAS and n) else p.capitalize() for n, p in enumerate(palavras))


def normalizar_sentido(valor: object) -> str | None:
    """'sentido capital' -> 'CAPITAL'; 'N' -> 'NORTE'; 'rio de janeiro' -> 'Rio de Janeiro'."""
    if valor is None:
        return None
    bruto = str(valor).strip()
    t = normalizar_busca(bruto)
    t = re.sub(r"^(sentido|pista|direcao)\s+", "", t)
    if not t:
        return None
    if t.upper() in {"N", "S", "L", "O"}:
        return {"N": "NORTE", "S": "SUL", "L": "LESTE", "O": "OESTE"}[t.upper()]
    for termo, sentido in SENTIDOS_TEXTO:
        if re.search(rf"\b{termo}\b", t):
            return sentido
    limpo = re.sub(r"^(sentido|pista|direção|direcao)\s+", "", bruto, flags=re.IGNORECASE)
    return _titulo(limpo.lower())[:40] or None


def encontrar_sentido(texto: str) -> str | None:
    m = re.search(r"\bsentido\s+(?:a\s+|ao\s+|o\s+|para\s+)?([A-Za-zÀ-ÿ]+(?:\s+(?:de|do|da|dos)?\s*[A-Za-zÀ-ÿ]+)?)",
                  texto or "", re.IGNORECASE)
    return normalizar_sentido(m.group(1)) if m else None


# ---------------------------------------------------------------------------
# Outros
# ---------------------------------------------------------------------------


def normalizar_uf(valor: object) -> str | None:
    if valor is None:
        return None
    t = normalizar_busca(str(valor))
    if not t:
        return None
    if t.upper() in UFS:
        return t.upper()
    return NOMES_UF.get(t)


def mascarar_dados_sensiveis(texto: str) -> str:
    """Remove CPFs antes de enviar o texto para a IA (minimização de dados, LGPD)."""
    return _RE_CPF.sub("[CPF removido]", texto or "")


def html_para_texto(conteudo_html: str) -> str:
    t = re.sub(r"(?is)<(script|style).*?</\1>", " ", conteudo_html)
    t = re.sub(r"(?i)<br\s*/?>", "\n", t)
    t = re.sub(r"(?i)</(p|div|tr|li|h\d)>", "\n", t)
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(t)
    t = re.sub(r"[ \t\xa0]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n\n", t).strip()


_MARCAS_CITACAO = [
    re.compile(r"^\s*Em .{5,120}escreveu:\s*$", re.IGNORECASE),
    re.compile(r"^\s*On .{5,120}wrote:\s*$", re.IGNORECASE),
    re.compile(r"^\s*-{2,}\s*(Mensagem original|Original Message)\s*-{2,}", re.IGNORECASE),
    re.compile(r"^\s*(De|From):\s.*@.*", re.IGNORECASE),  # cabeçalho de e-mail encaminhado/citado
]


def remover_citacoes(texto: str) -> str:
    """Corta o histórico citado de respostas ("Em ... escreveu:", linhas com ">")."""
    linhas = []
    for linha in (texto or "").splitlines():
        if any(p.match(linha) for p in _MARCAS_CITACAO):
            break
        if linha.lstrip().startswith(">"):
            continue
        linhas.append(linha)
    return "\n".join(linhas).strip()


def limitar(texto: str | None, tamanho: int) -> str:
    t = re.sub(r"\s+", " ", texto or "").strip()
    return t if len(t) <= tamanho else t[: tamanho - 1].rstrip() + "…"
