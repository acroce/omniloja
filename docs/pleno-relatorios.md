# Relatorios SQL - Pleno

## Parametros de entrada

Todas as queries do arquivo [reports/pleno_relatorios.sql](/Users/alexandrematheuscrose/Documents/Codex/2026-05-19/tabelas-pleno-vamos-criar-uma-conex/reports/pleno_relatorios.sql) usam os parametros abaixo:

```sql
SET @data_inicial = '2026-05-01';
SET @data_final = '2026-05-12';
SET @filial_numero = NULL;
```

Regras:

- `@data_inicial` e `@data_final` sao obrigatorios e usam `BETWEEN 'AAAA-MM-DD' AND 'AAAA-MM-DD'`.
- `@filial_numero` e opcional; usar `NULL` para todas as lojas.
- O filtro de loja sempre deve usar `cfg06_filial.cfg06_numero`.
- Nao confundir `cfg06_numero` com `cfg06_id`.

## Validacoes iniciais

Antes de usar qualquer consolidacao por caixa:

- Rode a auditoria de duplicidade de abertura por loja/data/PDV.
- Se houver mais de uma abertura no mesmo PDV/data, use consolidacao previa por `MIN(fcx07_id)`.
- Para recebimentos, valide o cadastro real de `cfg09_mpagto`.
- Para recebimentos, compare `fcx22_valor` com `fcx22_valor_entrada` antes de homologar o relatorio.

No schema real validado nesta base:

- `cfg09_codigo = 1` -> `DINHEIRO`
- `cfg09_codigo = 2` -> `CARTAO CREDITO A VISTA`
- `cfg09_codigo = 3` -> `CARTAO DEBITO`
- `cfg09_codigo = 9` -> `PIX`
- `cfg09_codigo = 10` -> `VALE TROCA (DEVOLUCAO)`
- `cfg09_codigo = 11` -> `CARTAO PARCELADO`
- `cfg09_codigo = 12` -> `IFOOD`

## Relatorio 00 - Auditoria de duplicidade de abertura

Objetivo:
Identificar loja/data/PDV com mais de uma linha em `fcx07_abertura`, evitando duplicidade em comparativos de vendas, ECF, encerramento e retiradas.

Tabelas usadas:

- `fcx07_abertura`
- `cfg06_filial`

Relacionamentos:

- `fcx07_abertura.cfg06_filial_id = cfg06_filial.cfg06_id`

Query SQL:
Consultar a secao `00. Auditoria de duplicidade de abertura por loja/data/PDV`.

Observacoes de validacao:

- Qualquer `COUNT(*) > 1` exige consolidacao por `cfg06_filial_id + fcx07_data + fcx07_pdv`.
- Essa auditoria deve ser o primeiro passo quando houver divergencia entre cupom, ECF e encerramento.

## Relatorio 01 - Conferencia de meios de pagamento

Objetivo:
Validar os codigos de meios de pagamento e comparar os campos `fcx22_valor`, `fcx22_valor_entrada`, `fcx22_valor_saida` e `fcx22_valor_residuo`.

Tabelas usadas:

- `fcx22_encerramento_item`
- `fcx20_encerramento`
- `fcx07_abertura`
- `cfg06_filial`
- `cfg09_mpagto`

Relacionamentos:

- `fcx22_encerramento_item.fcx20_encerramento_id = fcx20_encerramento.fcx20_id`
- `fcx20_encerramento.fcx07_abertura_id = fcx07_abertura.fcx07_id`
- `fcx07_abertura.cfg06_filial_id = cfg06_filial.cfg06_id`
- `fcx22_encerramento_item.cfg09_mpagto_id = cfg09_mpagto.cfg09_id`

Query SQL:
Consultar as secoes `01. Conferencia de meios de pagamento e campos de recebimento` e `02. Cadastro de meios de pagamento`.

Observacoes de validacao:

- Nao assumir que `cfg09_codigo` do ambiente produtivo sera igual ao de outro ambiente.
- Nao assumir que o valor oficial do recebimento e `fcx22_valor`; comparar com `fcx22_valor_entrada`.
- Se houver residuos relevantes, considerar `fcx22_valor_residuo` na conciliacao.

## Relatorio 03 - Vendas por loja, data e PDV com ECF

Objetivo:
Comparar total de cupons validos versus venda ECF por loja/data/PDV.

Tabelas usadas:

- `fcx07_abertura`
- `cfg06_filial`
- `fcx01_cupom`
- `fcx11_venda_ecf`
- `fcx10_ecf`

Relacionamentos:

