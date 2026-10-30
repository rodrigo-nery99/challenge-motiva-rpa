"""Regras de negócio aplicadas DEPOIS da IA.

A IA interpreta o texto; as regras abaixo garantem o que não pode depender de
interpretação: localização válida (rodovia + km dentro de um trecho da
concessão), segurança sempre como prioridade máxima e encaminhamento para uma
pessoa quando a IA não tem certeza.

Cada ajuste vira um aviso no registro, para que a equipe saiba o que foi
alterado e por quê.
"""

from __future__ import annotations

from .ia import ResultadoIA
from .modelos import ORDEM_URGENCIA, Entrada, Solicitacao, formatar_km
from .trechos import CadastroTrechos
from .utils_texto import (
    RE_EMAIL,
    converter_km,
    encontrar_km,
    encontrar_rodovias,
    encontrar_sentido,
    limitar,
    normalizar_busca,
    normalizar_sentido,
    normalizar_uf,
)

CATEGORIAS_CONSERVACAO = {
    "PAVIMENTO",
    "SINALIZACAO",
    "DISPOSITIVOS_SEGURANCA",
    "DRENAGEM_TALUDES",
    "ILUMINACAO",
    "VEGETACAO_LIMPEZA",
}

# Rede de proteção independente da IA: se aparecer no texto, a urgência é crítica.
TERMOS_SEGURANCA = [
    "obstruindo", "obstrucao da", "bloqueando a faixa", "bloqueia a faixa", "interditando a faixa",
    "objeto na pista", "pedra na pista", "pedras na pista", "terra na pista", "carga na pista",
    "pneu na pista", "galho na pista", "arvore na pista", "arvore caida na pista", "arvore caiu na pista",
    "oleo na pista", "animal na pista", "cavalo na pista", "boi na pista", "pedestre na pista",
    "queda de barreira", "barreira caiu", "desmoronou", "cratera",
    "fio caido", "fios caidos", "cabo caido", "cabos caidos", "fiacao exposta",
    "defensa arrancada", "sem defensa", "agua cobrindo", "alagamento na pista", "pista alagada",
    "tunel apagado", "tunel sem iluminacao", "pegando fogo", "incendio",
]
# Termos que, apesar de conterem "na pista", indicam que NÃO há obstrução
TERMOS_NEGACAO = ["nao ha nada na pista", "nada na pista", "nao invade a pista", "sem obstrucao"]


def _subir_urgencia(atual: str, minima: str) -> str:
    return minima if ORDEM_URGENCIA.index(atual) < ORDEM_URGENCIA.index(minima) else atual


