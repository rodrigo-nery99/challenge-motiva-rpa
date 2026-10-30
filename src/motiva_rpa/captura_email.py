"""Captura por e-mail: caixa do Gmail via IMAP (ou arquivos .eml para testes).

Fluxo no Gmail:
1. busca e-mails NÃO LIDOS na pasta configurada (lê sem marcar como lido);
2. o pipeline processa;
3. o e-mail é marcado como lido e copiado para o marcador "Motiva-RPA/Processados"
   (ou "Motiva-RPA/Erros" se algo falhar).

Planilhas anexadas (.csv/.xlsx) viram uma entrada por linha; o corpo do e-mail
vai junto como contexto. Sem planilha, o corpo do e-mail é a solicitação.
"""

from __future__ import annotations

import email
import email.policy
import hashlib
import imaplib
import logging
from dataclasses import dataclass, field
from datetime import datetime
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path

from .captura_arquivo import EXTENSOES, planilha_para_entradas
from .config import FUSO
from .modelos import Entrada, agora
from .utils_texto import html_para_texto, remover_citacoes

log = logging.getLogger(__name__)

CABECALHO_ROBO = "X-Motiva-RPA"
REMETENTES_AUTOMATICOS = ("mailer-daemon", "postmaster", "no-reply", "noreply", "nao-responda")


@dataclass
class EmailCapturado:
    message_id: str
    assunto: str
    remetente_nome: str
    remetente_email: str
    data: datetime
    corpo: str
    anexos: list[tuple[str, bytes]] = field(default_factory=list)
    gerado_pelo_robo: bool = False
    automatico: bool = False
    uid: bytes | None = None

    @property
    def deve_ignorar(self) -> str | None:
        if self.gerado_pelo_robo:
            return "mensagem enviada pelo próprio robô"
        if self.automatico:
            return "resposta automática / aviso de entrega"
        return None


def interpretar_email(bruto: bytes, uid: bytes | None = None) -> EmailCapturado:
    msg = email.message_from_bytes(bruto, policy=email.policy.default)
    nome, endereco = parseaddr(str(msg.get("From", "")))
    try:
        data = parsedate_to_datetime(str(msg["Date"])).astimezone(FUSO)
    except Exception:
        data = agora()

    corpo = ""
    parte = msg.get_body(preferencelist=("plain", "html"))
    if parte is not None:
        conteudo = parte.get_content()
        corpo = html_para_texto(conteudo) if parte.get_content_subtype() == "html" else conteudo
    corpo = remover_citacoes(corpo)

    anexos = []
    for anexo in msg.iter_attachments():
        nome_arquivo = anexo.get_filename()
        if nome_arquivo:
            anexos.append((nome_arquivo, anexo.get_payload(decode=True) or b""))

    auto_submitted = str(msg.get("Auto-Submitted", "no")).lower()
    automatico = (
        auto_submitted not in ("", "no")
        or bool(msg.get("X-Autoreply") or msg.get("X-Autorespond"))
        or any(r in endereco.lower() for r in REMETENTES_AUTOMATICOS)
    )
    message_id = str(msg.get("Message-ID", "")).strip() or "sem-id-" + hashlib.sha256(bruto).hexdigest()[:16]
    return EmailCapturado(
        message_id=message_id,
        assunto=str(msg.get("Subject", "")).strip(),
        remetente_nome=nome.strip(),
        remetente_email=endereco.strip().lower(),
        data=data,
        corpo=corpo.strip(),
        anexos=anexos,
        gerado_pelo_robo=msg.get(CABECALHO_ROBO) is not None,
        automatico=automatico and msg.get(CABECALHO_ROBO) is None,
        uid=uid,
    )


def ler_eml(caminho: Path) -> EmailCapturado:
    return interpretar_email(Path(caminho).read_bytes())