- `fcx07_abertura.cfg06_filial_id = cfg06_filial.cfg06_id`
- `fcx01_cupom.cfg06_filial_id = cfg06_filial.cfg06_id`
- `fcx11_venda_ecf.fcx10_ecf_id = fcx10_ecf.fcx10_id`
- `fcx10_ecf.cfg06_filial_id = cfg06_filial.cfg06_id`

Query SQL:
Consultar a secao `03. Vendas por loja, data e PDV com comparacao ECF`.

Observacoes de validacao:

- Cupom valido usa `IFNULL(fcx01_flgestornado, 0) = 0` e `IFNULL(fcx01_cupom_id_cancelado, 0) = 0`.
- O comparativo parte de `abertura_unica` para neutralizar duplicidade por PDV/data.
- A divergencia principal fica em `diferenca_cupom_ecf_bruta`.

## Relatorio 04 - Retiradas individuais em dinheiro

Objetivo:
Listar retiradas unitarias em dinheiro com operador, supervisor, data, hora e PDV.

Tabelas usadas:

- `fcx18_retirada`
- `fcx07_abertura`
- `cfg06_filial`
- `fcx19_retirada_item`
- `cfg09_mpagto`
- `adm05_usuario`

Relacionamentos:

- `fcx18_retirada.fcx07_abertura_id = fcx07_abertura.fcx07_id`
- `fcx19_retirada_item.fcx18_retirada_id = fcx18_retirada.fcx18_id`
- `fcx19_retirada_item.cfg09_mpagto_id = cfg09_mpagto.cfg09_id`

Query SQL:
Consultar a secao `04. Retiradas individuais em dinheiro`.

Observacoes de validacao:

- Para retiradas individuais, nao usar `SUM`.
- O valor principal exibido deve ser `ri.fcx19_valor`.
- O filtro de dinheiro usa `mp.cfg09_codigo = 1`, mas esse codigo deve ser homologado pela consulta de cadastro.

## Relatorio 05 - Total de retiradas por abertura

Objetivo:
Somar retiradas por abertura de caixa para conciliacao com encerramento.

Tabelas usadas:

- `fcx18_retirada`
- `fcx19_retirada_item`
- `fcx07_abertura`
- `cfg06_filial`

Relacionamentos:

- `fcx18_retirada.fcx07_abertura_id = fcx07_abertura.fcx07_id`
- `fcx19_retirada_item.fcx18_retirada_id = fcx18_retirada.fcx18_id`

Query SQL:
Consultar a secao `05. Total de retiradas por abertura`.

Observacoes de validacao:

- Aqui a soma correta e `SUM(ri.fcx19_valor_saida)`.
- O agrupamento deve respeitar a abertura real, nao apenas loja/data/PDV.

## Relatorio 06 - Encerramento de caixa com retiradas

Objetivo:
Consolidar encerramento, recebimentos, meios de pagamento, residuos e retiradas.

Tabelas usadas:

- `fcx20_encerramento`
- `fcx07_abertura`
- `cfg06_filial`
- `adm05_usuario`
- `fcx22_encerramento_item`
- `fcx18_retirada`
- `fcx19_retirada_item`

Relacionamentos:

- `fcx20_encerramento.fcx07_abertura_id = fcx07_abertura.fcx07_id`
- `fcx07_abertura.cfg06_filial_id = cfg06_filial.cfg06_id`
- `fcx22_encerramento_item.fcx20_encerramento_id = fcx20_encerramento.fcx20_id`
- `fcx18_retirada.fcx07_abertura_id = fcx07_abertura.fcx07_id`
- `fcx19_retirada_item.fcx18_retirada_id = fcx18_retirada.fcx18_id`

Query SQL:
Consultar a secao `06. Encerramento de caixa com retiradas e residuos`.

Observacoes de validacao:

- `residuo_mpagto` e `retirada_total` foram pre-agregados para evitar multiplicacao de linhas.
- A diferenca principal esta em `fcx20_vlrtotrecebto - fcx20_vlrtotmpagto`.
- `fcx20_flgfinalizado` define a situacao do encerramento.

## Relatorio 07 - Recebimentos por loja e periodo em colunas

Objetivo:
Gerar uma visao tipo Excel com meios de pagamento em colunas.

Tabelas usadas:

- `fcx22_encerramento_item`
- `fcx20_encerramento`
- `fcx07_abertura`
- `cfg06_filial`
- `cfg09_mpagto`

Relacionamentos:

- `fcx22_encerramento_item.fcx20_encerramento_id = fcx20_encerramento.fcx20_id`
- `fcx20_encerramento.fcx07_abertura_id = fcx07_abertura.fcx07_id`
- `fcx07_abertura.cfg06_filial_id = cfg06_filial.cfg06_id`
- `fcx22_encerramento_item.cfg09_mpagto_id = cfg09_mpagto.cfg09_id`

