"""Interpretação das solicitações.

Dois motores com a mesma interface ``analisar(entrada) -> AnaliseSolicitacao``:

- ``ClassificadorOpenAI``: o motor principal. Envia o texto para a OpenAI com
  Structured Outputs, então a resposta sempre segue o schema ``AnaliseSolicitacao``.
- ``ClassificadorRegras``: palavras-chave e expressões regulares. Serve de
  contingência (sem chave, sem internet, erro da API) e de linha de base na
  avaliação — mostra o que a IA acrescenta em relação a regras fixas.

``MotorIA`` tenta a OpenAI e, se ela falhar, usa as regras e registra o motivo.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .modelos import AnaliseSolicitacao, Entrada
from .utils_texto import (
    RE_EMAIL,
    RE_TELEFONE,
    encontrar_km,
    encontrar_rodovias,
    encontrar_sentido,
    limitar,
    normalizar_busca,
)

log = logging.getLogger(__name__)


DIAS_SEMANA = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]


class ErroIA(Exception):
    pass


class Classificador(Protocol):
    nome: str

    def analisar(self, entrada: Entrada) -> AnaliseSolicitacao: ...


def montar_mensagem_usuario(entrada: Entrada) -> str:
    """Texto enviado à IA: metadados da captura + conteúdo delimitado."""
    partes = [
        f"CANAL: {entrada.canal}",
        f"RECEBIDO EM: {entrada.recebido_em:%Y-%m-%d %H:%M} ({DIAS_SEMANA[entrada.recebido_em.weekday()]})",
    ]
    if entrada.remetente_nome or entrada.remetente_email:
        partes.append(f"REMETENTE: {entrada.remetente_nome or ''} <{entrada.remetente_email or ''}>".strip())
    if entrada.assunto:
        partes.append(f"ASSUNTO: {entrada.assunto}")
    if entrada.arquivo_origem:
        partes.append(f"ARQUIVO DE ORIGEM: {entrada.arquivo_origem}")
    if entrada.contexto:
        partes.append(f"CONTEXTO (mensagem que acompanhou a planilha):\n<<<\n{limitar(entrada.contexto, 800)}\n>>>")
    partes.append(f"CONTEÚDO DA SOLICITAÇÃO:\n<<<\n{entrada.texto.strip()}\n>>>")
    return "\n".join(partes)


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------


class ClassificadorOpenAI:
    def __init__(
        self,
        api_key: str,
        modelo: str,
        arquivo_prompt: Path,
        reasoning_effort: str = "",
        cliente=None,
        timeout: float = 60.0,
    ):
        if cliente is None:
            from openai import OpenAI  # import tardio: o projeto roda sem a lib em modo regras

            cliente = OpenAI(api_key=api_key, timeout=timeout, max_retries=2)
        self.cliente = cliente
        self.modelo = modelo
        self.reasoning_effort = reasoning_effort
        self.prompt_sistema = Path(arquivo_prompt).read_text(encoding="utf-8")
        self.nome = f"openai:{modelo}"

    def analisar(self, entrada: Entrada) -> AnaliseSolicitacao:
        mensagens = [
            {"role": "system", "content": self.prompt_sistema},
            {"role": "user", "content": montar_mensagem_usuario(entrada)},
        ]
        extras = {"reasoning_effort": self.reasoning_effort} if self.reasoning_effort else {}
        # SDKs mais antigos só têm o parse em client.beta
        parse = getattr(self.cliente.chat.completions, "parse", None) or self.cliente.beta.chat.completions.parse
        try:
            resposta = parse(model=self.modelo, messages=mensagens, response_format=AnaliseSolicitacao, **extras)
        except Exception as exc:  # modelo sem suporte a reasoning_effort: tenta de novo sem ele
            if extras and "reasoning" in str(exc).lower():
                log.warning("Modelo %s não aceita reasoning_effort; repetindo sem o parâmetro.", self.modelo)
                self.reasoning_effort = ""
                resposta = parse(model=self.modelo, messages=mensagens, response_format=AnaliseSolicitacao)
            else:
                raise
        mensagem = resposta.choices[0].message
        if getattr(mensagem, "refusal", None):
            raise ErroIA(f"A IA recusou a análise: {mensagem.refusal}")
        if mensagem.parsed is None:
            raise ErroIA("A IA não devolveu uma análise válida.")
        return mensagem.parsed


# ---------------------------------------------------------------------------
# Motor de regras (contingência e linha de base)
# ---------------------------------------------------------------------------

TERMOS_CATEGORIA: dict[str, dict[str, float]] = {
    "PAVIMENTO": {
        "buraco": 3, "panela": 3, "cratera": 3, "trinca": 2, "rachadura no asfalto": 3, "afundamento": 3,
        "afundou": 2, "ondulacao": 2, "desnivel": 2, "remendo": 2, "asfalto": 2, "pavimento": 3,
    },
    "SINALIZACAO": {
        "placa": 3, "sinalizacao": 2, "pintura": 2, "faixa apagada": 3, "tacha": 3, "tachao": 3,
        "olho de gato": 3, "tachoes": 3, "refletiv": 2, "painel de mensagem": 3, "pmv": 3, "apagada": 1,
    },
    "DISPOSITIVOS_SEGURANCA": {
        "defensa": 4, "guard rail": 4, "guardrail": 4, "barreira de concreto": 4, "new jersey": 4,
        "atenuador": 4, "cerca": 2, "alambrado": 3, "tela antiofuscante": 4,
    },
    "DRENAGEM_TALUDES": {
        "bueiro": 3, "canaleta": 3, "sarjeta": 3, "drenagem": 3, "alagamento": 3, "alagad": 2, "agua acumulada": 3,
        "erosao": 3, "talude": 3, "deslizamento": 3, "queda de barreira": 4, "barreira caiu": 4, "encosta": 3,
    },
    "ILUMINACAO": {
        "iluminacao": 3, "poste": 3, "luminaria": 3, "lampada": 2, "apagado": 1.5, "escuro": 1.5,
        "fio": 2, "fiacao": 3, "cabo eletrico": 3,
    },
    "VEGETACAO_LIMPEZA": {
        "rocada": 4, "mato": 3, "vegetacao": 3, "arvore": 3, "galho": 3, "entulho": 3, "lixo": 3,
        "animal morto": 4, "carcaca": 4, "oleo na pista": 3, "objeto": 2, "carga caida": 3,
    },
    "OCORRENCIA_TRAFEGO": {
        "acidente": 3, "colisao": 3, "capotou": 4, "engavetamento": 4, "veiculo quebrado": 4,
        "carro quebrado": 4, "veiculo parado": 3, "caminhao parado": 3, "animal na pista": 4,
        "cavalo": 3, "boi": 3, "pedestre": 3, "pegando fogo": 3, "congestionamento": 3, "guincho": 2,
    },
    "FORA_ESCOPO": {
        "pedagio": 2, "tarifa": 3, "tag": 2, "sem parar": 3, "cobranca": 3, "cobrado": 3, "reembolso": 3,
        "estorno": 3, "elogio": 3, "vaga de emprego": 3, "curriculo": 3, "promocao": 3, "desconto": 2,
    },
}

TERMOS_RISCO = [
    "obstruindo", "bloqueando a faixa", "na pista", "queda de barreira", "barreira caiu", "cratera",
    "fio caido", "fios caidos", "defensa arrancada", "pista alagada", "agua cobrindo", "incendio",
    "pegando fogo", "acidente", "capotou",
]
TERMOS_ALTA = ["faixa de rolamento", "faixa 1", "faixa 2", "faixa 3", "pista expressa", "regulamentacao",
               "velocidade maxima", "risco de queda", "erosao avancando", "trevo", "passarela"]
TERMOS_BAIXA = ["lixo", "rocada de rotina", "limpeza", "pichad"]


def _pontuar(texto_norm: str) -> dict[str, float]:
    return {
        categoria: sum(peso for termo, peso in termos.items() if termo in texto_norm)
        for categoria, termos in TERMOS_CATEGORIA.items()
    }


class ClassificadorRegras:
    nome = "regras"

    def analisar(self, entrada: Entrada) -> AnaliseSolicitacao:
        bruto = "\n".join(filter(None, [entrada.assunto, entrada.texto]))
        t = normalizar_busca(bruto)
        pontos = _pontuar(t)

        total = sum(pontos.values())
        if total == 0:
            categoria, confianca = "FORA_ESCOPO", 0.3
        else:
            categoria = max(pontos, key=pontos.get)
            confianca = round(min(0.8, 0.35 + 0.45 * pontos[categoria] / total), 2)

        t_risco = t.replace("nada na pista", "").replace("sem acidente", "")
        risco = any(x in t_risco for x in TERMOS_RISCO) and categoria != "FORA_ESCOPO"
        if risco:
            urgencia = "CRITICA"
        elif categoria == "FORA_ESCOPO" or any(x in t for x in TERMOS_BAIXA):
            urgencia = "BAIXA"
        elif any(x in t for x in TERMOS_ALTA):
            urgencia = "ALTA"
        else:
            urgencia = "MEDIA"

        rodovias = encontrar_rodovias(bruto)
        if "faixa da esquerda" in t or "faixa 1" in t:
            local = "faixa 1"
        elif "acostamento" in t:
            local = "acostamento"
        elif "canteiro" in t:
            local = "canteiro central"
        else:
            local = None

        if any(x in t for x in ("inspetor", "inspecao", "viatura", "ronda")):
            tipo = "INSPECAO_TRAFEGO"
        elif any(x in t for x in ("equipe", "encarregado", "conservacao", "frente de obra")):
            tipo = "EQUIPE_CAMPO"
        elif "cco" in t.split() or "centro de controle" in t:
            tipo = "CCO"
        elif any(x in t for x in ("passei", "estava dirigindo", "sou usuario", "moro", "meu carro")):
            tipo = "USUARIO"
        else:
            tipo = "OUTRO"

        termos = [termo for termo in TERMOS_CATEGORIA.get(categoria, {}) if termo in t][:5]
        telefones = RE_TELEFONE.findall(entrada.texto)
        emails = [e for e in RE_EMAIL.findall(entrada.texto) if e != entrada.remetente_email]

        return AnaliseSolicitacao(
            categoria=categoria,
            urgencia=urgencia,
            confianca=confianca,
            justificativa=(
                f"Motor de regras: termos encontrados {termos}." if termos else "Motor de regras: nenhum termo conhecido."
            ),
            resumo=limitar(entrada.texto, 200),
            rodovia=rodovias[0] if rodovias else None,
            km=encontrar_km(bruto),
            sentido=encontrar_sentido(bruto),
            local_na_via=local,
            referencia=None,
            cidade=None,
            uf=None,
            obstrucao_pista=any(x in t_risco for x in ("obstruindo", "bloqueando a faixa", "na pista")) and categoria != "FORA_ESCOPO",
            risco_imediato=risco,
            interdicao_necessaria=True if "interdi" in t else None,
            multiplos_locais=len(rodovias) > 1,
            dimensao=None,
            problemas=[],
            servicos_solicitados=[],
            data_preferencial=None,
            tipo_solicitante=tipo,
            solicitante_nome=None,
            solicitante_email=emails[0] if emails else None,
            solicitante_telefone=telefones[0] if telefones else None,
            equipe_origem=None,
        )


# ---------------------------------------------------------------------------
# Motor com contingência
# ---------------------------------------------------------------------------


@dataclass
class ResultadoIA:
    analise: AnaliseSolicitacao
    motor: str
    segundos: float
    aviso: str | None = None


class MotorIA:
    def __init__(self, principal: Classificador | None, reserva: Classificador | None = None):
        if principal is None and reserva is None:
            raise ValueError("É preciso pelo menos um classificador.")
        self.principal = principal
        self.reserva = reserva

    @property
    def nome(self) -> str:
        return self.principal.nome if self.principal else f"{self.reserva.nome} (sem OpenAI)"

    def analisar(self, entrada: Entrada) -> ResultadoIA:
        inicio = time.perf_counter()
        if self.principal is not None:
            try:
                analise = self.principal.analisar(entrada)
                return ResultadoIA(analise, self.principal.nome, time.perf_counter() - inicio)
            except Exception as exc:
                if self.reserva is None:
                    raise
                aviso = f"OpenAI indisponível ({type(exc).__name__}: {limitar(str(exc), 160)}); usado o motor de regras."
                log.warning(aviso)
                analise = self.reserva.analisar(entrada)
                return ResultadoIA(analise, f"{self.reserva.nome} (contingência)", time.perf_counter() - inicio, aviso)
        analise = self.reserva.analisar(entrada)
        return ResultadoIA(
            analise,
            f"{self.reserva.nome} (sem OpenAI)",
            time.perf_counter() - inicio,
            "OPENAI_API_KEY não configurada; usado o motor de regras.",
        )


def criar_motor(config) -> MotorIA:
    principal = None
    if config.openai_configurada:
        principal = ClassificadorOpenAI(
            api_key=config.openai_api_key,
            modelo=config.openai_modelo,
            arquivo_prompt=config.arquivo_prompt,
            reasoning_effort=config.openai_reasoning_effort,
        )
    reserva = ClassificadorRegras() if (config.permitir_fallback or principal is None) else None
    return MotorIA(principal, reserva)
