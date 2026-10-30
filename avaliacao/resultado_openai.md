# Avaliação — motor `openai:gpt-4.1-mini`

Casos: **32** · erros de execução: 0 · tempo médio: 2.34 s

| Métrica | Resultado |
|---|---|
| Categoria correta | 97% |
| Urgência correta (só IA) | 88% |
| Urgência correta (IA + regras de negócio) | 84% |
| Urgência a no máximo 1 nível | 100% |
| Casos críticos detectados | 12 de 12 |
| Localização correta (rodovia + km) | 97% |

## Matriz de confusão da categoria (linha = esperado, coluna = previsto)

| esperado \ previsto | PAVIMENTO | SINALIZACA | DISPOSITIV | DRENAGEM | ILUMINACAO | VEGETACAO | OCORRENCIA | FORA |
|---|---|---|---|---|---|---|---|---|
| PAVIMENTO | 5 |  |  |  |  |  |  |  |
| SINALIZACA |  | 4 |  |  |  |  |  |  |
| DISPOSITIV |  |  | 4 |  |  |  |  |  |
| DRENAGEM |  |  |  | 4 |  |  |  |  |
| ILUMINACAO |  |  |  |  | 3 |  |  |  |
| VEGETACAO | 1 |  |  |  |  | 5 |  |  |
| OCORRENCIA |  |  |  |  |  |  | 3 |  |
| FORA |  |  |  |  |  |  |  | 3 |

## Divergências

| Caso | Esperado | Previsto | Texto |
|---|---|---|---|
| c06 | urgência: MEDIA | BAIXA | Pintura da faixa de pedestres no km 22 da Castello está desbotada, pre… |
| c07 | local: SP-348 km ? | SP-348 km 98 | Placa de indicação da saída 98 está torta, virada pro mato, Bandeirant… |
| c16 | urgência: MEDIA | ALTA | Três luminárias apagadas no trevo do km 26 da Castello. O trevo ainda … |
| c19 | urgência: ALTA | CRITICA | Eucalipto inclinado na beira da pista, raiz exposta, pode cair a qualq… |
| c20 | categoria: VEGETACAO_LIMPEZA | PAVIMENTO | Mancha grande de óleo na pista do km 42 da Bandeirantes, sentido inter… |
| c30 | urgência: ALTA | MEDIA | o mato tá tão alto no trevo do km 46 da castello que não dá pra ver qu… |
| c31 | urgência: MEDIA | ALTA | Linha 6 da planilha 'ronda.xlsx' (aba Semana 45): Rodovia: SP-330 KM: … |
