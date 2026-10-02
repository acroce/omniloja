# Triagem manual de OCR - Cofre Inteligente

Regra de aprovação: o comprovante deve ter data inicial e final iguais à data prevista no Pleno e total, total geral ou combinação de subtotais igual ao valor da transferência. A confirmação da Brinks continua obrigatória antes de salvar.

| Transação | Loja | Prevista | Valor | Resultado visual | Diagnóstico | Ação técnica |
| --- | --- | --- | ---: | --- | --- | --- |
| 207057 | 189 - Barão de Limeira | 10/08/2026 | 200,00 | Reprovar | Documento GTV-e; não há período de depósito válido e a data visível diverge. | Manter como falha correta. |
| 194446 | 1169 - Sócrates | 18/08/2026 | 2.237,00 | Reprovar | Recibo apresenta total geral visível de 2.376,00. | Manter como falha correta. |
| 198539 | 224 - Água Fria | 18/08/2026 | 3.560,00 | Aprovar OCR | De/Até 18/08/2026 e total de 3.560,00. Tesseract lê alguns centavos incorretamente. | Preservar tolerância de centavos e reprocessar após confirmar seleção da data. |
| 195354 | 248 - Vieira de Morais | 18/08/2026 | 2.647,00 | Reprovar | Valor confere, mas período vai de 18/08/2026 até 19/08/2026. | Manter validação estrita das duas datas. |
| 194431 | 61 - Alto do Ipiranga | 18/08/2026 | 3.042,00 | Aprovar OCR | De/Até 18/08/2026; subtotais 1.495,00 + 1.547,00 = 3.042,00. | Recuperar data por ocorrências repetidas quando o rótulo estiver ilegível. |
| 198884 | 1038 - Casa Verde | 19/08/2026 | 2.441,00 | Pendente | Foto inclinada e comprovante sobreposto a outro documento; o total geral precisa de revisão ampliada. | Avaliar corte/rotação antes de reprocessar. |
| 198738 | 1076 - Louveira | 19/08/2026 | 1.429,00 | Aprovar OCR | De/Até 19/08/2026 e total geral 1.429,00 visíveis. | Reprocessar após a rodada de correções. |
| 198740 | 14 - Orfanato | 19/08/2026 | 1.643,00 | Reprovar | Recibo de 18/08/2026, total geral 1.579,00. | Manter como falha correta. |
| 200691 | 202 - JD. São Paulo | 19/08/2026 | 1.667,00 | Aprovar OCR | `From`/`To` 19/08/2026 e `Grand Total` 1.667,00. | Aceitar os rótulos equivalentes em inglês. |
| 198677 | 211 - Vila Olímpia | 19/08/2026 | 4.263,00 | Aprovar OCR | Recibo à esquerda: 1.197,00 + 2.089,00 + 977,00. Relatório à direita mostra 4.267,50 e deve ser ignorado. | Usar o recorte esquerdo para recibo misturado a relatório. |
| 198656 | 248 - Vieira de Morais | 19/08/2026 | 2.413,00 | Pendente | O painel não possui arquivo de evidência para a tentativa. | Classificar como anexo indisponível, não como falha de OCR. |
| 200615 | 260 - Ocian | 19/08/2026 | 2.894,00 | Aprovar OCR | De/Até 19/08/2026 e total geral 2.894,00. | Reprocessar após a rodada de correções. |
| 198809 | 292 - Aclimação | 19/08/2026 | 3.798,00 | Aprovar OCR | Recibo à esquerda, relatório ao fundo; total geral do recibo 3.798,00. | Recorte esquerdo deve prevalecer sobre o relatório de retiradas. |
| 198688 | 456 - Pedro Lessa | 19/08/2026 | 2.607,00 | Aprovar OCR | Foto fraca, mas De/Até e total geral 2.607,00 estão visíveis. | Aplicar contraste e preservar a leitura do recibo. |
| 198786 | 529 - Dona Gertrudes | 19/08/2026 | 1.814,00 | Aprovar OCR | De/Até 19/08/2026 e total geral 1.814,00. | Reprocessar após a rodada de correções. |
| 207063 | 137 - Oratório | 20/08/2026 | 2.029,00 | Aprovar OCR | Recibo à esquerda, De/Até 20/08/2026 e total geral 2.029,00. | Priorizar recibo sobre relatório de retiradas ao fundo. |
| 206870 | 14 - Orfanato | 20/08/2026 | 1.872,00 | Reprovar | Recibo de 23/08/2026, total geral 1.674,00. | Manter como falha correta. |
| 204283 | 61 - Alto do Ipiranga | 21/08/2026 | 4.147,00 | Reprovar | Recibo de 22/08/2026, total geral 2.271,00. | Manter como falha correta. |
| 204346 | 137 - Oratório | 22/08/2026 | 2.508,00 | Aprovar OCR | Recibo à esquerda, De/Até 22/08/2026 e total geral 2.508,00. | Priorizar recibo sobre relatório de retiradas ao fundo. |
| 204217 | 170 - Cursino | 22/08/2026 | 3.865,00 | Aprovar OCR | Comprovante lateral; De/Até 22/08/2026 e total geral 3.865,00. | Manter variantes de rotação para leitura de recibo. |
| 206223 | 225 - Atlântica | 22/08/2026 | 2.782,00 | Reprovar | Recibo identifica `DIA BRASIL 1225 - SP Santo André`, embora data e total sejam compatíveis. | Reprovar quando o cabeçalho do recibo identificar outra loja. |
| 211051 | 239 - Higienópolis | 22/08/2026 | 3.424,00 | Pendente | Arquivo baixado não é uma imagem JPEG válida. | Classificar como anexo corrompido/indisponível. |
| 204282 | 309 - Oswaldo Cruz | 22/08/2026 | 2.842,00 | Aprovar OCR | De/Até 22/08/2026 e total geral 2.842,00. | Reprocessar após a rodada de correções. |
| 204329 | 491 - Heitor Peixoto | 22/08/2026 | 1.301,00 | Aprovar OCR | Recibo sobre relatório, De/Até 22/08/2026 e total geral 1.301,00. | Usar recorte/rotação antes da leitura. |
| 213610 | 56 - Cantagalo | 22/08/2026 | 1.809,00 | Aprovar OCR | De/Até 22/08/2026; subtotais 730,00 + 1.079,00 = 1.809,00. | Manter soma de subtotais quando necessária. |
| 204563 | 94 - Celso Garcia | 22/08/2026 | 2.728,00 | Reprovar | Recibo é de 21/08/2026, apesar do total geral de 2.728,00. | Manter validação estrita das duas datas. |
| 205953 | 98 - Sabará | 22/08/2026 | 2.456,00 | Aprovar OCR | De/Até 22/08/2026 e total geral 2.456,00. | Reprocessar após a rodada de correções. |
| 207363 | 99 - Adriático | 22/08/2026 | 4.180,00 | Reprovar | De/Até corretos, mas total geral visível de 4.148,00. | Manter validação estrita de valor. |
| 204227 | 1033 - Cardoso de Melo | 23/08/2026 | 1.032,00 | Pendente | Arquivo não pôde ser aberto como imagem. | Classificar como anexo inválido/corrompido. |
| 210603 | 1045 - República | 23/08/2026 | 2.098,00 | Pendente | Arquivo não pôde ser aberto como imagem. | Classificar como anexo inválido/corrompido. |
| 204275 | 1060 - Fradique Coutinho | 23/08/2026 | 1.825,00 | Pendente | Painel sem evidência da tentativa. | Classificar como anexo indisponível. |
| 209750 | 1141 - Consolação | 23/08/2026 | 808,00 | Aprovar OCR | De/Até 23/08/2026 e total geral 808,00. | Reprocessar após a rodada de correções. |
| 204226 | 179 - Clínicas | 23/08/2026 | 1.923,00 | Aprovar OCR | Recibo lateral, De/Até 23/08/2026 e total geral 1.923,00. | Manter variantes de rotação. |
| 204752 | 203 - Morro Grande | 23/08/2026 | 3.064,00 | Reprovar | Recibo de 22/08/2026 e total geral 2.517,00. | Manter validações estritas. |
| 204295 | 211 - Vila Olímpia | 23/08/2026 | 2.987,00 | Reprovar | Recibo de 22/08/2026, embora o total geral seja 2.987,00. | Manter validação estrita da data. |
