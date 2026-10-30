# Roteiro do vídeo de demonstração (3 a 5 minutos)

## Antes de gravar

- [ ] `.env` com `OPENAI_API_KEY`, `GMAIL_USUARIO`, `GMAIL_SENHA_APP`, `ENVIO_MODO=smtp` e `ENVIO_REDIRECIONAR_PARA`.
- [ ] `python main.py testar-ia` responde com `Motor: openai:...` (e não `regras`).
- [ ] `python main.py avaliar --motor ambos` já rodado (para mostrar a comparação).
- [ ] Banco limpo: apague `dados/solicitacoes.db`.
- [ ] Caixa do Gmail do grupo sem e-mails não lidos.
- [ ] Um segundo e-mail (pessoal) pronto para mandar as solicitações ao vivo.
- [ ] Janelas abertas: terminal, Gmail do grupo, pasta `entrada/`, `saida/solicitacoes.xlsx`, http://localhost:8000/docs.
- [ ] Fonte do terminal grande (o avaliador precisa ler).

## Cenas

| # | Tempo | O que mostrar | Fala sugerida |
|---|---|---|---|
| 1 | 0:00–0:25 | Título e diagrama AS-IS (`docs/processo_as_is.png`) | "O desafio da Motiva é um agente de voz para quem trabalha em campo na rodovia. Nesta Sprint fizemos a base: as solicitações de conservação. Hoje elas chegam por e-mail, planilha de ronda e 0800, alguém lê, descobre o trecho pelo km, decide a urgência no olho e encaminha. Um objeto na pista pode esperar atrás de uma roçada." |
| 2 | 0:25–0:45 | Diagrama TO-BE (`docs/processo_to_be.png`) | "O robô captura, a IA classifica e extrai rodovia, km, sentido e se há risco imediato, as regras localizam a concessão e checam duplicatas, e a solicitação sai registrada e encaminhada com prazo." |
| 3 | 0:45–1:00 | Terminal: `python main.py monitorar --intervalo 20` | "O robô está vigiando o Gmail e a pasta de entrada." |
| 4 | 1:00–1:40 | Do e-mail pessoal, mande: *"Inspeção 03: buraco grande na faixa da direita da Bandeirantes, km 72+400, sentido capital, uns 80 cm. Carros desviando em cima da hora."* Espere o ciclo e mostre o log | "A IA entendeu: pavimento, urgência crítica, SP-348 km 72,4 sentido capital. O cadastro diz que é trecho da Autoban, e foi para a conservação de lá com cópia para o CCO." |
| 5 | 1:40–2:05 | Gmail do grupo: e-mail ao responsável e confirmação com protocolo | "A equipe recebe tudo padronizado: localização, prazo de 2 horas e o porquê da classificação. Quem relatou recebe o protocolo." |
| 6 | 2:05–2:20 | Mande de novo, de outro jeito: *"Tem um buraco enorme na Bandeirantes km 72 sentido São Paulo, estourou meu pneu."* | "Um usuário relata o mesmo buraco. O robô registra, mas avisa: possível duplicata do protocolo anterior. A equipe não sai duas vezes." |
| 7 | 2:20–2:50 | Copie `amostras/planilhas/checklist_inspecao_viaoeste.xlsx` para `entrada/` | "Agora a captura por arquivo: o checklist semanal de uma equipe de inspeção, com título antes do cabeçalho. Cada linha virou uma solicitação. As pedras de carga na faixa 2 foram para crítico; o lixo no acostamento, para baixa." |
| 8 | 2:50–3:15 | Mande sem km: *"Passei pela Castello e tem um buraco enorme depois do pedágio de Itapevi."* Depois responda com *"Era o km 33"* e o protocolo no assunto | "Sem km, o robô não manda a equipe procurar: pede a informação. Quando a resposta chega com o protocolo, a IA reanalisa e encaminha." |
| 9 | 3:15–3:30 | Mande o texto da amostra `10_tentativa_manipulacao.eml` | "Uma mensagem tenta mandar a IA classificar como crítico. A IA trata o conteúdo como dado e manda para fora do escopo." |
| 10 | 3:30–3:50 | `saida/solicitacoes.xlsx` (registro e histórico) | "Tudo fica registrado com protocolo, localização, concessão, motor usado e histórico de cada etapa." |
| 11 | 3:50–4:25 | Em outro terminal: `python main.py voz` (ou `/docs` da API) | "Essa é a base do agente de voz: o inspetor relata sem dizer o km, o agente pergunta, complementa e já avisa que existe outra solicitação aberta ali. Ele também pode perguntar o que está pendente perto do km onde está." |
| 12 | 4:25–4:45 | `avaliacao/resultado_openai.md` ao lado de `resultado_regras.md` | "Medimos em 32 casos rotulados. Regras fixas acham rodovia e km, mas erram a urgência: detectam só 5 de 12 críticos. A IA…" (completar com o número de vocês) |

## Dicas

- Se o Gmail demorar, rode `python main.py emails` em vez de esperar o ciclo.
- Cena 8 com `ENVIO_REDIRECIONAR_PARA`: o pedido de informação chega na caixa do grupo, não no e-mail pessoal. Para simular a resposta, mande do e-mail pessoal uma mensagem com o protocolo no assunto (ex.: `Re: [CNS-2026-000004]`) e o km no corpo.
- Grave em 1080p e corte as esperas na edição.
- Plano B sem internet: `python main.py demo --limpar` (com `ENVIO_MODO=arquivo`) mostra o fluxo completo com as amostras.
- As falas da tabela descrevem o resultado esperado. Ajustem ao que a IA realmente classificar na gravação.