def construir_registro(
    entrada: Entrada,
    resultado: ResultadoIA,
    trechos: CadastroTrechos,
    confianca_minima: float = 0.6,
) -> Solicitacao:
    a = resultado.analise
    avisos: list[str] = []
    if resultado.aviso:
        avisos.append(resultado.aviso)
    texto_completo = f"{entrada.assunto or ''}\n{entrada.texto}"

    s = Solicitacao(
        canal=entrada.canal,
        origem_ref=entrada.origem_ref,
        arquivo_origem=entrada.arquivo_origem,
        assunto=entrada.assunto,
        remetente_nome=entrada.remetente_nome,
        remetente_email=entrada.remetente_email,
        recebido_em=entrada.recebido_em.isoformat(),
        texto_original=entrada.texto,
        categoria=a.categoria,
        urgencia=a.urgencia,
        confianca=round(max(0.0, min(1.0, float(a.confianca))), 2),
        justificativa=a.justificativa.strip(),
        resumo=limitar(a.resumo, 220),
        local_na_via=a.local_na_via,
        referencia=a.referencia,
        cidade=a.cidade,
        obstrucao_pista=bool(a.obstrucao_pista),
        risco_imediato=bool(a.risco_imediato),
        interdicao_necessaria=a.interdicao_necessaria,
        dimensao=a.dimensao,
        data_preferencial=a.data_preferencial,
        tipo_solicitante=a.tipo_solicitante,
        solicitante_nome=a.solicitante_nome or entrada.remetente_nome,
        solicitante_telefone=a.solicitante_telefone,
        equipe_origem=a.equipe_origem,
        motor_ia=resultado.motor,
        dados_ia=a.model_dump(),
        dados_estruturados=dict(entrada.dados_planilha),
    )

    # --- 1. Localização: rodovia, km e sentido ----------------------------
    s.rodovia = trechos.codigo_rodovia(a.rodovia)
    if a.rodovia and not s.rodovia:
        avisos.append(f"Rodovia '{a.rodovia}' citada não foi reconhecida (código ou nome do cadastro).")
    if not s.rodovia:
        achadas = encontrar_rodovias(texto_completo)
        s.rodovia = achadas[0] if achadas else trechos.rodovia_no_texto(texto_completo)
        if s.rodovia:
            avisos.append(f"Rodovia {s.rodovia} localizada no texto por regra.")

    s.km = converter_km(a.km)
    if a.km is not None and s.km is None:
        avisos.append(f"Km '{a.km}' fora da faixa esperada e descartado.")
    if s.km is None:
        s.km = encontrar_km(texto_completo)
        if s.km is not None:
            avisos.append(f"Km {formatar_km(s.km)} localizado no texto por regra.")

    s.sentido = normalizar_sentido(a.sentido) or encontrar_sentido(texto_completo)
    s.uf = normalizar_uf(a.uf)

    email = (a.solicitante_email or "").strip()
    s.solicitante_email = email if RE_EMAIL.fullmatch(email) else entrada.remetente_email

    # --- 2. Colunas da planilha / campos da ligação prevalecem --------------
    dp = entrada.dados_planilha
    if dp:
        rodovia_dp = trechos.codigo_rodovia(dp.get("rodovia"))
        if rodovia_dp:
            if s.rodovia and s.rodovia != rodovia_dp:
                avisos.append(f"IA leu {s.rodovia}, mas a coluna diz {rodovia_dp}; mantida a da coluna.")
            s.rodovia = rodovia_dp
        km_dp = converter_km(dp.get("km"))
        if km_dp is not None:
            if s.km is not None and abs(s.km - km_dp) > 0.05:
                avisos.append(f"IA leu km {formatar_km(s.km)}, mas a coluna diz km {formatar_km(km_dp)}; mantida a da coluna.")
            s.km = km_dp
        if normalizar_sentido(dp.get("sentido")):
            s.sentido = normalizar_sentido(dp["sentido"])
        if normalizar_uf(dp.get("uf")):
            s.uf = normalizar_uf(dp["uf"])
        for campo in ("cidade", "local_na_via", "solicitante_nome", "solicitante_telefone", "equipe_origem"):
            if dp.get(campo):
                setattr(s, campo, dp[campo].strip())
        if dp.get("solicitante_email") and RE_EMAIL.fullmatch(dp["solicitante_email"].strip()):
            s.solicitante_email = dp["solicitante_email"].strip()

    # --- 3. Enriquecimento com o cadastro de trechos ------------------------
    trecho = trechos.localizar(s.rodovia, s.km)
    if trecho:
        s.concessao = trecho.concessao
        s.trecho = trecho.descricao
        s.base_conservacao = trecho.base_conservacao
        s.uf = s.uf or trecho.uf
    elif s.rodovia and s.km is not None and len(trechos):
        if trechos.opera_rodovia(s.rodovia):
            avisos.append(f"{s.rodovia} km {formatar_km(s.km)} está fora dos trechos cadastrados — confirmar o km.")
        else:
            avisos.append(f"{s.rodovia} não consta no cadastro de trechos da concessionária — confirmar a rodovia.")

    # --- 4. Regras de urgência --------------------------------------------
    texto_norm = normalizar_busca(texto_completo)
    negado = any(n in texto_norm for n in TERMOS_NEGACAO)
    termo_risco = None if negado else next((t for t in TERMOS_SEGURANCA if t in texto_norm), None)
    if s.categoria != "FORA_ESCOPO":
        if (s.risco_imediato or s.obstrucao_pista or termo_risco) and s.urgencia != "CRITICA":
            if s.risco_imediato:
                motivo = "IA apontou risco imediato"
            elif s.obstrucao_pista:
                motivo = "IA apontou obstrução da pista"
            else:
                motivo = f"termo de segurança '{termo_risco}' no texto"
            avisos.append(f"Regra: {motivo} — urgência elevada de {s.urgencia} para CRITICA.")
            s.urgencia = "CRITICA"
        if s.interdicao_necessaria and s.urgencia in ("BAIXA", "MEDIA"):
            avisos.append(f"Regra: precisa de interdição/sinalização — urgência elevada de {s.urgencia} para ALTA.")
            s.urgencia = "ALTA"

    # --- 5. Campos obrigatórios e status ----------------------------------
    faltantes: list[str] = []
    if s.categoria in CATEGORIAS_CONSERVACAO:
        if not s.rodovia:
            faltantes.append("rodovia")
        if s.km is None:
            faltantes.append("km do local")
        if s.rodovia and s.km is not None and not s.sentido:
            avisos.append("Sentido da pista não informado — a equipe deve confirmar no local.")
    elif s.categoria == "OCORRENCIA_TRAFEGO" and not (s.rodovia or s.referencia):
        faltantes.append("local da ocorrência")
    s.campos_faltantes = faltantes

    tem_contato = bool(s.solicitante_email) or entrada.canal == "voz"
    if s.confianca < confianca_minima:
        s.status = "EM_TRIAGEM"
        s.motivo_status = f"Confiança da IA ({s.confianca:.0%}) abaixo do mínimo de {confianca_minima:.0%}."
    elif s.categoria == "FORA_ESCOPO":
        s.status, s.motivo_status = "ENCAMINHADA", "Fora do escopo de conservação: enviado à Ouvidoria."
    elif a.multiplos_locais:
        s.status, s.motivo_status = "EM_TRIAGEM", "A mensagem trata de mais de um local ou problema."
    elif faltantes and (s.urgencia == "CRITICA" or s.categoria == "OCORRENCIA_TRAFEGO"):
        s.status = "ENCAMINHADA"
        s.motivo_status = f"Urgência crítica: encaminhada mesmo sem {', '.join(faltantes)}."
        avisos.append(f"Dados faltantes ({', '.join(faltantes)}): o CCO/equipe deve confirmar com o solicitante.")
    elif faltantes and tem_contato:
        s.status = "PENDENTE_INFORMACAO"
        s.motivo_status = f"Falta: {', '.join(faltantes)}. Pedido enviado ao solicitante."
    elif faltantes:
        s.status = "EM_TRIAGEM"
        s.motivo_status = f"Falta: {', '.join(faltantes)} e não há contato do solicitante para pedir."
    else:
        s.status, s.motivo_status = "ENCAMINHADA", "Dados completos: encaminhada ao responsável."

    s.avisos = avisos
    return s
