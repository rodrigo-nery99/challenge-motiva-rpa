"""Pipeline de ponta a ponta: entrada → IA → regras → registro → encaminhamento.

É o mesmo para todos os canais (e-mail, planilha, voz, API). Cada canal só
precisa transformar o que recebeu em uma ``Entrada``.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime

from .config import Config, carregar_config
from .ia import MotorIA, criar_motor
from .modelos import Entrada, Resultado, Solicitacao, agora
from .notificacao import Notificador
from .regras_negocio import construir_registro
from .registro import Repositorio
from .roteamento import Roteador
from .trechos import CadastroTrechos
from .utils_texto import RE_PROTOCOLO, limitar, mascarar_dados_sensiveis

log = logging.getLogger(__name__)


class Pipeline:
    def __init__(
        self,
        config: Config,
        motor: MotorIA | None = None,
        repositorio: Repositorio | None = None,
        roteador: Roteador | None = None,
        notificador: Notificador | None = None,
        trechos: CadastroTrechos | None = None,
    ):
        config.criar_pastas()
        self.config = config
        self.motor = motor or criar_motor(config)
        self.repo = repositorio or Repositorio(config.banco_dados)
        self.roteador = roteador or Roteador(config.matriz_roteamento)
        self.notificador = notificador or Notificador(
            modo=config.envio_modo,
            pasta_saida=config.pasta_saida,
            usuario=config.gmail_usuario,
            senha_app=config.gmail_senha_app,
            redirecionar_para=config.envio_redirecionar_para,
        )
        self.trechos = trechos or CadastroTrechos(config.cadastro_trechos)

    @classmethod
    def criar(cls, config: Config | None = None) -> "Pipeline":
        return cls(config or carregar_config())

    # ------------------------------------------------------------------
    def processar(self, entrada: Entrada) -> Resultado:
        existente = self.repo.existe_origem(entrada.origem_ref)
        if existente:
            log.info("Ignorada (já registrada como %s): %s", existente.protocolo, entrada.origem_ref)
            return self._resultado(existente, duplicado=True)

        protocolo = self._protocolo_citado(entrada)
        if protocolo:
            registro = self.repo.por_protocolo(protocolo)
            if registro:
                return self.complementar(registro, entrada)

        s = self._analisar(entrada)
        s = self.repo.inserir(s)
        self.repo.registrar_evento(s, "RECEBIDA", f"canal={entrada.canal} origem={entrada.origem_ref}")
        self.repo.registrar_evento(
            s, "CLASSIFICADA",
            f"{s.categoria} / {s.urgencia} · confiança {s.confianca:.0%} · motor {s.motor_ia}",
        )
        avisos_envio = self._encaminhar(s, entrada.recebido_em)
        log.info("%s %s/%s → %s [%s]", s.protocolo, s.categoria, s.urgencia, s.equipe_nome, s.status)
        return self._resultado(s, avisos_extra=avisos_envio)

    def complementar(self, registro: Solicitacao, entrada: Entrada) -> Resultado:
        """Informação nova sobre uma solicitação já registrada (resposta do cliente, ligação…)."""
        if self.repo.origem_ja_registrada_no_historico(entrada.origem_ref):
            return self._resultado(registro, duplicado=True, complemento=True)
        self.repo.registrar_evento(
            registro, "COMPLEMENTO_RECEBIDO", f"origem={entrada.origem_ref}\n{limitar(entrada.texto, 600)}"
        )

        if registro.status not in ("PENDENTE_INFORMACAO", "EM_TRIAGEM"):
            avisos = []
            if registro.equipe_email:
                try:
                    destino = self.notificador.enviar(self.notificador.atualizacao(registro, entrada.texto), registro.protocolo)
                    self.repo.registrar_evento(registro, "ATUALIZACAO_ENVIADA", destino)
                except Exception as exc:
                    avisos.append(f"Falha ao repassar complemento: {exc}")
            return self._resultado(registro, complemento=True, avisos_extra=avisos)

        recebido = datetime.fromisoformat(registro.recebido_em) if registro.recebido_em else agora()
        combinada = Entrada(
            canal=registro.canal,
            origem_ref=registro.origem_ref,
            texto=(f"{registro.texto_original}\n\n--- Complemento do solicitante "
                   f"({entrada.recebido_em:%d/%m/%Y %H:%M}) ---\n{entrada.texto}"),
            assunto=registro.assunto,
            remetente_nome=registro.remetente_nome,
            remetente_email=registro.remetente_email or entrada.remetente_email,
            recebido_em=recebido,
            arquivo_origem=registro.arquivo_origem,
            dados_planilha=dict(registro.dados_estruturados or {}),
        )
        novo = self._analisar(combinada)
        novo.id, novo.protocolo, novo.criado_em = registro.id, registro.protocolo, registro.criado_em
        if novo.possivel_duplicata == registro.protocolo:  # não é duplicata de si mesma
            novo.possivel_duplicata = None
            novo.avisos = [a for a in novo.avisos if registro.protocolo not in a]
        novo.avisos.insert(0, "Reanalisada após complemento do solicitante.")
        self.repo.atualizar(novo)
        self.repo.registrar_evento(
            novo, "REANALISADA", f"{novo.categoria} / {novo.urgencia} · status {novo.status} · motor {novo.motor_ia}"
        )
        avisos_envio = self._encaminhar(novo, recebido)
        return self._resultado(novo, complemento=True, avisos_extra=avisos_envio)

    def processar_lote(self, entradas: list[Entrada]) -> list[Resultado]:
        resultados = []
        for entrada in entradas:
            try:
                resultados.append(self.processar(entrada))
            except Exception as exc:  # uma linha ruim não derruba o lote
                log.exception("Erro ao processar %s", entrada.origem_ref)
                resultados.append(Resultado(protocolo=None, status="ERRO", origem_ref=entrada.origem_ref, erro=str(exc)))
        return resultados

    # ------------------------------------------------------------------
    def _protocolo_citado(self, entrada: Entrada) -> str | None:
        m = RE_PROTOCOLO.search(entrada.assunto or "") or RE_PROTOCOLO.search((entrada.texto or "")[:400])
        return m.group(0).upper() if m else None

    def _analisar(self, entrada: Entrada) -> Solicitacao:
        # A IA recebe o texto com dados sensíveis mascarados; o registro guarda o original.
        para_ia = replace(
            entrada,
            texto=mascarar_dados_sensiveis(entrada.texto),
            contexto=mascarar_dados_sensiveis(entrada.contexto) if entrada.contexto else None,
        )
        resultado = self.motor.analisar(para_ia)
        s = construir_registro(entrada, resultado, self.trechos, self.config.confianca_minima)
        self._marcar_duplicata(s, excluir_id=None)
        return s

    def _marcar_duplicata(self, s: Solicitacao, excluir_id: int | None) -> None:
        """Vários usuários e inspetores costumam relatar o mesmo buraco: avisa se já há
        solicitação aberta da mesma categoria a até 1 km, no mesmo sentido."""
        if not s.rodovia or s.km is None or s.categoria in ("FORA_ESCOPO", "OCORRENCIA_TRAFEGO"):
            return
        for outra in self.repo.abertas_proximas(s.rodovia, s.km, 1.0, excluir_id=excluir_id):
            mesmo_sentido = not s.sentido or not outra.sentido or s.sentido == outra.sentido
            if outra.categoria == s.categoria and mesmo_sentido and outra.protocolo:
                s.possivel_duplicata = outra.protocolo
                s.avisos.append(
                    f"Possível duplicata de {outra.protocolo} ({outra.localizacao}, {outra.status.lower()}): "
                    "confirmar se é o mesmo problema antes de mobilizar outra equipe."
                )
                return

    def _encaminhar(self, s: Solicitacao, recebido_em: datetime) -> list[str]:
        destino = self.roteador.definir(s, recebido_em)
        s.equipe_id, s.equipe_nome, s.equipe_email = destino.equipe_id, destino.equipe_nome, destino.email
        s.copias, s.sla_horas = destino.copias, destino.sla_horas
        s.prazo_retorno = destino.prazo.isoformat() if destino.prazo else None
        self.repo.atualizar(s)

        falhas: list[str] = []

        def enviar(evento: str, montar):
            try:
                resultado = self.notificador.enviar(montar(), s.protocolo)
                self.repo.registrar_evento(s, evento, resultado)
            except Exception as exc:
                log.error("Falha no envio (%s) de %s: %s", evento, s.protocolo, exc)
                self.repo.registrar_evento(s, "FALHA_ENVIO", f"{evento}: {exc}")
                falhas.append(f"Falha no envio ({evento}): {exc}")

        if s.status == "PENDENTE_INFORMACAO":
            if s.solicitante_email:
                enviar("PEDIDO_INFORMACAO_ENVIADO", lambda: self.notificador.pedido_informacao(s))
            return falhas

        evento = "ENVIADA_TRIAGEM" if s.status == "EM_TRIAGEM" else "ENCAMINHADA"
        enviar(evento, lambda: self.notificador.encaminhamento(s, destino))
        if self.config.enviar_confirmacao_solicitante and s.solicitante_email and s.canal != "voz":
            enviar("CONFIRMACAO_ENVIADA", lambda: self.notificador.confirmacao(s, destino))
        return falhas

    @staticmethod
    def _resultado(s: Solicitacao, duplicado: bool = False, complemento: bool = False,
                   avisos_extra: list[str] | None = None) -> Resultado:
        return Resultado(
            protocolo=s.protocolo,
            status=s.status,
            categoria=s.categoria,
            urgencia=s.urgencia,
            equipe=s.equipe_nome,
            prazo_retorno=s.prazo_retorno,
            motor_ia=s.motor_ia,
            origem_ref=s.origem_ref,
            duplicado=duplicado,
            complemento=complemento,
            avisos=[*s.avisos, *(avisos_extra or [])],
        )
