"""Montagem e envio dos e-mails do processo.

Tipos de mensagem:
- encaminhamento ao responsável (ou à triagem);
- confirmação ao solicitante, com protocolo e prazo;
- pedido de informação quando faltam dados;
- atualização ao responsável quando chega um complemento.

Modo ``arquivo`` grava cada e-mail como .eml em saida/emails/ (abre no Outlook,
Thunderbird ou no próprio navegador arrastando para o Gmail). Modo ``smtp`` envia
pelo Gmail. Todo e-mail sai com o cabeçalho X-Motiva-RPA, que o robô usa para
não ler as próprias mensagens.
"""

from __future__ import annotations

import html
import logging
import re
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage
from email.utils import format_datetime, formataddr, make_msgid
from pathlib import Path

from .modelos import CATEGORIAS, STATUS, TIPOS_SOLICITANTE, URGENCIAS, Solicitacao, agora
from .roteamento import Destino

log = logging.getLogger(__name__)

CABECALHO_ROBO = "X-Motiva-RPA"
NOME_REMETENTE = "Robô de Conservação Motiva (protótipo acadêmico)"
CORES_URGENCIA = {"CRITICA": "#b42318", "ALTA": "#c4320a", "MEDIA": "#b54708", "BAIXA": "#067647"}


def formatar_data(iso: str | datetime | None) -> str:
    if not iso:
        return "—"
    d = iso if isinstance(iso, datetime) else datetime.fromisoformat(iso)
    return d.strftime("%d/%m/%Y %H:%M")


def _v(valor) -> str:
    if valor is None or valor == "" or valor == []:
        return "—"
    if isinstance(valor, bool):
        return "Sim" if valor else "Não"
    if isinstance(valor, int) and not isinstance(valor, bool):
        return f"{valor:,}".replace(",", ".")
    return str(valor)


def _tabela(s: Solicitacao) -> list[tuple[str, str]]:
    municipio = "/".join(x for x in [s.cidade, s.uf] if x)
    return [
        ("Protocolo", s.protocolo or "—"),
        ("Categoria", CATEGORIAS.get(s.categoria, s.categoria)),
        ("Urgência", URGENCIAS.get(s.urgencia, s.urgencia)),
        ("Localização", s.localizacao),
        ("Referência", _v(s.referencia)),
        ("Município", municipio or "—"),
        ("Trecho / concessão", _v(s.trecho)),
        ("Base de conservação", _v(s.base_conservacao)),
        ("Obstrução da pista", _v(s.obstrucao_pista)),
        ("Risco imediato", _v(s.risco_imediato)),
        ("Precisa de interdição", _v(s.interdicao_necessaria)),
        ("Dimensão / extensão", _v(s.dimensao)),
        ("Possível duplicata de", _v(s.possivel_duplicata)),
        ("Solicitante", " · ".join(x for x in [s.solicitante_nome, s.solicitante_email, s.solicitante_telefone] if x) or "—"),
        ("Tipo de solicitante", TIPOS_SOLICITANTE.get(s.tipo_solicitante, s.tipo_solicitante)),
        ("Equipe / viatura de origem", _v(s.equipe_origem)),
        ("Canal / origem", f"{s.canal} · {s.arquivo_origem or s.remetente_email or s.origem_ref}"),
        ("Recebido em", formatar_data(s.recebido_em)),
    ]


def _html(titulo: str, cor: str, paragrafos: list[str], tabela: list[tuple[str, str]] | None = None,
          extras: list[tuple[str, str]] | None = None) -> str:
    esc = html.escape
    partes = [
        "<div style=\"font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#1d2939;max-width:680px\">",
        f"<div style=\"border-left:6px solid {cor};padding:8px 14px;margin-bottom:14px;background:#f9fafb\">"
        f"<strong style=\"font-size:16px\">{esc(titulo)}</strong></div>",
    ]
    partes += [f"<p style=\"margin:0 0 10px\">{p}</p>" for p in paragrafos]
    if tabela:
        partes.append("<table style=\"border-collapse:collapse;width:100%;margin:8px 0 14px\">")
        for rotulo, valor in tabela:
            partes.append(
                "<tr><td style=\"padding:5px 8px;border-bottom:1px solid #eaecf0;color:#475467;width:34%\">"
                f"{esc(rotulo)}</td><td style=\"padding:5px 8px;border-bottom:1px solid #eaecf0\">{esc(valor)}</td></tr>"
            )
        partes.append("</table>")
    for rotulo, bloco in extras or []:
        partes.append(
            f"<p style=\"margin:12px 0 4px;color:#475467\"><strong>{esc(rotulo)}</strong></p>"
            f"<div style=\"white-space:pre-wrap;background:#f2f4f7;padding:10px;border-radius:4px\">{esc(bloco)}</div>"
        )
    partes.append(
        "<p style=\"margin-top:18px;color:#98a2b3;font-size:12px\">Mensagem automática do robô de conservação "
        "rodoviária (protótipo acadêmico — Challenge Motiva).</p></div>"
    )
    return "".join(partes)


