import email
import email.policy
from types import SimpleNamespace

from conftest import IAFalsa, analise

from motiva_rpa.ia import ClassificadorOpenAI, ClassificadorRegras, MotorIA
from motiva_rpa.modelos import AnaliseSolicitacao, Entrada
from motiva_rpa.notificacao import Notificador
from motiva_rpa.pipeline import Pipeline
from motiva_rpa.robo import ciclo_pasta, processar_pasta_eml
from conftest import RAIZ


def entrada(texto="Buraco no acostamento da Castello km 45+300", origem="msg-1", **kw):
    return Entrada(canal="email", origem_ref=origem, texto=texto, assunto="Buraco",
                   remetente_nome="Ana", remetente_email="ana@inspecao.example", **kw)


def ler(caminho):
    return email.message_from_bytes(caminho.read_bytes(), policy=email.policy.default)


def test_ponta_a_ponta_registra_e_encaminha(criar_pipeline, emails_gerados):
    p = criar_pipeline(IAFalsa())
    r = p.processar(entrada())
    assert r.protocolo.startswith("CNS-") and r.status == "ENCAMINHADA"

    s = p.repo.por_protocolo(r.protocolo)
    assert s.equipe_id == "CONSERVACAO_VIAOESTE" and s.prazo_retorno and s.concessao == "VIAOESTE"
    eventos = [h["evento"] for h in p.repo.historico(r.protocolo)]
    assert eventos[:2] == ["RECEBIDA", "CLASSIFICADA"] and "ENCAMINHADA" in eventos

    [enc] = emails_gerados("encaminhamento")
    msg = ler(enc)
    assert msg["To"] == "conservacao.viaoeste@example.com"
    assert msg["Reply-To"] == "ana@inspecao.example"
    assert r.protocolo in msg["Subject"] and msg["X-Motiva-RPA"] == "encaminhamento"
    assert len(emails_gerados("confirmacao")) == 1


def test_mesma_origem_nao_duplica(criar_pipeline):
    p = criar_pipeline(IAFalsa())
    primeiro = p.processar(entrada())
    segundo = p.processar(entrada())
    assert segundo.duplicado and segundo.protocolo == primeiro.protocolo
    assert len(p.repo.listar()) == 1


def test_pedido_de_informacao_e_complemento_pelo_protocolo(criar_pipeline, emails_gerados):
    ia = IAFalsa(analise(km=None))
    p = criar_pipeline(ia)
    r = p.processar(entrada(texto="Buraco perto do pedágio de Itapevi"))
    assert r.status == "PENDENTE_INFORMACAO"
    assert len(emails_gerados("pedido_informacao")) == 1 and not emails_gerados("encaminhamento")

    ia.resposta = analise(km=33)
    resposta = Entrada(canal="email", origem_ref="msg-2", texto="Era o km 33",
                       assunto=f"Re: [{r.protocolo}] Precisamos de mais informações",
                       remetente_email="ana@inspecao.example")
    r2 = p.processar(resposta)
    assert r2.complemento and r2.protocolo == r.protocolo and r2.status == "ENCAMINHADA"
    assert "Complemento do solicitante" in ia.chamadas[-1].texto  # a IA reanalisa com o texto todo
    assert len(p.repo.listar()) == 1
    assert p.processar(resposta).duplicado  # o mesmo complemento não é aplicado duas vezes


def test_baixa_confianca_vai_para_triagem(criar_pipeline, emails_gerados):
    p = criar_pipeline(IAFalsa(analise(confianca=0.3)))
    r = p.processar(entrada())
    assert r.status == "EM_TRIAGEM" and r.equipe.startswith("Triagem")
    assert ler(emails_gerados("encaminhamento")[0])["Subject"].startswith("[TRIAGEM]")


def test_concessao_pelo_trecho_e_copias_do_cco_e_engenharia(criar_pipeline, emails_gerados):
    p = criar_pipeline(IAFalsa(analise(categoria="DRENAGEM_TALUDES", rodovia="BR-290", km=18, sentido="Porto Alegre",
                                       urgencia="CRITICA")))
    p.processar(entrada(texto="Água cobrindo a faixa"))
    msg = ler(emails_gerados("encaminhamento")[0])
    assert msg["To"] == "conservacao.viasul@example.com"
    assert "cco@example.com" in msg["Cc"] and "engenharia.taludes@example.com" in msg["Cc"]
    assert "BR-290 km 18 sentido Porto Alegre" in msg["Subject"]


def test_sinalizacao_vai_para_equipe_central(criar_pipeline):
    p = criar_pipeline(IAFalsa(analise(categoria="SINALIZACAO")))
    assert p.processar(entrada()).equipe == "Sinalização e Dispositivos de Segurança"


