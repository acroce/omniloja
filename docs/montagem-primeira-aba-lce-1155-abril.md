# Montagem da Primeira Aba do LCE - Loja 1155 - Abril/2026

Arquivo analisado:

- [Rascunho novo LCE.xlsx](/Users/alexandrematheuscrose/Downloads/Rascunho%20novo%20LCE.xlsx)

SQL de apoio:

- [reports/lce_1155_abril_2026.sql](/Users/alexandrematheuscrose/Documents/Codex/2026-05-19/tabelas-pleno-vamos-criar-uma-conex/reports/lce_1155_abril_2026.sql)

## O que fecha

A linha `1155` da aba `NOVO LCE Pleno Arius` fecha assim:

| Bloco | Coluna | Valor |
|---|---|---:|
| Recebimento | 01.01.01-SC DINHEIRO | 72.030,66 |
| Recebimento | 01.01.03-SC CARTAO DEBITO C | 313.093,35 |
| Recebimento | 01.01.04-SC CARTOES A VISTA | 333.811,32 |
| Recebimento | 01.01.08-SC VALE TROCA (DEVOLUCAO) | 706,12 |
| Recebimento | 01.01.09-SC TRANSAÇÃO PIX C | 72.034,95 |
| Recebimento | 01.01.10-SC CREDITO PARCELADO | 51.382,38 |
| Recebimento | 01.01.11-SC IFOOD C | 0,00 |
| Recebimento | 01.02-TROCO | 4.000,00 |
| Recebimento | 01.03-SC SOBRA DE CAIXA | 132,61 |
| Transferência | COFRE INTELIGENTE | 74.591,00 |
| Transferência | ROUBOS E NOTA FALSA | 0,00 |
| Transferência | TROCO E FUNDO FIXO | 0,00 |
| Pagamento | 02.02.02-TROCO | 4.080,00 |
| Pagamento | 02.03-SC QUEBRA DE CAIXA | 214,24 |
| Pagamento | 02.02.01.01-SU DESPESAS C/LANCHES E REFEIÇÕES C | 49,14 |
| Pagamento | 02.02.01.03-SU MANUTENÇÃO E LIMPEZA C | 0,00 |
| Pagamento | 02.02.01.04-SU MATERIAL DE ESCRITÓRIO | 0,00 |
| Pagamento | 02.02.01.06-SU PROPAGANDA E PUBLICIDADE C | 0,00 |

## De onde cada valor sai

### Recebimento

No MySQL, a origem é:

- `fin07_transacao`
- `fin11_categoria`
- `cfg06_filial`

Regra que reproduz a primeira aba:

- `cfg06_filial.cfg06_numero = 1155`
- `dom22_situacao_trans_financeira_id = 2` (`LIQUIDADO`)
- `fin07_data_vencto_realizada BETWEEN '2026-04-01' AND '2026-04-30'`
- categorias `01.01.01`, `01.01.03`, `01.01.04`, `01.01.08`, `01.01.09`, `01.01.10`, `01.01.11`, `01.02`, `01.03`
- para abril/2026, a primeira aba exclui os lancamentos de `2026-04-17`

Sem excluir `2026-04-17`, os valores ficam iguais ao bruto do financeiro/caixa e batem com a aba `Relat Vendas meio de pagamento`.

### Transferência

No MySQL, a origem tambem aparece em:

- `fin07_transacao`
- `fin11_categoria`
- `cfg06_filial`

Regra:

- `cfg06_filial.cfg06_numero = 1155`
- `dom22_situacao_trans_financeira_id = 2`
- `fin07_data_vencto_realizada BETWEEN '2026-04-01' AND '2026-04-30'`
- `fin11_codigo = '03.01'`

Aqui nao houve a exclusao de `2026-04-17`. O valor `74.591,00` bate direto.

### Pagamento

No MySQL, a origem tambem esta em:

- `fin07_transacao`
- `fin11_categoria`
- `cfg06_filial`

Regra:

- `cfg06_filial.cfg06_numero = 1155`
- `dom22_situacao_trans_financeira_id = 2`
- `fin07_data_vencto_realizada BETWEEN '2026-04-01' AND '2026-04-30'`
- categorias `02.02.01.01`, `02.02.01.03`, `02.02.01.04`, `02.02.01.06`, `02.02.02`, `02.03`
- para abril/2026, a coluna `02.03-SC QUEBRA DE CAIXA` da primeira aba tambem exclui `2026-04-17`

## Ponto de atenção principal

Existe uma anomalia operacional importante:

- a aba `Recebimento` do arquivo nao contem os valores de `17/04/2026`
- a aba `Pagamento` tambem nao leva `17/04/2026` para `02.03-SC QUEBRA DE CAIXA`
- a aba `Transferência` nao tem esse corte

Impacto do dia `17/04/2026` que ficou fora da primeira aba:

| Categoria | Valor excluído |
|---|---:|
| 01.01.01-SC DINHEIRO | 2.570,00 |
| 01.01.03-SC CARTAO DEBITO C | 11.825,38 |
| 01.01.04-SC CARTOES A VISTA | 11.757,44 |
| 01.01.09-SC TRANSAÇÃO PIX C | 3.178,90 |
| 01.01.10-SC CREDITO PARCELADO | 1.502,50 |
| 02.03-SC QUEBRA DE CAIXA | 52,08 |

## Leitura prática

Para montar a primeira aba ate SAP, hoje a regra mais segura e:

1. Usar `fin07_transacao` como base.
2. Filtrar por `cfg06_filial_referencia_id` da loja 1155.
3. Filtrar `LIQUIDADO`.
4. Consolidar por `fin11_categoria`.
5. Em abril/2026, reproduzir a primeira aba excluindo `2026-04-17` apenas para `Recebimento` e `Quebra de Caixa`.
6. Manter `03.01-SC TRANSFERENCIA ENTRE CONTAS` sem essa exclusao.

## Proximo passo sugerido

Se quiser, eu posso fazer uma segunda entrega em cima disso:

- montar uma copia da planilha com a primeira aba preenchida por formulas
- ou transformar essa logica em um unico SQL pivotado para qualquer loja e qualquer mes
- ou ainda investigar por que `17/04/2026` ficou fora do export original