def email_para_entradas(e: EmailCapturado) -> list[Entrada]:
    planilhas = [(n, c) for n, c in e.anexos if Path(n).suffix.lower() in EXTENSOES]
    outros = [n for n, _ in e.anexos if Path(n).suffix.lower() not in EXTENSOES]

    if planilhas:
        entradas: list[Entrada] = []
        contexto = f"Assunto: {e.assunto}\n{e.corpo}"
        for nome, conteudo in planilhas:
            entradas += planilha_para_entradas(
                conteudo, nome, canal="email", remetente_nome=e.remetente_nome,
                remetente_email=e.remetente_email, contexto=contexto, recebido_em=e.data,
            )
        for entrada in entradas:
            entrada.arquivo_origem = f"anexo {entrada.arquivo_origem} do e-mail de {e.remetente_email}"
        return entradas

    texto = e.corpo or e.assunto
    if outros:
        texto += f"\n\n[Anexos recebidos: {', '.join(outros)}]"
    return [
        Entrada(
            canal="email",
            origem_ref=e.message_id,
            texto=texto,
            assunto=e.assunto,
            remetente_nome=e.remetente_nome or None,
            remetente_email=e.remetente_email or None,
            recebido_em=e.data,
        )
    ]


class CapturaGmail:
    """Conexão IMAP com o Gmail (usuário + senha de app)."""

    def __init__(self, usuario: str, senha_app: str, pasta: str = "INBOX",
                 marcador_processados: str = "", marcador_erros: str = "",
                 filtro_assunto: str = "", servidor: str = "imap.gmail.com"):
        self.usuario = usuario
        self.senha_app = senha_app
        self.pasta = pasta
        self.marcador_processados = marcador_processados
        self.marcador_erros = marcador_erros
        self.filtro_assunto = filtro_assunto.lower()
        self.servidor = servidor
        self.imap: imaplib.IMAP4_SSL | None = None

    def __enter__(self) -> "CapturaGmail":
        self.imap = imaplib.IMAP4_SSL(self.servidor, 993)
        self.imap.login(self.usuario, self.senha_app)
        status, _ = self.imap.select(f'"{self.pasta}"')
        if status != "OK":
            raise RuntimeError(f"Não foi possível abrir a pasta '{self.pasta}' no Gmail")
        for marcador in (self.marcador_processados, self.marcador_erros):
            if marcador:
                self.imap.create(f'"{marcador}"')  # devolve NO se já existir — tudo bem
        return self

    def __exit__(self, *_):
        if self.imap is not None:
            try:
                self.imap.close()
                self.imap.logout()
            except Exception:
                pass

    def buscar_nao_lidos(self, limite: int = 50) -> list[EmailCapturado]:
        status, dados = self.imap.uid("SEARCH", None, "UNSEEN")
        if status != "OK":
            raise RuntimeError("Falha na busca IMAP")
        capturados = []
        for uid in dados[0].split()[:limite]:
            status, partes = self.imap.uid("FETCH", uid, "(BODY.PEEK[])")
            if status != "OK" or not partes or not isinstance(partes[0], tuple):
                continue
            e = interpretar_email(partes[0][1], uid=uid)
            if self.filtro_assunto and self.filtro_assunto not in e.assunto.lower() and not e.deve_ignorar:
                continue
            capturados.append(e)
        return capturados

    def _marcar(self, uid: bytes, marcador: str) -> None:
        self.imap.uid("STORE", uid, "+FLAGS", "(\\Seen)")
        if marcador:
            self.imap.uid("COPY", uid, f'"{marcador}"')

    def marcar_processado(self, e: EmailCapturado) -> None:
        if e.uid is not None:
            self._marcar(e.uid, self.marcador_processados)

    def marcar_ignorado(self, e: EmailCapturado) -> None:
        if e.uid is not None:
            self.imap.uid("STORE", e.uid, "+FLAGS", "(\\Seen)")

    def marcar_erro(self, e: EmailCapturado) -> None:
        if e.uid is not None:
            self._marcar(e.uid, self.marcador_erros)