def test_possivel_duplicata_no_mesmo_local(criar_pipeline):
    p = criar_pipeline(IAFalsa(analise(rodovia="SP-348", km=72.4, sentido="capital")))
    primeiro = p.processar(entrada(origem="msg-1"))
    p.motor.principal.resposta = analise(rodovia="SP-348", km=72, sentido="capital")
    segundo = p.processar(entrada(origem="msg-2", texto="Buraco enorme, estourou meu pneu"))
    s = p.repo.por_protocolo(segundo.protocolo)
    assert s.possivel_duplicata == primeiro.protocolo
    # outro sentido ou outra categoria não é duplicata
    p.motor.principal.resposta = analise(rodovia="SP-348", km=72, sentido="interior")
    terceiro = p.processar(entrada(origem="msg-3"))
    assert p.repo.por_protocolo(terceiro.protocolo).possivel_duplicata is None


def test_contingencia_quando_a_openai_falha(criar_pipeline):
    p = criar_pipeline(IAFalsa(erro=TimeoutError("sem rede")), reserva=ClassificadorRegras())
    r = p.processar(entrada())
    assert "contingência" in r.motor_ia
    assert any("OpenAI indisponível" in a for a in r.avisos)


def test_dados_sensiveis_nao_vao_para_a_ia(criar_pipeline):
    ia = IAFalsa()
    p = criar_pipeline(ia)
    r = p.processar(entrada(texto="Usuário CPF 123.456.789-09 relata buraco na Castello km 45"))
    assert "123.456.789-09" not in ia.chamadas[0].texto
    assert "123.456.789-09" in p.repo.por_protocolo(r.protocolo).texto_original


def test_classificador_openai_usa_structured_outputs(tmp_path):
    chamadas = {}

    def parse(**kwargs):
        chamadas.update(kwargs)
        mensagem = SimpleNamespace(parsed=analise(categoria="SINALIZACAO"), refusal=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=mensagem)])

    cliente = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(parse=parse)))
    c = ClassificadorOpenAI("chave", "gpt-teste", RAIZ / "prompts" / "sistema_conservacao.md",
                            reasoning_effort="low", cliente=cliente)
    resultado = c.analisar(entrada(texto="Placa caída"))
    assert resultado.categoria == "SINALIZACAO"
    assert chamadas["response_format"] is AnaliseSolicitacao
    assert chamadas["model"] == "gpt-teste" and chamadas["reasoning_effort"] == "low"
    assert "Placa caída" in chamadas["messages"][1]["content"]
    assert "Motiva" in chamadas["messages"][0]["content"]


def test_redirecionamento_de_envio(config, tmp_path):
    notificador = Notificador("arquivo", tmp_path, redirecionar_para="grupo@exemplo.example")
    p = Pipeline(config, motor=MotorIA(IAFalsa()), notificador=notificador)
    p.processar(entrada())
    enc = next((tmp_path / "emails").glob("*encaminhamento.eml"))
    msg = ler(enc)
    assert msg["To"] == "grupo@exemplo.example" and "conservacao.viaoeste@example.com" in msg["Subject"]


def test_demo_com_amostras_e_motor_de_regras(pipeline_regras, config):
    resultados = processar_pasta_eml(pipeline_regras, RAIZ / "amostras" / "emails")
    assert len(resultados) == 14  # 10 e-mails + 4 linhas da planilha anexada
    for nome in ("checklist_inspecao_viaoeste.xlsx", "manifestacoes_ouvidoria_0800.csv"):
        (config.pasta_entrada / nome).write_bytes((RAIZ / "amostras" / "planilhas" / nome).read_bytes())
    resultados += ciclo_pasta(pipeline_regras, idade_minima_s=0)
    assert len(resultados) == 23 and not [r for r in resultados if r.erro]
    assert list((config.pasta_entrada / "processados").iterdir())
    xlsx = pipeline_regras.repo.exportar_excel(config.pasta_saida / "registro.xlsx")
    assert xlsx.exists()


def test_ciclo_gmail_processa_marca_e_ignora_mensagens_do_robo(config, monkeypatch):
    from motiva_rpa import robo
    from motiva_rpa.captura_email import ler_eml

    pane = ler_eml(RAIZ / "amostras" / "emails" / "01_buraco_bandeirantes.eml")
    pane.uid = b"1"
    do_robo = ler_eml(RAIZ / "amostras" / "emails" / "02_placa_castello.eml")
    do_robo.uid, do_robo.gerado_pelo_robo = b"2", True
    marcacoes = []

    class GmailFalso:
        def __init__(self, *args):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def buscar_nao_lidos(self, limite):
            return [pane, do_robo]

        def marcar_processado(self, e):
            marcacoes.append(("processado", e.uid))

        def marcar_ignorado(self, e):
            marcacoes.append(("ignorado", e.uid))

        def marcar_erro(self, e):
            marcacoes.append(("erro", e.uid))

    monkeypatch.setattr(robo, "CapturaGmail", GmailFalso)
    config.gmail_usuario, config.gmail_senha_app = "grupo@gmail.com", "x"
    p = Pipeline(config, motor=MotorIA(IAFalsa(analise(rodovia="SP-348", km=72.4, urgencia="CRITICA"))))
    resultados = robo.ciclo_gmail(p)
    assert len(resultados) == 1 and resultados[0].status == "ENCAMINHADA"
    assert marcacoes == [("processado", b"1"), ("ignorado", b"2")]
