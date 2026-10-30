"""Funções que o agente de voz (próximas sprints) vai chamar.

O agente conversa com o profissional em campo — inspetor de tráfego, encarregado
de conservação, operador do CCO — entende o relato e chama uma destas funções
(function calling / tools). Elas usam o MESMO pipeline do e-mail e da planilha,
então um relato por voz gera o mesmo registro, protocolo e encaminhamento.

Funções:
- ``registrar_solicitacao_conservacao``: registra um problema novo na rodovia.
- ``consultar_solicitacao``: status por protocolo.
- ``consultar_pendencias_trecho``: o que já está aberto perto de um km
  (evita relatar de novo o mesmo buraco e orienta a equipe em campo).
- ``complementar_solicitacao``: acrescenta informação (ex.: o km que faltou).

Cada resposta traz ``mensagem_para_falar``: um texto curto, pronto para o TTS,
pensado para quem está na beira da rodovia, com ruído e pouco tempo.
``FERRAMENTAS`` tem as definições no formato de tools da OpenAI (Realtime API e
Responses API); ``executar_ferramenta`` é o despachante que o agente chama.

Também ficam expostas por HTTP em api.py (POST /voz/ferramentas/{nome}), para
plataformas de voz que chamam webhooks.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime

from .modelos import CATEGORIAS, SENTIDOS, STATUS, URGENCIAS, Entrada, agora
from .pipeline import Pipeline
from .utils_texto import converter_km

_pipeline: Pipeline | None = None


def configurar(pipeline: Pipeline | None) -> None:
    """Permite injetar um pipeline (testes, API)."""
    global _pipeline
    _pipeline = pipeline


def _p() -> Pipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = Pipeline.criar()
    return _pipeline


# ---------------------------------------------------------------------------
# Texto para fala
# ---------------------------------------------------------------------------


def soletrar(texto: str | None) -> str:
    """'CNS-2026-000042' -> 'C N S, 2 0 2 6, 0 0 0 0 4 2' (o TTS lê caractere por caractere)."""
    if not texto:
        return ""
    return ", ".join(" ".join(bloco) for bloco in texto.replace("-", " ").split())


def km_falado(km: float | None) -> str:
    """54.3 -> 'quilômetro 54 mais 300'; 101 -> 'quilômetro 101'."""
    if km is None:
        return "quilômetro não informado"
    inteiro = int(km)
    metros = round((km - inteiro) * 1000)
    return f"quilômetro {inteiro}" + (f" mais {metros}" if metros else "")


def rodovia_falada(rodovia: str | None) -> str:
    """'SP-280' -> 'S P 280'."""
    if not rodovia:
        return "rodovia não informada"
    sigla, _, numero = rodovia.partition("-")
    return f"{' '.join(sigla)} {int(numero) if numero.isdigit() else numero}"


def local_falado(s) -> str:
    partes = [rodovia_falada(s.rodovia), km_falado(s.km)]
    if s.sentido:
        partes.append(f"sentido {SENTIDOS.get(s.sentido, s.sentido).lower()}")
    return ", ".join(partes)


def _prazo_falado(iso: str | None) -> str:
    if not iso:
        return ""
    d = datetime.fromisoformat(iso)
    hoje = agora().date()
    dias = (d.date() - hoje).days
    dia = "hoje" if dias == 0 else ("amanhã" if dias == 1 else f"dia {d:%d/%m}")
    return f"{dia} às {d:%H:%M}"


# ---------------------------------------------------------------------------
# Funções chamadas pelo agente
# ---------------------------------------------------------------------------


def registrar_solicitacao_conservacao(
    descricao: str,
    rodovia: str | None = None,
    km: str | float | None = None,
    sentido: str | None = None,
    local_na_via: str | None = None,
    referencia: str | None = None,
    nome_profissional: str | None = None,
    equipe_origem: str | None = None,
    telefone: str | None = None,
    id_chamada: str | None = None,
) -> dict:
    """Registra um problema na rodovia relatado por voz e encaminha à equipe responsável."""
    linhas = [f"Relato por voz do profissional em campo: {descricao.strip()}"]
    for rotulo, valor in [
        ("Rodovia", rodovia), ("Km", km), ("Sentido", sentido), ("Posição na via", local_na_via),
        ("Referência", referencia), ("Profissional", nome_profissional), ("Equipe/viatura", equipe_origem),
        ("Telefone/rádio", telefone),
    ]:
        if valor not in (None, ""):
            linhas.append(f"{rotulo}: {valor}")
    dados = {k: str(v) for k, v in {
        "rodovia": rodovia, "km": km, "sentido": sentido, "local_na_via": local_na_via,
        "solicitante_nome": nome_profissional, "solicitante_telefone": telefone, "equipe_origem": equipe_origem,
    }.items() if v not in (None, "")}

    entrada = Entrada(
        canal="voz",
        origem_ref=f"voz:{id_chamada or uuid.uuid4().hex}",
        texto="\n".join(linhas),
        assunto="Relato recebido pelo agente de voz",
        remetente_nome=nome_profissional,
        dados_planilha=dados,
    )
    r = _p().processar(entrada)
    s = _p().repo.por_protocolo(r.protocolo) if r.protocolo else None
    resposta = {
        "sucesso": s is not None,
        "protocolo": r.protocolo,
        "protocolo_soletrado": soletrar(r.protocolo),
        "status": r.status,
        "categoria": r.categoria,
        "urgencia": r.urgencia,
        "equipe_responsavel": r.equipe,
        "prazo_atendimento": r.prazo_retorno,
        "localizacao": s.localizacao if s else None,
        "campos_faltantes": s.campos_faltantes if s else [],
        "possivel_duplicata": s.possivel_duplicata if s else None,
    }
    if s is None:
        resposta["mensagem_para_falar"] = "Não consegui registrar agora. Passe o relato ao CCO pelo rádio."
        return resposta
    if s.status == "PENDENTE_INFORMACAO":
        resposta["mensagem_para_falar"] = (
            f"Anotei com o protocolo {soletrar(s.protocolo)}. Para encaminhar, preciso de: "
            f"{' e '.join(s.campos_faltantes)}. Pode me informar?"
        )
        return resposta
    fala = (f"Registrado: {CATEGORIAS[s.categoria].split(' (')[0].lower()}, {local_falado(s)}. "
            f"Protocolo {soletrar(s.protocolo)}. Encaminhado para {s.equipe_nome}, "
            f"atendimento até {_prazo_falado(s.prazo_retorno)}.")
    if s.possivel_duplicata:
        fala += f" Atenção: já existe a solicitação {soletrar(s.possivel_duplicata)} aberta perto deste ponto."
    if s.urgencia == "CRITICA":
        fala += " O CCO foi avisado. Sinalize o local se for seguro e mantenha distância da pista."
    resposta["mensagem_para_falar"] = fala
    return resposta


def consultar_solicitacao(protocolo: str) -> dict:
    """Consulta o status de uma solicitação pelo protocolo."""
    repo = _p().repo
    s = repo.por_protocolo((protocolo or "").replace(" ", "").upper())
    if s is None:
        return {
            "encontrada": False,
            "mensagem_para_falar": "Não encontrei esse protocolo. Pode repetir, letra por letra?",
        }
    historico = repo.historico(s.protocolo)
    situacao = {
        "ENCAMINHADA": f"está com {s.equipe_nome}, com atendimento previsto até {_prazo_falado(s.prazo_retorno)}.",
        "EM_TRIAGEM": f"está em análise na {s.equipe_nome}.",
        "PENDENTE_INFORMACAO": f"está aguardando informações. Falta: {' e '.join(s.campos_faltantes)}.",
        "CONCLUIDA": "foi concluída.",
        "CANCELADA": "foi cancelada.",
    }.get(s.status, f"está com status {s.status}.")
    return {
        "encontrada": True,
        "protocolo": s.protocolo,
        "protocolo_soletrado": soletrar(s.protocolo),
        "status": s.status,
        "status_descricao": STATUS.get(s.status, s.status),
        "categoria": CATEGORIAS.get(s.categoria, s.categoria),
        "urgencia": URGENCIAS.get(s.urgencia, s.urgencia),
        "localizacao": s.localizacao,
        "equipe_responsavel": s.equipe_nome,
        "prazo_atendimento": s.prazo_retorno,
        "aberta_em": s.recebido_em,
        "ultimo_evento": historico[-1]["evento"] if historico else None,
        "campos_faltantes": s.campos_faltantes,
        "mensagem_para_falar": f"A solicitação {soletrar(s.protocolo)}, em {local_falado(s)}, {situacao}",
    }


def consultar_pendencias_trecho(rodovia: str, km: str | float, raio_km: float = 5.0) -> dict:
    """Lista solicitações em aberto perto de um km — para a equipe saber o que já foi relatado."""
    p = _p()
    codigo = p.trechos.codigo_rodovia(rodovia)
    km_num = converter_km(km)
    if not codigo or km_num is None:
        return {"sucesso": False, "mensagem_para_falar": "Não entendi a rodovia ou o quilômetro. Pode repetir?"}
    abertas = p.repo.abertas_proximas(codigo, km_num, float(raio_km), limite=20)
    itens = [
        {
            "protocolo": s.protocolo, "categoria": s.categoria, "urgencia": s.urgencia,
            "localizacao": s.localizacao, "status": s.status, "equipe": s.equipe_nome, "resumo": s.resumo,
        }
        for s in abertas
    ]
    if not abertas:
        fala = f"Não há solicitações abertas na {rodovia_falada(codigo)} entre o km {km_num - raio_km:g} e o {km_num + raio_km:g}."
    else:
        primeiras = abertas[:3]
        descricoes = "; ".join(
            f"{CATEGORIAS[s.categoria].split(' (')[0].lower()} no {km_falado(s.km)}, urgência {URGENCIAS[s.urgencia].lower()}"
            for s in primeiras
        )
        plural = len(abertas) > 1
        fala = (f"Há {len(abertas)} {'solicitações abertas' if plural else 'solicitação aberta'} "
                f"perto daí: {descricoes}.")
        if len(abertas) > 3:
            fala += f" E mais {len(abertas) - 3}."
    return {"sucesso": True, "rodovia": codigo, "km": km_num, "raio_km": raio_km, "total": len(itens),
            "solicitacoes": itens, "mensagem_para_falar": fala}


def complementar_solicitacao(protocolo: str, informacao: str, id_chamada: str | None = None) -> dict:
    """Acrescenta informação a uma solicitação existente (ex.: o km ou o sentido que faltavam)."""
    p = _p()
    s = p.repo.por_protocolo((protocolo or "").replace(" ", "").upper())
    if s is None:
        return {"sucesso": False, "mensagem_para_falar": "Não encontrei esse protocolo. Pode repetir?"}
    entrada = Entrada(
        canal="voz",
        origem_ref=f"voz-complemento:{id_chamada or uuid.uuid4().hex}",
        texto=informacao,
        assunto=f"Complemento por voz {s.protocolo}",
    )
    r = p.complementar(s, entrada)
    resposta = consultar_solicitacao(s.protocolo)
    resposta["sucesso"] = True
    resposta["status"] = r.status
    resposta["mensagem_para_falar"] = "Obrigado, anotei. " + resposta["mensagem_para_falar"]
    atualizada = p.repo.por_protocolo(s.protocolo)
    if atualizada and atualizada.possivel_duplicata:
        resposta["possivel_duplicata"] = atualizada.possivel_duplicata
        resposta["mensagem_para_falar"] += (
            f" Atenção: já existe a solicitação {soletrar(atualizada.possivel_duplicata)} aberta perto deste ponto."
        )
    return resposta


# ---------------------------------------------------------------------------
# Definições das ferramentas (formato OpenAI Realtime / Responses API)
# ---------------------------------------------------------------------------

FERRAMENTAS = [
    {
        "type": "function",
        "name": "registrar_solicitacao_conservacao",
        "description": (
            "Registra um problema de conservação na rodovia (buraco, placa, defensa, drenagem, talude, "
            "iluminação, vegetação, objeto na pista) relatado por um profissional em campo e encaminha à "
            "equipe responsável. Antes de chamar, confirme a rodovia, o km e o sentido."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "descricao": {"type": "string", "description": "O problema nas palavras do profissional, com tamanho e posição."},
                "rodovia": {"type": "string", "description": "Código (SP-280) ou nome (Castello Branco)."},
                "km": {"type": "string", "description": "Quilômetro, ex.: '45+300' ou '45,3'."},
                "sentido": {"type": "string", "description": "Ex.: capital, interior, norte, sul."},
                "local_na_via": {"type": "string", "description": "Faixa 1/2/3, acostamento, canteiro, alça, ponte…"},
                "referencia": {"type": "string", "description": "Ponto de referência (pedágio, viaduto, posto)."},
                "nome_profissional": {"type": "string"},
                "equipe_origem": {"type": "string", "description": "Viatura, equipe ou base de quem relata."},
                "telefone": {"type": "string", "description": "Telefone ou canal de rádio para retorno."},
            },
            "required": ["descricao"],
        },
    },
    {
        "type": "function",
        "name": "consultar_solicitacao",
        "description": "Consulta o status de uma solicitação de conservação pelo protocolo (CNS-AAAA-NNNNNN).",
        "parameters": {
            "type": "object",
            "properties": {"protocolo": {"type": "string"}},
            "required": ["protocolo"],
        },
    },
    {
        "type": "function",
        "name": "consultar_pendencias_trecho",
        "description": (
            "Lista as solicitações em aberto perto de um quilômetro. Use antes de registrar um problema "
            "novo, para saber se ele já foi relatado, ou quando o profissional perguntar o que há no trecho."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "rodovia": {"type": "string"},
                "km": {"type": "string"},
                "raio_km": {"type": "number", "description": "Distância em km para cada lado (padrão 5)."},
            },
            "required": ["rodovia", "km"],
        },
    },
    {
        "type": "function",
        "name": "complementar_solicitacao",
        "description": "Acrescenta informação a uma solicitação existente, por exemplo o km, o sentido ou o tamanho do problema.",
        "parameters": {
            "type": "object",
            "properties": {
                "protocolo": {"type": "string"},
                "informacao": {"type": "string", "description": "A informação nova, em texto."},
            },
            "required": ["protocolo", "informacao"],
        },
    },
]

_FUNCOES = {
    "registrar_solicitacao_conservacao": registrar_solicitacao_conservacao,
    "consultar_solicitacao": consultar_solicitacao,
    "consultar_pendencias_trecho": consultar_pendencias_trecho,
    "complementar_solicitacao": complementar_solicitacao,
}


def ferramentas_chat_completions() -> list[dict]:
    """Mesmas ferramentas no formato da Chat Completions API ({"type", "function": {...}})."""
    return [{"type": "function", "function": {k: v for k, v in f.items() if k != "type"}} for f in FERRAMENTAS]


def executar_ferramenta(nome: str, argumentos: str | dict) -> dict:
    """Despachante: o agente de voz passa o nome da função e os argumentos (JSON)."""
    if nome not in _FUNCOES:
        return {"sucesso": False, "erro": f"Ferramenta desconhecida: {nome}"}
    args = json.loads(argumentos) if isinstance(argumentos, str) else dict(argumentos or {})
    try:
        return _FUNCOES[nome](**args)
    except TypeError as exc:
        return {"sucesso": False, "erro": f"Argumentos inválidos: {exc}"}