Query SQL:
Consultar a secao `07. Recebimentos por loja e periodo em colunas`.

Observacoes de validacao:

- A query usa `fcx22_valor_entrada` nas colunas e traz `SUM(i.fcx22_valor)` junto para comparacao.
- Ajuste os `CASE WHEN` sempre que o cadastro real de `cfg09_mpagto` mudar.
- Se quiser todas as lojas, mantenha `@filial_numero = NULL`.

## Relatorio 08 - Itens vendidos por loja, data e SKU

Objetivo:
Analisar movimentacao de vendas em nivel de item.

Tabelas usadas:

- `fcx02_cupom_item`
- `fcx01_cupom`
- `mcd01_mercadoria`
- `cfg06_filial`

Relacionamentos:

- `fcx02_cupom_item.fcx01_cupom_id = fcx01_cupom.fcx01_id`
- `fcx02_cupom_item.mcd01_mercadoria_id = mcd01_mercadoria.mcd01_id`
- `fcx01_cupom.cfg06_filial_id = cfg06_filial.cfg06_id`

Query SQL:
Consultar a secao `08. Itens vendidos por loja, data e SKU`.

Observacoes de validacao:

- A query exclui cupom cancelado/estornado e item estornado.
- Esse relatorio ajuda a cruzar venda com estoque e investigacao de divergencia por SKU.

## Relatorio 09 - Notas de transferencia pendentes de entrada

Objetivo:
Listar NFs de saida cujo estoque ainda nao foi realizado na loja destino.

Tabelas usadas:

- `fis01_notafiscal`
- `pes04_pessoa`
- `pes03_estabelecimento`
- `cfg06_filial`
- `fis02_notafiscal_item`
- `est05_estoque_movimento`

Relacionamentos:

- `fis01_notafiscal.pes04_pessoa_emit = pes04_pessoa.pes04_id`
- `fis01_notafiscal.pes04_pessoa_dest = pes04_pessoa.pes04_id`
- `pes04_pessoa.pes03_estabelecimento_id = pes03_estabelecimento.pes03_id`
- `cfg06_filial.pes03_estabelecimento_id = pes03_estabelecimento.pes03_id`
- `fis02_notafiscal_item.fis01_notafiscal_id = fis01_notafiscal.fis01_id`
- `est05_estoque_movimento.fis02_notafiscal_item_id = fis02_notafiscal_item.fis02_id`

Query SQL:
Consultar a secao `09. Notas de transferencia pendentes de entrada`.

Observacoes de validacao:

- A regra de pendencia usa `NOT EXISTS` sobre qualquer item da nota no estoque movimento.
- Para transferencia CD -> loja, a loja destino e obtida via `pes04_pessoa_dest`.

## Relatorio 10 - Pedidos de transferencia com status herdado

Objetivo:
Marcar todos os itens do pedido como `Entrada realizada` quando qualquer item do pedido ja estiver vinculado a NF fisica.

Tabelas usadas:

- `com16_pretransferencia`
- `com19_pretransferencia_item`
- `cfg06_filial`
- `com33_pedtransf_atendido`
- `fis25_notafiscal_item_fisico`
- `fis01_notafiscal`
- `mcd01_mercadoria`

Relacionamentos:

- `com19_pretransferencia_item.com16_pretransferencia_id = com16_pretransferencia.com16_id`
- `com16_pretransferencia.cfg06_filial_dest_id = cfg06_filial.cfg06_id`
- `com33_pedtransf_atendido.com19_pretransferencia_item_id = com19_pretransferencia_item.com19_id`
- `fis25_notafiscal_item_fisico.fis25_id = com33_pedtransf_atendido.fis25_notafiscal_item_fisico_id`
- `fis01_notafiscal.fis01_id = fis25_notafiscal_item_fisico.fis01_notafiscal_id`

Query SQL:
Consultar a secao `10. Pedidos de transferencia com status herdado do pedido`.

Observacoes de validacao:

- A CTE `status_pedido` herda o status no nivel do pedido.
- Mesmo que apenas um item tenha NF vinculada, todos os itens do pedido passam a `Entrada realizada`.

## Notas de performance

- As queries filtram o periodo o mais cedo possivel nas tabelas factuais.
- Os agrupamentos foram empurrados para subconsultas ou CTEs para reduzir join de granularidades diferentes.
- Em relatorios de caixa, nao juntar diretamente itens de encerramento com itens de retirada sem pre-agregar.
- Em analises por loja, o filtro final deve sempre usar `cfg06_numero`.
