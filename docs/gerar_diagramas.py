"""Gera os desenhos do processo ANTES (AS-IS) e DEPOIS (TO-BE) em SVG.

Notação inspirada em BPMN: raias (quem faz), tarefas (retângulos), decisões
(losangos), início/fim (círculos). Para alterar, edite as listas LANES/NODES/EDGES
e rode:  python docs/gerar_diagramas.py
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from pathlib import Path

PASTA = Path(__file__).resolve().parent

HEADER_W = 150
COL_W = 172
TOP = 70
TASK_W, TASK_H = 148, 66
GW = 34  # meia-diagonal do losango
FONT = "Inter, 'Segoe UI', 'DejaVu Sans', Arial, sans-serif"

COR = {
    "texto": "#1d2939", "suave": "#667085", "linha": "#475467", "raia": "#f8fafc", "raia_alt": "#eef2f6",
    "borda_raia": "#d0d5dd", "tarefa": "#ffffff", "borda": "#98a2b3", "ia": "#eef4ff", "borda_ia": "#3e63dd",
    "robo": "#f0f9ff", "borda_robo": "#0b6bcb", "dor": "#d92d20", "dor_bg": "#fef3f2", "ganho": "#067647",
    "ganho_bg": "#ecfdf3", "inicio": "#12b76a", "fim": "#344054",
}


@dataclass
class No:
    id: str
    raia: int
    col: float
    tipo: str  # inicio | fim | tarefa | ia | robo | decisao
    texto: str
    marca: str = ""  # número do ponto de dor/ganho
    texto_acima: bool = False  # rótulo da decisão acima do losango (quando a saída é por baixo)

    def centro(self, raias) -> tuple[float, float]:
        x = HEADER_W + 30 + self.col * COL_W + COL_W / 2
        y0 = TOP + sum(r[1] for r in raias[: self.raia])
        return x, y0 + raias[self.raia][1] / 2

    def ancora(self, lado: str, raias) -> tuple[float, float]:
        x, y = self.centro(raias)
        if self.tipo in ("inicio", "fim"):
            meia_l = meia_a = 20
        elif self.tipo == "decisao":
            meia_l = meia_a = GW
        else:
            meia_l, meia_a = TASK_W / 2, TASK_H / 2
        return {"esq": (x - meia_l, y), "dir": (x + meia_l, y), "topo": (x, y - meia_a), "base": (x, y + meia_a)}[lado]


def _texto(x, y, texto, tamanho=12.5, peso=400, cor=None, ancora="middle"):
    linhas = texto.split("\n")
    alt = tamanho * 1.25
    y0 = y - alt * (len(linhas) - 1) / 2 + tamanho * 0.35
    spans = "".join(
        f'<tspan x="{x:.1f}" y="{y0 + i * alt:.1f}">{escape(l)}</tspan>' for i, l in enumerate(linhas)
    )
    return (f'<text font-family="{FONT}" font-size="{tamanho}" font-weight="{peso}" fill="{cor or COR["texto"]}" '
            f'text-anchor="{ancora}">{spans}</text>')


def _no(n: No, raias, tema: str) -> str:
    x, y = n.centro(raias)
    out = []
    if n.tipo in ("inicio", "fim"):
        cor = COR["inicio"] if n.tipo == "inicio" else COR["fim"]
        esp = 2 if n.tipo == "inicio" else 4.5
        out.append(f'<circle cx="{x}" cy="{y}" r="18" fill="#fff" stroke="{cor}" stroke-width="{esp}"/>')
        out.append(_texto(x, y + 38, n.texto, 11.5, 500, COR["suave"]))
    elif n.tipo == "decisao":
        pts = f"{x},{y - GW} {x + GW},{y} {x},{y + GW} {x - GW},{y}"
        out.append(f'<polygon points="{pts}" fill="#fffbeb" stroke="#b54708" stroke-width="1.5"/>')
        ty = y - GW - 20 if n.texto_acima else y + GW + 20
        out.append(_texto(x, ty, n.texto, 11.5, 600, "#93370d"))
    else:
        fundo, borda, esp = {
            "tarefa": (COR["tarefa"], COR["borda"], 1.2),
            "ia": (COR["ia"], COR["borda_ia"], 2),
            "robo": (COR["robo"], COR["borda_robo"], 1.4),
        }[n.tipo]
        out.append(f'<rect x="{x - TASK_W / 2}" y="{y - TASK_H / 2}" width="{TASK_W}" height="{TASK_H}" rx="10" '
                   f'fill="{fundo}" stroke="{borda}" stroke-width="{esp}"/>')
        if n.tipo == "ia":
            out.append(f'<rect x="{x + TASK_W / 2 - 30}" y="{y - TASK_H / 2 - 9}" width="34" height="18" rx="9" '
                       f'fill="{COR["borda_ia"]}"/>')
            out.append(_texto(x + TASK_W / 2 - 13, y - TASK_H / 2, "IA", 10.5, 700, "#fff"))
        out.append(_texto(x, y, n.texto, 11.8, 500))
    if n.marca:
        cor, bg = (COR["dor"], COR["dor_bg"]) if tema == "dor" else (COR["ganho"], COR["ganho_bg"])
        mx, my = (x - TASK_W / 2 + 2, y - TASK_H / 2 - 2) if n.tipo not in ("decisao", "inicio", "fim") else (x - GW, y - GW)
        out.append(f'<circle cx="{mx}" cy="{my}" r="11" fill="{bg}" stroke="{cor}" stroke-width="1.6"/>')
        out.append(_texto(mx, my, n.marca, 11, 700, cor))
    return "\n".join(out)


def _aresta(nos, raias, a, b, rotulo="", rota="auto", tracejada=False, saida=None, entrada=None, desvio=0):
    na, nb = nos[a], nos[b]
    ax, ay = na.centro(raias)
    bx, by = nb.centro(raias)
    if rota == "auto":
        rota = "reta" if abs(ay - by) < 1 else ("vertical" if abs(ax - bx) < 1 else "hvh")
    if rota == "reta":
        pts = [na.ancora("dir", raias), nb.ancora("esq", raias)]
    elif rota == "vertical":
        pts = [na.ancora("base" if by > ay else "topo", raias), nb.ancora("topo" if by > ay else "base", raias)]
    elif rota == "hvh":  # sai pela direita, desce/sobe no meio, entra pela esquerda
        p1, p2 = na.ancora("dir", raias), nb.ancora("esq", raias)
        mx = (p1[0] + p2[0]) / 2 + desvio
        pts = [p1, (mx, p1[1]), (mx, p2[1]), p2]
    elif rota == "vh":  # sai por cima/baixo, depois horizontal até a entrada
        p1 = na.ancora(saida or ("base" if by > ay else "topo"), raias)
        p2 = nb.ancora(entrada or ("esq" if bx > ax else "dir"), raias)
        pts = [p1, (p1[0], p2[1]), p2]
    elif rota == "hv":  # horizontal, depois entra por cima/baixo
        p1 = na.ancora(saida or ("dir" if bx > ax else "esq"), raias)
        p2 = nb.ancora(entrada or ("topo" if by > ay else "base"), raias)
        pts = [p1, (p2[0], p1[1]), p2]
    else:
        raise ValueError(rota)
    d = "M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in pts)
    traco = ' stroke-dasharray="5 4"' if tracejada else ""
    out = [f'<path d="{d}" fill="none" stroke="{COR["linha"]}" stroke-width="1.5"{traco} marker-end="url(#seta)"/>']
    if rotulo:
        (x1, y1), (x2, y2) = pts[0], pts[1]
        lx, ly = (x1 + x2) / 2, (y1 + y2) / 2
        if abs(y1 - y2) < 1:
            ly -= 9
        else:
            lx += 8
        out.append(
            f'<text font-family="{FONT}" font-size="11" font-weight="600" fill="#93370d" paint-order="stroke" '
            f'stroke="#fff" stroke-width="5" stroke-linejoin="round" '
            f'text-anchor="{"middle" if abs(y1 - y2) < 1 else "start"}" x="{lx:.1f}" y="{ly:.1f}">{escape(rotulo)}</text>'
        )
    return "\n".join(out)


def desenhar(titulo, subtitulo, raias, nos_lista, arestas, legenda_titulo, legenda, tema, colunas, destino):
    nos = {n.id: n for n in nos_lista}
    largura = HEADER_W + 60 + colunas * COL_W
    altura_raias = sum(r[1] for r in raias)
    linhas_legenda = (len(legenda) + 1) // 2
    altura = TOP + altura_raias + 60 + linhas_legenda * 24 + 30
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{largura}" height="{altura}" viewBox="0 0 {largura} {altura}">',
        '<defs><marker id="seta" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">'
        f'<path d="M0,0 L10,5 L0,10 z" fill="{COR["linha"]}"/></marker></defs>',
        f'<rect width="{largura}" height="{altura}" fill="#ffffff"/>',
        _texto(24, 30, titulo, 20, 700, ancora="start"),
        _texto(24, 52, subtitulo, 12.5, 400, COR["suave"], ancora="start"),
    ]
    y = TOP
    for i, (nome, alt) in enumerate(raias):
        fundo = COR["raia"] if i % 2 == 0 else COR["raia_alt"]
        svg.append(f'<rect x="20" y="{y}" width="{largura - 40}" height="{alt}" fill="{fundo}" stroke="{COR["borda_raia"]}"/>')
        svg.append(f'<rect x="20" y="{y}" width="{HEADER_W}" height="{alt}" fill="#ffffff" stroke="{COR["borda_raia"]}"/>')
        svg.append(_texto(20 + HEADER_W / 2, y + alt / 2, nome, 12.5, 700))
        y += alt
    for aresta in arestas:
        a, b, *resto = aresta
        opcoes = resto[0] if resto else {}
        svg.append(_aresta(nos, raias, a, b, **opcoes))
    for n in nos_lista:
        svg.append(_no(n, raias, tema))

    cor, bg = (COR["dor"], COR["dor_bg"]) if tema == "dor" else (COR["ganho"], COR["ganho_bg"])
    y = TOP + altura_raias + 34
    svg.append(_texto(24, y, legenda_titulo, 13.5, 700, cor, ancora="start"))
    meia = (largura - 60) / 2
    for i, item in enumerate(legenda):
        cx = 36 + (i % 2) * meia
        cy = y + 26 + (i // 2) * 24
        svg.append(f'<circle cx="{cx}" cy="{cy}" r="10" fill="{bg}" stroke="{cor}" stroke-width="1.5"/>')
        svg.append(_texto(cx, cy, str(i + 1), 10.5, 700, cor))
        svg.append(_texto(cx + 18, cy, item, 12, 400, ancora="start"))
    svg.append("</svg>")
    Path(destino).write_text("\n".join(svg), encoding="utf-8")
    return destino


# ---------------------------------------------------------------------------
# AS-IS
# ---------------------------------------------------------------------------
RAIAS_ASIS = [("Solicitante\n(inspetor, equipe\nde campo, usuário)", 140), ("Analista da central\nde conservação\n(caixa compartilhada)", 150),
              ("Equipe de\nconservação", 130)]
NOS_ASIS = [
    No("ini", 0, 0, "inicio", "Encontra problema\nna rodovia"),
    No("envia", 0, 1, "tarefa", "Envia e-mail, planilha\nde ronda ou liga\npara a central"),
    No("abre", 1, 2, "tarefa", "Abre a caixa de\nentrada (várias\nvezes ao dia)", "1"),
    No("le", 1, 3, "tarefa", "Lê e interpreta cada\ne-mail e cada linha\nda planilha"),
    No("dados", 1, 4, "decisao", "Dados completos?"),
    No("responde", 0, 4, "tarefa", "Responde com os\ndados que faltavam", "6"),
    No("placa", 1, 5, "tarefa", "Descobre trecho e\nconcessão pelo km\nno mapa/sistema"),
    No("define", 1, 6, "tarefa", "Define tipo e\nurgência no olho", "2"),
    No("digita", 1, 7, "tarefa", "Digita na planilha\nde controle", "3"),
    No("encaminha", 1, 8, "tarefa", "Procura o responsável\nna lista e encaminha\npor e-mail", "4"),
    No("liga", 0, 8, "tarefa", "Liga para saber\no andamento", "5"),
    No("recebe", 2, 9, "tarefa", "Recebe e-mail sem\npadrão, sem prazo\ndefinido"),
    No("fim", 2, 10, "fim", "Atende"),
]
ARESTAS_ASIS = [
    ("ini", "envia"),
    ("envia", "abre"),
    ("abre", "le"),
    ("le", "dados"),
    ("dados", "responde", {"rotulo": "não: pede por e-mail", "rota": "vertical"}),
    ("responde", "le", {"rota": "hv", "saida": "esq", "entrada": "topo"}),
    ("dados", "placa", {"rotulo": "sim"}),
    ("placa", "define"),
    ("define", "digita"),
    ("digita", "encaminha"),
    ("encaminha", "recebe"),
    ("recebe", "fim"),
    ("liga", "encaminha", {"rota": "vertical", "tracejada": True}),
]
LEGENDA_ASIS = [
    "Leitura manual: um obstáculo na pista pode levar horas para ser visto.",
    "Urgência no olho: um buraco na faixa espera atrás de uma roçada.",
    "Redigitação de rodovia, km e sentido gera erro e equipe no lugar errado.",
    "Encaminhamento depende de quem conhece a lista de responsáveis.",
    "Sem protocolo nem prazo: o solicitante liga para saber o status.",
    "Relatos repetidos do mesmo buraco viram várias ordens de serviço.",
]

# ---------------------------------------------------------------------------
# TO-BE
# ---------------------------------------------------------------------------
RAIAS_TOBE = [("Solicitante", 130), ("Robô RPA + IA\n(este projeto)", 160), ("Triagem humana\n(só exceções)", 120),
              ("Equipe\nresponsável", 130)]
NOS_TOBE = [
    No("ini", 0, 0, "inicio", "Encontra problema\nna rodovia"),
    No("envia", 0, 1, "tarefa", "Envia e-mail, planilha\nou fala com o\nagente de voz"),
    No("captura", 1, 2, "robo", "Captura automática:\nGmail (IMAP) e\npasta de planilhas", "1"),
    No("separa", 1, 3, "robo", "Separa corpo,\nanexos e linhas\nda planilha"),
    No("ia", 1, 4, "ia", "Classifica e extrai\nos dados (saída\nestruturada)", "2"),
    No("regras", 1, 5, "robo", "Regras: rodovia + km,\ntrecho da concessão,\nsegurança, duplicatas", "3"),
    No("registra", 1, 6, "robo", "Registra com\nprotocolo e\nhistórico", "4"),
    No("confia", 1, 7, "decisao", "Confiança ≥ 60%\ne 1 local?", texto_acima=True),
    No("triagem", 2, 7, "tarefa", "Analista revisa e\nencaminha (e-mail\n[TRIAGEM])", "6"),
    No("completo", 1, 8, "decisao", "Rodovia e km?"),
    No("complementa", 0, 8, "tarefa", "Responde com o\nprotocolo no assunto"),
    No("matriz", 1, 9, "robo", "Define equipe e SLA\npela matriz\n(categoria × concessão)", "5"),
    No("envio", 1, 10, "robo", "E-mail padronizado ao\nresponsável + cópias;\nconfirma ao solicitante"),
    No("acompanha", 0, 11, "fim", "Acompanha pelo\nprotocolo"),
    No("recebe", 3, 10, "tarefa", "Recebe pedido\ncompleto e\npriorizado"),
    No("fim", 3, 11, "fim", "Atende no SLA"),
]
ARESTAS_TOBE = [
    ("ini", "envia"),
    ("envia", "captura"),
    ("captura", "separa"),
    ("separa", "ia"),
    ("ia", "regras"),
    ("regras", "registra"),
    ("registra", "confia"),
    ("confia", "triagem", {"rotulo": "não", "rota": "vertical"}),
    ("confia", "completo", {"rotulo": "sim"}),
    ("completo", "complementa", {"rotulo": "não: pede por e-mail", "rota": "vertical"}),
    ("complementa", "ia", {"rota": "hv", "saida": "esq", "entrada": "topo"}),
    ("completo", "matriz", {"rotulo": "sim"}),
    ("matriz", "envio"),
    ("envio", "acompanha", {"rota": "vh", "saida": "topo", "entrada": "esq"}),
    ("envio", "recebe", {"rota": "vertical"}),
    ("triagem", "recebe", {"rota": "vh", "saida": "base", "entrada": "esq"}),
    ("recebe", "fim"),
]
LEGENDA_TOBE = [
    "Captura contínua: Gmail e pasta verificados a cada minuto.",
    "A IA lê texto livre e planilhas e devolve sempre o mesmo formato.",
    "Segurança primeiro: obstáculo na pista e risco imediato viram crítico.",
    "Protocolo, histórico e planilha exportável: rastreio de ponta a ponta.",
    "Equipe e prazo pela matriz; o CCO acompanha tudo que é crítico.",
    "Pessoas só tratam exceções; duplicatas no mesmo km são sinalizadas.",
]


def exportar_png(*svgs: Path) -> None:
    """Opcional: gera PNG (2x) com o Chromium do Playwright, se estiver instalado."""
    try:
        import asyncio
        import re

        from playwright.async_api import async_playwright
    except ImportError:
        print("Playwright não instalado: só os SVG foram gerados (abra no navegador para ver/exportar).")
        return

    async def _rodar():
        async with async_playwright() as p:
            navegador = await p.chromium.launch()
            pagina = await navegador.new_page(device_scale_factor=2)
            for svg in svgs:
                conteudo = svg.read_text(encoding="utf-8")
                w = int(re.search(r'width="(\d+)"', conteudo).group(1))
                h = int(re.search(r'height="(\d+)"', conteudo).group(1))
                await pagina.set_viewport_size({"width": w, "height": h})
                await pagina.set_content(f"<html><body style='margin:0'>{conteudo}</body></html>")
                await pagina.screenshot(path=str(svg.with_suffix(".png")), full_page=True)
            await navegador.close()

    asyncio.run(_rodar())
    print("PNG gerados.")


def main() -> None:
    a = desenhar("Processo atual (AS-IS) — solicitações de conservação rodoviária",
                 "Premissa do grupo, a validar com a Motiva. Números em vermelho: pontos de dor.",
                 RAIAS_ASIS, NOS_ASIS, ARESTAS_ASIS, "Pontos de dor", LEGENDA_ASIS, "dor", 11,
                 PASTA / "processo_as_is.svg")
    b = desenhar("Processo automatizado (TO-BE) — Sprint 1",
                 "Robô em Python + OpenAI. Números em verde: ganhos. O agente de voz (próximas sprints) usa as mesmas funções.",
                 RAIAS_TOBE, NOS_TOBE, ARESTAS_TOBE, "Ganhos", LEGENDA_TOBE, "ganho", 12,
                 PASTA / "processo_to_be.svg")
    print(f"Gerados: {a.name}, {b.name}")
    exportar_png(a, b)


if __name__ == "__main__":
    main()