def _texto(titulo: str, paragrafos: list[str], tabela=None, extras=None) -> str:
    limpos = [html.unescape(re.sub(r"<[^>]+>", "", re.sub(r"<br\s*/?>", "\n", p))) for p in paragrafos]
    linhas = [titulo, "=" * len(titulo), "", *limpos, ""]
    for rotulo, valor in tabela or []:
        linhas.append(f"{rotulo:<20} {valor}")
    for rotulo, bloco in extras or []:
        linhas += ["", f"{rotulo}:", bloco]
    return "\n".join(linhas)


class Notificador:
    def __init__(self, modo: str, pasta_saida: Path, usuario: str = "", senha_app: str = "",
                 redirecionar_para: str = "", smtp_host: str = "smtp.gmail.com", smtp_porta: int = 465):
        self.modo = modo
        self.pasta = Path(pasta_saida) / "emails"
        self.pasta.mkdir(parents=True, exist_ok=True)
        self.usuario = usuario
        self.senha_app = senha_app
        self.redirecionar_para = redirecionar_para
        self.smtp_host = smtp_host
        self.smtp_porta = smtp_porta
        if modo == "smtp" and not (usuario and senha_app):
            raise ValueError("ENVIO_MODO=smtp exige GMAIL_USUARIO e GMAIL_SENHA_APP no .env")

    # -- montagem ----------------------------------------------------------
    def _mensagem(self, tipo: str, para: str, assunto: str, texto: str, corpo_html: str,
                  copias: list[str] | None = None, responder_para: str | None = None) -> EmailMessage:
        msg = EmailMessage()
        remetente = self.usuario or "robo.conservacao@example.com"
        msg["From"] = formataddr((NOME_REMETENTE, remetente))
        copias = [c for c in (copias or []) if c]
        if self.redirecionar_para:
            originais = ", ".join([para, *copias])
            msg["To"] = self.redirecionar_para
            msg["Subject"] = f"{assunto} [para: {originais}]"
        else:
            msg["To"] = para
            if copias:
                msg["Cc"] = ", ".join(copias)
            msg["Subject"] = assunto
        if responder_para:
            msg["Reply-To"] = responder_para
        msg["Message-ID"] = make_msgid(domain="motiva-rpa.local")
        msg["Date"] = format_datetime(agora())
        msg[CABECALHO_ROBO] = tipo
        msg["Auto-Submitted"] = "auto-generated"
        msg.set_content(texto)
        msg.add_alternative(corpo_html, subtype="html")
        return msg

    def encaminhamento(self, s: Solicitacao, d: Destino) -> EmailMessage:
        triagem = s.status == "EM_TRIAGEM"
        prefixo = "[TRIAGEM] " if triagem else ""
        assunto = (f"{prefixo}[{s.protocolo}][{URGENCIAS[s.urgencia].upper()}] "
                   f"{CATEGORIAS[s.categoria].split(' (')[0]} — {s.localizacao}")
        paragrafos = [
            f"Nova solicitação para <strong>{html.escape(d.equipe_nome)}</strong>.",
            f"<strong>Atendimento até {formatar_data(d.prazo)}</strong> (SLA de {d.sla_horas} h).",
            f"<strong>Resumo:</strong> {html.escape(s.resumo)}",
        ]
        if triagem:
            paragrafos.insert(1, f"<strong>Por que está em triagem:</strong> {html.escape(s.motivo_status)} "
                                 "Confirme a categoria e encaminhe à equipe correta.")
        paragrafos.append(
            f"<strong>Análise automática</strong> — motor {html.escape(s.motor_ia)}, confiança {s.confianca:.0%}: "
            f"{html.escape(s.justificativa)}"
        )
        if s.solicitante_email:
            paragrafos.append("Responder este e-mail fala direto com o solicitante.")
        extras = []
        if s.avisos:
            extras.append(("Avisos e regras aplicadas", "\n".join(f"• {a}" for a in s.avisos)))
        extras.append(("Mensagem original", s.texto_original))
        tabela = _tabela(s)
        cor = CORES_URGENCIA.get(s.urgencia, "#475467")
        return self._mensagem(
            "encaminhamento", d.email, assunto,
            _texto(assunto, paragrafos, tabela, extras), _html(assunto, cor, paragrafos, tabela, extras),
            copias=d.copias, responder_para=s.solicitante_email,
        )

    def confirmacao(self, s: Solicitacao, d: Destino) -> EmailMessage:
        assunto = f"[{s.protocolo}] Recebemos sua solicitação — {s.localizacao}"
        nome = (s.solicitante_nome or "").split(" ")[0] or "Olá"
        paragrafos = [
            f"{html.escape(nome)}, recebemos sua solicitação e ela foi registrada com o protocolo "
            f"<strong>{s.protocolo}</strong>.",
            f"Ela foi classificada como <strong>{html.escape(CATEGORIAS[s.categoria])}</strong>, urgência "
            f"<strong>{URGENCIAS[s.urgencia].lower()}</strong>, e encaminhada para "
            f"<strong>{html.escape(d.equipe_nome)}</strong>.",
            f"O prazo de atendimento é até <strong>{formatar_data(d.prazo)}</strong>.",
        ]
        if s.categoria == "FORA_ESCOPO":
            paragrafos[1] = ("Como o assunto não é de conservação da rodovia, encaminhamos para a "
                             f"<strong>{html.escape(d.equipe_nome)}</strong>.")
        if s.urgencia == "CRITICA":
            paragrafos.append("O Centro de Controle Operacional foi avisado. Em caso de risco à vida, ligue "
                              "para o 0800 da concessionária ou para o 190/193.")
        paragrafos.append("Para acrescentar informações, responda este e-mail mantendo o protocolo no assunto.")
        return self._mensagem("confirmacao", s.solicitante_email, assunto,
                              _texto(assunto, paragrafos), _html(assunto, "#1570ef", paragrafos))

    def pedido_informacao(self, s: Solicitacao) -> EmailMessage:
        assunto = f"[{s.protocolo}] Precisamos de mais informações sobre sua solicitação"
        nome = (s.solicitante_nome or "").split(" ")[0] or "Olá"
        itens = "".join(f"<br>• {html.escape(c)}" for c in s.campos_faltantes)
        paragrafos = [
            f"{html.escape(nome)}, registramos sua solicitação com o protocolo <strong>{s.protocolo}</strong>, "
            "mas precisamos de alguns dados para encaminhá-la:" + itens,
            f"Entendemos que se trata de: <em>{html.escape(s.resumo)}</em>",
            "É só <strong>responder este e-mail</strong> com as informações, mantendo o protocolo no assunto. "
            "Assim que chegarem, a solicitação segue automaticamente para a equipe responsável.",
        ]
        return self._mensagem("pedido_informacao", s.solicitante_email, assunto,
                              _texto(assunto, paragrafos), _html(assunto, "#b54708", paragrafos))

    def atualizacao(self, s: Solicitacao, complemento: str) -> EmailMessage:
        assunto = f"[{s.protocolo}] Nova informação do solicitante"
        paragrafos = [f"O solicitante enviou uma informação nova sobre {s.protocolo} "
                      f"({html.escape(CATEGORIAS[s.categoria])}, {html.escape(s.localizacao)})."]
        extras = [("Informação recebida", complemento)]
        return self._mensagem("atualizacao", s.equipe_email, assunto,
                              _texto(assunto, paragrafos, None, extras),
                              _html(assunto, "#475467", paragrafos, None, extras),
                              responder_para=s.solicitante_email)

    # -- envio -------------------------------------------------------------
    def enviar(self, msg: EmailMessage, protocolo: str | None = None) -> str:
        tipo = msg[CABECALHO_ROBO] or "email"
        nome = f"{agora():%Y%m%d-%H%M%S}_{protocolo or 'sem-protocolo'}_{tipo}"
        caminho = self.pasta / f"{nome}.eml"
        n = 1
        while caminho.exists():
            n += 1
            caminho = self.pasta / f"{nome}_{n}.eml"
        caminho.write_bytes(bytes(msg))  # sempre guarda uma cópia (evidência para a demo)
        if self.modo == "smtp":
            contexto = ssl.create_default_context()
            with smtplib.SMTP_SSL(self.smtp_host, self.smtp_porta, context=contexto, timeout=30) as smtp:
                smtp.login(self.usuario, self.senha_app)
                smtp.send_message(msg)
            log.info("E-mail '%s' enviado para %s", tipo, msg["To"])
            return f"enviado para {msg['To']}"
        log.info("E-mail '%s' gravado em %s", tipo, caminho.name)
        return f"gravado em {caminho.name}"


__all__ = ["Notificador", "CABECALHO_ROBO", "STATUS", "formatar_data"]
