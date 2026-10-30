"""Linha de comando do robô de conservação rodoviária (Motiva).  Uso:  python -m motiva_rpa <comando>

Comandos principais
  demo        processa as amostras (e-mails .eml + planilhas) sem precisar de Gmail
  monitorar   robô contínuo: Gmail + pasta de entrada, a cada N segundos
  emails      lê o Gmail uma vez
  arquivos    lê a pasta de entrada uma vez
  listar      mostra as solicitações registradas
  exportar    gera saida/solicitacoes.xlsx (registro + histórico)
  testar-ia   classifica um texto e mostra o JSON devolvido pela IA
  avaliar     mede a IA nos casos rotulados (avaliacao/casos_rotulados.jsonl)
  voz         simula uma ligação chamando as funções do agente de voz
  api         sobe a API HTTP (http://localhost:8000/docs)
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from pathlib import Path

from .config import RAIZ, carregar_config
from .modelos import Resultado

AMOSTRAS = RAIZ / "amostras"


def _console_utf8() -> None:
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _log(verboso: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verboso else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    for barulhento in ("httpx", "openai", "httpcore", "urllib3"):
        logging.getLogger(barulhento).setLevel(logging.WARNING)


def _tabela(linhas: list[list[str]], cabecalho: list[str]) -> str:
    larguras = [max(len(str(x)) for x in col) for col in zip(cabecalho, *linhas)] if linhas else [len(c) for c in cabecalho]
    fmt = "  ".join(f"{{:<{w}}}" for w in larguras)
    saida = [fmt.format(*cabecalho), fmt.format(*["-" * w for w in larguras])]
    saida += [fmt.format(*[str(x) for x in l]) for l in linhas]
    return "\n".join(saida)


def _resumo(resultados: list[Resultado]) -> None:
    if not resultados:
        print("\nNenhuma solicitação nova.")
        return
    linhas = []
    for r in resultados:
        marca = "dup" if r.duplicado else ("compl" if r.complemento else ("ERRO" if r.erro else "nova"))
        linhas.append([r.protocolo or "—", marca, r.status, r.categoria or "—", r.urgencia or "—",
                       (r.equipe or "—")[:45], (r.motor_ia or "—")[:28]])
    print()
    print(_tabela(linhas, ["protocolo", "tipo", "status", "categoria", "urgência", "responsável", "motor"]))
    print(f"\n{len(resultados)} resultado(s).")


def _pipeline(cfg=None):
    from .pipeline import Pipeline

    return Pipeline.criar(cfg)


# ---------------------------------------------------------------------------


def cmd_demo(args) -> None:
    from .captura_email import interpretar_email, email_para_entradas
    from .robo import ciclo_pasta, processar_pasta_eml

    cfg = carregar_config()
    if args.limpar:
        for alvo in (cfg.banco_dados,):
            if alvo.exists():
                alvo.unlink()
        shutil.rmtree(cfg.pasta_saida / "emails", ignore_errors=True)
        print("Banco e e-mails de saída anteriores apagados.")
    if cfg.envio_modo == "smtp" and not cfg.envio_redirecionar_para:
        print("Atenção: ENVIO_MODO=smtp sem ENVIO_REDIRECIONAR_PARA — a demo usa endereços fictícios; "
              "usando modo arquivo nesta execução.")
        cfg.envio_modo = "arquivo"
    p = _pipeline(cfg)
    print(f"Motor de IA: {p.motor.nome} · envio: {cfg.envio_modo} · cadastro: {len(p.trechos)} trechos de rodovia\n")

    print("== 1/3  Captura por e-mail (amostras/emails/*.eml) ==")
    resultados = processar_pasta_eml(p, AMOSTRAS / "emails")

    print("\n== 2/3  Captura por arquivo (planilhas copiadas para entrada/) ==")
    for planilha in sorted((AMOSTRAS / "planilhas").glob("*")):
        if planilha.suffix.lower() in (".csv", ".xlsx"):
            shutil.copy(planilha, cfg.pasta_entrada / planilha.name)
    resultados += ciclo_pasta(p, idade_minima_s=0)

    print("\n== 3/3  Resposta de cliente a um pedido de informação ==")
    for modelo in sorted((AMOSTRAS / "emails" / "respostas").glob("*.eml.modelo")):
        bruto = modelo.read_text(encoding="utf-8")
        remetente = next((l.split("<")[-1].rstrip(">").strip() for l in bruto.splitlines() if l.startswith("From:")), "")
        pendente = next((s for s in p.repo.listar("PENDENTE_INFORMACAO") if s.solicitante_email == remetente), None)
        if not pendente:
            print(f"(sem solicitação pendente de {remetente}; resposta não enviada)")
            continue
        e = interpretar_email(bruto.replace("{{PROTOCOLO}}", pendente.protocolo).encode("utf-8"))
        resultados += p.processar_lote(email_para_entradas(e))

    _resumo(resultados)
    destino = p.repo.exportar_excel(cfg.pasta_saida / "solicitacoes.xlsx")
    print(f"\nRegistro exportado: {destino.relative_to(RAIZ)}")
    print(f"E-mails gerados:    {(cfg.pasta_saida / 'emails').relative_to(RAIZ)}/ "
          f"({len(list((cfg.pasta_saida / 'emails').glob('*.eml')))} arquivos .eml)")


def cmd_emails(args) -> None:
    from .robo import ciclo_gmail

    _resumo(ciclo_gmail(_pipeline()))


def cmd_arquivos(args) -> None:
    from .robo import ciclo_pasta

    _resumo(ciclo_pasta(_pipeline(), idade_minima_s=0))


def cmd_monitorar(args) -> None:
    from .robo import monitorar

    cfg = carregar_config()
    p = _pipeline(cfg)
    print(f"Motor de IA: {p.motor.nome} · envio: {cfg.envio_modo} · Gmail: "
          f"{'sim' if cfg.gmail_configurado and not args.sem_gmail else 'não'} · pasta: {cfg.pasta_entrada}")
    try:
        monitorar(p, args.intervalo or cfg.monitor_intervalo, usar_gmail=not args.sem_gmail,
                  usar_pasta=not args.sem_pasta, ao_processar=_resumo)
    except KeyboardInterrupt:
        print("\nRobô parado.")


def cmd_listar(args) -> None:
    from .registro import Repositorio

    repo = Repositorio(carregar_config().banco_dados)
    linhas = [[s.protocolo, s.status, s.categoria, s.urgencia, s.localizacao[:38],
               (s.equipe_nome or "—")[:40], f"{s.confianca:.0%}"]
              for s in repo.listar(args.status, args.limite)]
    print(_tabela(linhas, ["protocolo", "status", "categoria", "urgência", "local", "responsável", "conf."]))


def cmd_exportar(args) -> None:
    from .registro import Repositorio

    cfg = carregar_config()
    destino = Repositorio(cfg.banco_dados).exportar_excel(Path(args.arquivo) if args.arquivo else cfg.pasta_saida / "solicitacoes.xlsx")
    print(f"Exportado: {destino}")


def cmd_testar_ia(args) -> None:
    from .ia import criar_motor
    from .modelos import Entrada

    cfg = carregar_config()
    motor = criar_motor(cfg)
    texto = args.texto or ("Aqui é o Rogério da Inspeção 03. Tem um buraco grande na faixa da direita da "
                           "Bandeirantes, km 72 mais 400, sentido capital, uns 80 centímetros. Os carros estão "
                           "desviando em cima da hora. Rádio canal 4.")
    r = motor.analisar(Entrada(canal="teste", origem_ref="teste", texto=texto))
    print(f"Motor: {r.motor} ({r.segundos:.1f} s)")
    if r.aviso:
        print(f"Aviso: {r.aviso}")
    print(json.dumps(r.analise.model_dump(), ensure_ascii=False, indent=2))


def cmd_avaliar(args) -> None:
    from .avaliacao import avaliar, carregar_casos, relatorio_markdown
    from .ia import ClassificadorOpenAI, ClassificadorRegras

    cfg = carregar_config()
    casos = carregar_casos(RAIZ / "avaliacao" / "casos_rotulados.jsonl")
    motores = []
    if args.motor in ("regras", "ambos"):
        motores.append(ClassificadorRegras())
    if args.motor in ("openai", "ambos"):
        if not cfg.openai_configurada:
            print("OPENAI_API_KEY não configurada — pulando o motor OpenAI.")
        else:
            motores.append(ClassificadorOpenAI(cfg.openai_api_key, cfg.openai_modelo, cfg.arquivo_prompt,
                                               cfg.openai_reasoning_effort))
    for m in motores:
        print(f"Avaliando {m.nome} em {len(casos)} casos…")
        r = avaliar(m, casos)
        nome = "regras" if m.nome == "regras" else "openai"
        destino = RAIZ / "avaliacao" / f"resultado_{nome}.md"
        destino.write_text(relatorio_markdown(r), encoding="utf-8")
        cr_ok, cr_tot = r["criticas_detectadas"]
        print(f"  categoria {r['acc_categoria']:.0%} · urgência {r['acc_urgencia_final']:.0%} · "
              f"críticas {cr_ok}/{cr_tot} · local {r['acc_local']:.0%} · {r['tempo_medio_s']:.2f} s/caso")
        print(f"  relatório: {destino.relative_to(RAIZ)}")


def cmd_voz(args) -> None:
    from . import agente_voz

    agente_voz.configurar(_pipeline())

    def chamar(nome: str, argumentos: dict) -> dict:
        print(f"\nAgente de voz → {nome}({json.dumps(argumentos, ensure_ascii=False)})")
        resposta = agente_voz.executar_ferramenta(nome, argumentos)
        print(json.dumps(resposta, ensure_ascii=False, indent=2))
        return resposta

    # 1. Inspetor relata sem dizer o km
    r = chamar("registrar_solicitacao_conservacao", {
        "descricao": args.descricao or "Placa de velocidade máxima 100 caída no acostamento, logo depois do viaduto.",
        "rodovia": "Castello Branco", "sentido": "interior",
        "nome_profissional": "Inspetor Marcos", "equipe_origem": "Inspeção 07",
    })
    # 2. O agente pergunta o km e complementa
    if r.get("status") == "PENDENTE_INFORMACAO" and r.get("protocolo"):
        r = chamar("complementar_solicitacao", {"protocolo": r["protocolo"], "informacao": "É no km 45 mais 300."})
    # 3. O que mais está aberto nesse trecho?
    chamar("consultar_pendencias_trecho", {"rodovia": "SP-280", "km": "45", "raio_km": 10})
    # 4. Consulta pelo protocolo
    if r.get("protocolo"):
        chamar("consultar_solicitacao", {"protocolo": r["protocolo"]})


def cmd_api(args) -> None:
    import uvicorn

    print(f"API em http://localhost:{args.porta}/docs")
    uvicorn.run("motiva_rpa.api:app", host=args.host, port=args.porta, reload=False)


def main(argv: list[str] | None = None) -> None:
    _console_utf8()
    parser = argparse.ArgumentParser(prog="python -m motiva_rpa", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-v", "--verboso", action="store_true")
    sub = parser.add_subparsers(dest="comando", required=True)

    p = sub.add_parser("demo", help="processa as amostras sem Gmail")
    p.add_argument("--limpar", action="store_true", help="apaga o banco e os e-mails gerados antes")
    p.set_defaults(func=cmd_demo)

    sub.add_parser("emails", help="lê o Gmail uma vez").set_defaults(func=cmd_emails)
    sub.add_parser("arquivos", help="lê a pasta de entrada uma vez").set_defaults(func=cmd_arquivos)

    p = sub.add_parser("monitorar", help="robô contínuo")
    p.add_argument("--intervalo", type=int, help="segundos entre ciclos")
    p.add_argument("--sem-gmail", action="store_true")
    p.add_argument("--sem-pasta", action="store_true")
    p.set_defaults(func=cmd_monitorar)

    p = sub.add_parser("listar", help="mostra o registro")
    p.add_argument("--status")
    p.add_argument("--limite", type=int, default=50)
    p.set_defaults(func=cmd_listar)

    p = sub.add_parser("exportar", help="gera planilha do registro")
    p.add_argument("--arquivo")
    p.set_defaults(func=cmd_exportar)

    p = sub.add_parser("testar-ia", help="classifica um texto")
    p.add_argument("texto", nargs="?")
    p.set_defaults(func=cmd_testar_ia)

    p = sub.add_parser("avaliar", help="mede a IA nos casos rotulados")
    p.add_argument("--motor", choices=["regras", "openai", "ambos"], default="ambos")
    p.set_defaults(func=cmd_avaliar)

    p = sub.add_parser("voz", help="simula o agente de voz")
    p.add_argument("--descricao")
    p.set_defaults(func=cmd_voz)

    p = sub.add_parser("api", help="sobe a API HTTP")
    p.add_argument("--porta", type=int, default=8000)
    p.add_argument("--host", default="127.0.0.1")
    p.set_defaults(func=cmd_api)

    args = parser.parse_args(argv)
    _log(args.verboso)
    args.func(args)


if __name__ == "__main__":
    main()
