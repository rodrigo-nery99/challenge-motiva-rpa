"""Avaliação da IA com casos rotulados (avaliacao/casos_rotulados.jsonl).

Mede, para cada motor (OpenAI e regras):
- acerto da categoria;
- acerto da urgência final (IA + regras de negócio);
- acerto da localização extraída (rodovia + km);
- tempo médio por solicitação.

Gera um relatório em Markdown em avaliacao/resultado_<motor>.md.
"""

from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from pathlib import Path

from .config import RAIZ
from .trechos import CadastroTrechos
from .ia import Classificador, ResultadoIA
from .modelos import CATEGORIAS, ORDEM_URGENCIA, Entrada
from .regras_negocio import construir_registro


def _local(rodovia, km) -> str | None:
    if not rodovia and km is None:
        return None
    return f"{rodovia or '?'} km {float(km):g}" if km is not None else f"{rodovia} km ?"


def carregar_casos(caminho: Path) -> list[dict]:
    with Path(caminho).open(encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip() and not l.lstrip().startswith("//")]


def avaliar(classificador: Classificador, casos: list[dict]) -> dict:
    trechos = CadastroTrechos(RAIZ / "dados" / "trechos_motiva.csv")
    linhas = []
    for caso in casos:
        entrada = Entrada(canal=caso.get("canal", "email"), origem_ref=caso["id"], texto=caso["texto"],
                          assunto=caso.get("assunto"))
        inicio = time.perf_counter()
        try:
            analise = classificador.analisar(entrada)
            erro = None
        except Exception as exc:  # registra e segue
            analise, erro = None, f"{type(exc).__name__}: {exc}"
        segundos = time.perf_counter() - inicio
        if analise is None:
            linhas.append({"caso": caso, "erro": erro, "segundos": segundos})
            continue
        s = construir_registro(entrada, ResultadoIA(analise, classificador.nome, segundos), trechos)
        linhas.append({
            "caso": caso, "erro": None, "segundos": segundos,
            "categoria": analise.categoria, "urgencia_ia": analise.urgencia, "urgencia_final": s.urgencia,
            "local": _local(s.rodovia, s.km), "confianca": analise.confianca,
        })

    validas = [l for l in linhas if not l["erro"]]
    n = len(validas) or 1

    def taxa(cond) -> float:
        return sum(1 for l in validas if cond(l)) / n

    def distancia(a: str, b: str) -> int:
        return abs(ORDEM_URGENCIA.index(a) - ORDEM_URGENCIA.index(b))

    confusao: dict[str, Counter] = defaultdict(Counter)
    for l in validas:
        confusao[l["caso"]["categoria"]][l["categoria"]] += 1

    return {
        "motor": classificador.nome,
        "total": len(linhas),
        "erros_execucao": len(linhas) - len(validas),
        "acc_categoria": taxa(lambda l: l["categoria"] == l["caso"]["categoria"]),
        "acc_urgencia_ia": taxa(lambda l: l["urgencia_ia"] == l["caso"]["urgencia"]),
        "acc_urgencia_final": taxa(lambda l: l["urgencia_final"] == l["caso"]["urgencia"]),
        "urgencia_ate_1_nivel": taxa(lambda l: distancia(l["urgencia_final"], l["caso"]["urgencia"]) <= 1),
        "criticas_detectadas": (
            sum(1 for l in validas if l["caso"]["urgencia"] == "CRITICA" and l["urgencia_final"] == "CRITICA"),
            sum(1 for l in validas if l["caso"]["urgencia"] == "CRITICA"),
        ),
        "acc_local": taxa(lambda l: l["local"] == _local(l["caso"].get("rodovia"), l["caso"].get("km"))),
        "tempo_medio_s": sum(l["segundos"] for l in linhas) / (len(linhas) or 1),
        "confusao": {k: dict(v) for k, v in confusao.items()},
        "linhas": linhas,
    }


def relatorio_markdown(r: dict) -> str:
    pct = lambda x: f"{x:.0%}"  # noqa: E731
    criticas_ok, criticas_total = r["criticas_detectadas"]
    out = [
        f"# Avaliação — motor `{r['motor']}`",
        "",
        f"Casos: **{r['total']}** · erros de execução: {r['erros_execucao']} · tempo médio: {r['tempo_medio_s']:.2f} s",
        "",
        "| Métrica | Resultado |",
        "|---|---|",
        f"| Categoria correta | {pct(r['acc_categoria'])} |",
        f"| Urgência correta (só IA) | {pct(r['acc_urgencia_ia'])} |",
        f"| Urgência correta (IA + regras de negócio) | {pct(r['acc_urgencia_final'])} |",
        f"| Urgência a no máximo 1 nível | {pct(r['urgencia_ate_1_nivel'])} |",
        f"| Casos críticos detectados | {criticas_ok} de {criticas_total} |",
        f"| Localização correta (rodovia + km) | {pct(r['acc_local'])} |",
        "",
        "## Matriz de confusão da categoria (linha = esperado, coluna = previsto)",
        "",
    ]
    cats = list(CATEGORIAS)
    curtas = {c: c.split("_")[0][:10] for c in cats}
    out.append("| esperado \\ previsto | " + " | ".join(curtas[c] for c in cats) + " |")
    out.append("|---" * (len(cats) + 1) + "|")
    for esperado in cats:
        if esperado not in r["confusao"]:
            continue
        linha = r["confusao"][esperado]
        out.append(f"| {curtas[esperado]} | " + " | ".join(str(linha.get(c, "")) for c in cats) + " |")
    out += ["", "## Divergências", "", "| Caso | Esperado | Previsto | Texto |", "|---|---|---|---|"]
    for l in r["linhas"]:
        c = l["caso"]
        if l["erro"]:
            out.append(f"| {c['id']} | — | ERRO: {l['erro'][:60]} | |")
            continue
        difs = []
        if l["categoria"] != c["categoria"]:
            difs.append(("categoria", c["categoria"], l["categoria"]))
        if l["urgencia_final"] != c["urgencia"]:
            difs.append(("urgência", c["urgencia"], l["urgencia_final"]))
        esperado_local = _local(c.get("rodovia"), c.get("km"))
        if l["local"] != esperado_local:
            difs.append(("local", esperado_local, l["local"]))
        for campo, esp, prev in difs:
            texto = c["texto"].replace("\n", " ").replace("|", "/")[:70]
            out.append(f"| {c['id']} | {campo}: {esp} | {prev} | {texto}… |")
    return "\n".join(out) + "\n"
