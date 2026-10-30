import io
import os
import time
from email.message import EmailMessage

from openpyxl import Workbook

from conftest import RAIZ
from motiva_rpa.captura_arquivo import MonitorPasta, planilha_para_entradas
from motiva_rpa.captura_email import email_para_entradas, interpretar_email, ler_eml

AMOSTRAS = RAIZ / "amostras"


# ---------------------------------------------------------------- planilhas
def test_csv_com_ponto_e_virgula_e_windows_1252():
    conteudo = "Rodovia;KM;Sentido;Anomalia;Inspetor\nSP-330;68+200;Interior;Afundamento no acostamento;Lúcia\n"
    entradas = planilha_para_entradas(conteudo.encode("cp1252"), "ronda.csv")
    assert len(entradas) == 1
    e = entradas[0]
    assert e.dados_planilha["rodovia"] == "SP-330"
    assert e.dados_planilha["km"] == "68+200"
    assert e.dados_planilha["sentido"] == "Interior"
    assert e.dados_planilha["solicitante_nome"] == "Lúcia"  # acentos preservados
    assert "Afundamento no acostamento" in e.texto
    assert e.arquivo_origem == "ronda.csv (linha 2)"


def test_csv_com_virgula_e_aspas():
    conteudo = 'rodovia,km,manifestacao\nBR-116,211,"Tachões soltos, um bateu no carro"\n'
    [e] = planilha_para_entradas(conteudo.encode(), "ouvidoria.csv")
    assert "Tachões soltos, um bateu no carro" in e.texto


def test_xlsx_com_titulo_antes_do_cabecalho_e_linha_vazia():
    wb = Workbook()
    ws = wb.active
    ws["A1"] = "Checklist semanal de inspeção"
    ws.append([])
    ws.append(["Rodovia", "KM", "Anomalia"])
    ws.append(["SP-280", "38+100", "Trinca"])
    ws.append([None, None, None])
    ws.append(["SP-270", 71.4, "Pedras na faixa 2"])
    buf = io.BytesIO()
    wb.save(buf)
    entradas = planilha_para_entradas(buf.getvalue(), "check.xlsx")
    assert [e.dados_planilha["rodovia"] for e in entradas] == ["SP-280", "SP-270"]
    assert entradas[1].dados_planilha["km"] == "71.4"
    assert entradas[0].origem_ref != entradas[1].origem_ref


def test_amostras_de_planilha():
    xlsx = (AMOSTRAS / "planilhas" / "checklist_inspecao_viaoeste.xlsx").read_bytes()
    assert len(planilha_para_entradas(xlsx, "checklist.xlsx")) == 6
    csv = (AMOSTRAS / "planilhas" / "manifestacoes_ouvidoria_0800.csv").read_bytes()
    linhas = planilha_para_entradas(csv, "ouvidoria.csv")
    assert len(linhas) == 3 and linhas[0].dados_planilha["solicitante_nome"] == "Antônio Melo"


def test_monitor_move_arquivo_processado(tmp_path):
    monitor = MonitorPasta(tmp_path)
    arquivo = tmp_path / "lote.csv"
    arquivo.write_text("rodovia;km;descricao\nSP-280;45;buraco\n", encoding="utf-8")
    antigo = time.time() - 10
    os.utime(arquivo, (antigo, antigo))
    (tmp_path / "~$temporario.xlsx").write_text("x")
    assert monitor.arquivos_novos() == [arquivo]
    destino = monitor.concluir(arquivo)
    assert destino.parent.name == "processados" and not arquivo.exists()


# ---------------------------------------------------------------- e-mail
def test_le_amostra_eml():
    e = ler_eml(AMOSTRAS / "emails" / "01_buraco_bandeirantes.eml")
    assert e.assunto == "URGENTE - buraco na pista Bandeirantes km 72"
    assert e.remetente_email == "rogerio.lima@inspecao.example"
    assert "72+400" in e.corpo
    [entrada] = email_para_entradas(e)
    assert entrada.canal == "email" and entrada.origem_ref == e.message_id


def test_email_com_planilha_anexa_vira_uma_entrada_por_linha():
    e = ler_eml(AMOSTRAS / "emails" / "09_ronda_noturna_csv.eml")
    entradas = email_para_entradas(e)
    assert len(entradas) == 4
    assert all(x.canal == "email" and "ronda noturna" in x.contexto for x in entradas)
    assert entradas[0].remetente_email == "lucia.ramos@inspecao.example"


def _email(**cabecalhos) -> bytes:
    m = EmailMessage()
    m["From"] = cabecalhos.pop("de", "Fulano <fulano@exemplo.example>")
    m["Subject"] = "Teste"
    for k, v in cabecalhos.items():
        m[k.replace("_", "-")] = v
    m.set_content("corpo")
    return bytes(m)


def test_ignora_mensagens_do_proprio_robo_e_automaticas():
    assert interpretar_email(_email(X_Motiva_RPA="encaminhamento")).deve_ignorar
    assert interpretar_email(_email(de="Mail Delivery <mailer-daemon@googlemail.com>")).deve_ignorar
    assert interpretar_email(_email(Auto_Submitted="auto-replied")).deve_ignorar
    assert interpretar_email(_email()).deve_ignorar is None


def test_email_so_html():
    m = EmailMessage()
    m["From"] = "a@b.example"
    m["Subject"] = "x"
    m.set_content("<p>Buraco <b>grande</b></p>", subtype="html")
    assert interpretar_email(bytes(m)).corpo == "Buraco grande"
