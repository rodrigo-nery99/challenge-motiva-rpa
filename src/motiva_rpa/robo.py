"""Ciclos do robô: ler o Gmail, ler a pasta de entrada e repetir em intervalo."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from .captura_arquivo import MonitorPasta, planilha_para_entradas
from .captura_email import CapturaGmail, email_para_entradas, ler_eml
from .modelos import Resultado, agora
from .pipeline import Pipeline

log = logging.getLogger(__name__)


def ciclo_gmail(pipeline: Pipeline, limite: int = 50) -> list[Resultado]:
    cfg = pipeline.config
    if not cfg.gmail_configurado:
        log.warning("Gmail não configurado (GMAIL_USUARIO / GMAIL_SENHA_APP); captura por e-mail ignorada.")
        return []
    resultados: list[Resultado] = []
    with CapturaGmail(
        cfg.gmail_usuario, cfg.gmail_senha_app, cfg.gmail_pasta_entrada,
        cfg.gmail_marcador_processados, cfg.gmail_marcador_erros, cfg.gmail_filtro_assunto,
    ) as gmail:
        emails = gmail.buscar_nao_lidos(limite)
        log.info("Gmail: %d e-mail(s) não lido(s)", len(emails))
        for e in emails:
            if e.deve_ignorar:
                log.info("Ignorado (%s): %s", e.deve_ignorar, e.assunto)
                gmail.marcar_ignorado(e)
                continue
            try:
                lote = pipeline.processar_lote(email_para_entradas(e))
                resultados += lote
                if any(r.status == "ERRO" for r in lote):
                    gmail.marcar_erro(e)
                else:
                    gmail.marcar_processado(e)
            except Exception:
                log.exception("Erro ao processar o e-mail '%s'", e.assunto)
                gmail.marcar_erro(e)
    return resultados


def processar_pasta_eml(pipeline: Pipeline, pasta: Path) -> list[Resultado]:
    """Processa arquivos .eml de uma pasta (demo offline e testes)."""
    resultados: list[Resultado] = []
    for caminho in sorted(Path(pasta).glob("*.eml")):
        e = ler_eml(caminho)
        if e.deve_ignorar:
            log.info("Ignorado (%s): %s", e.deve_ignorar, caminho.name)
            continue
        resultados += pipeline.processar_lote(email_para_entradas(e))
    return resultados


def ciclo_pasta(pipeline: Pipeline, idade_minima_s: float = 2.0) -> list[Resultado]:
    monitor = MonitorPasta(pipeline.config.pasta_entrada)
    resultados: list[Resultado] = []
    for arquivo in monitor.arquivos_novos(idade_minima_s):
        log.info("Arquivo encontrado: %s", arquivo.name)
        try:
            entradas = planilha_para_entradas(arquivo.read_bytes(), arquivo.name, canal="arquivo")
            log.info("%s: %d linha(s) com solicitação", arquivo.name, len(entradas))
            lote = pipeline.processar_lote(entradas)
            resultados += lote
            monitor.concluir(arquivo)
        except Exception as exc:
            log.exception("Erro ao ler %s", arquivo.name)
            monitor.falhar(arquivo, exc)
    return resultados


def monitorar(pipeline: Pipeline, intervalo: int, usar_gmail: bool = True, usar_pasta: bool = True,
              ao_processar=None) -> None:
    log.info("Robô iniciado: verificando a cada %ds (Ctrl+C para parar)", intervalo)
    while True:
        inicio = agora()
        resultados: list[Resultado] = []
        if usar_gmail:
            try:
                resultados += ciclo_gmail(pipeline)
            except Exception:
                log.exception("Falha no ciclo do Gmail; tentando de novo no próximo ciclo")
        if usar_pasta:
            resultados += ciclo_pasta(pipeline)
        if resultados and ao_processar:
            ao_processar(resultados)
        log.debug("Ciclo de %s concluído", inicio)
        time.sleep(intervalo)
