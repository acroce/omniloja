# Auditoria diaria de estoque no Pleno

Objetivo: gerar um pacote diario, somente com dados do Pleno, para auditar se as movimentacoes explicam o estoque por loja/SKU/dia.

## Parte 1 - servidor

No servidor, leve a pasta `tabelas-pleno-vamos-criar-uma-conex` contendo pelo menos:

- `scripts/export_pleno_stock_audit.py`
- `scripts/export_pleno_stock_snapshot.py`
- `scripts/run_pleno_stock_audit_server.sh`
- `scripts/run_pleno_stock_snapshot_server.sh`
- `config/pleno_stock_audit_lojas.txt`
- `.env`
- `.python_packages`, se o servidor nao tiver `pymysql` instalado globalmente

Arquivo `.env` esperado:

```text
MYSQL_HOST=172.22.20.101
MYSQL_PORT=3306
MYSQL_USER=diabrasil
MYSQL_PASSWORD=...
MYSQL_DATABASE=pleno
```

Arquivo de lojas:

```bash
cp config/pleno_stock_audit_lojas.example.txt config/pleno_stock_audit_lojas.txt
```

Depois edite `config/pleno_stock_audit_lojas.txt` com uma loja por linha ou em lista:

```text
155
203
586
```

### Coleta fechada do dia

Essa coleta usa o estoque diario do Pleno e as trilhas do periodo: vendas, movimentos, notas, pedidos e inventarios.

```bash
scripts/run_pleno_stock_audit_server.sh --date 2026-07-06 --lojas 155,203
```

Sem `--lojas`, exporta todas as lojas. Sem datas, exporta ontem. O pacote fica em:

```text
outputs/pleno_stock_audit_packages/YYYY-MM-DD_lojas_155-203.tar.gz
```

Periodo:

```bash
scripts/run_pleno_stock_audit_server.sh --start-date 2026-07-01 --end-date 2026-07-06 --lojas 155,203
```

Exemplo de cron diario as 01:30, auditando o dia anterior:

```cron
30 1 * * * /caminho/tabelas-pleno-vamos-criar-uma-conex/scripts/run_pleno_stock_audit_server.sh >> /var/log/pleno_stock_audit.log 2>&1
```

### Snapshots de estoque atual

Essa coleta pega o `est06_estoque_atual` no momento da execucao. Use para comparar dois horarios do mesmo dia, por exemplo 06:00 e 23:30, principalmente quando pode existir inventario no meio do caminho.

```bash
scripts/run_pleno_stock_snapshot_server.sh --label 0600
scripts/run_pleno_stock_snapshot_server.sh --label 2330
```

Exemplo de cron para duas exportacoes:

```cron
0 6 * * * /caminho/tabelas-pleno-vamos-criar-uma-conex/scripts/run_pleno_stock_snapshot_server.sh --label 0600 >> /var/log/pleno_stock_snapshot.log 2>&1
30 23 * * * /caminho/tabelas-pleno-vamos-criar-uma-conex/scripts/run_pleno_stock_snapshot_server.sh --label 2330 >> /var/log/pleno_stock_snapshot.log 2>&1
```

## Parte 2 - maquina local

Depois de trazer os `.tar.gz` ou as pastas para esta maquina, importe para SQLite:

```bash
python3 scripts/import_pleno_stock_audit_local.py outputs/pleno_stock_audit_packages/2026-07-06_lojas_155-203.tar.gz --replace-run
python3 scripts/import_pleno_stock_audit_local.py outputs/pleno_stock_snapshot_packages/2026-07-06_060000_0600_lojas_155-203.tar.gz --replace-run
python3 scripts/import_pleno_stock_audit_local.py outputs/pleno_stock_snapshot_packages/2026-07-06_233000_2330_lojas_155-203.tar.gz --replace-run
```

SQLite padrao:

```text
outputs/pleno_stock_audit.sqlite
```

Esse SQLite sera a base da dashboard local.

## Trilhas exportadas

- `estoque_diario_loja.csv`: resumo por loja/dia com estoque inicial, fim, venda e valor de custo.
- `estoque_diario_sku.csv`: estoque inicial/final por loja/SKU/dia, com valor de custo de inicio e fim.
- `vendas_sku.csv`: itens vendidos por cupom, excluindo cupom/item estornado, com quantidade e valor de venda.
- `movimentos_estoque.csv`: todos os movimentos do `est05_estoque_movimento`, classificados por origem, com quantidade, valor de custo, codigo/causa de devolucao e vinculo de retificacao quando existir.
- `movimentos_resumo.csv`: resumo de movimentos por loja/dia/origem, com quantidade e valor de custo.
- `notas_entrada.csv`: entradas de NF no Pleno, com quantidade, valor da nota/item e sinalizacao se gerou movimento de estoque.
- `notas_pendentes_entrada.csv`: notas de entrada que ja existem no Pleno mas ainda estao sem check-in/entrada, com data de emissao, dias pendentes e valor.
- `pedidos_transferencia.csv`: pedidos feitos pela loja e situacao de entrada realizada/pendente, com quantidade e valor pelo custo atual.
- `retificacoes.csv`: ajustes/retificacoes de recebimento do Pleno (`dia01_ajustes_recebimento`), com NF, albaran, tipo de operacao, aprovacao e quantidades.
- `inventarios.csv`: inventarios criados no periodo, com diferenca de quantidade e valor de custo entre sistema e contagem.
- `conciliacao_sku.csv`: principal arquivo de auditoria. Calcula `qtd_inicio + qtd_movimento` e compara com `qtd_fim_pleno`; tambem calcula o mesmo caminho em valor de custo.
- `top_movimentos.csv`: maiores movimentos por valor de custo absoluto para priorizar investigacao.
- `manifest.json`: data de geracao, filtros usados e quantidade de linhas por arquivo.

## Views locais

O importador cria as views iniciais:

- `vw_auditoria_divergencias`: SKUs em que `qtd_inicio + qtd_movimento` nao bate com `qtd_fim_pleno`.
- `vw_movimentos_sem_causa`: movimentos no `est05` sem NF, venda, boletim ou inventario vinculado.
- `vw_snapshots_estoque`: snapshots do estoque atual, com label/horario da coleta.

Nas cargas novas, todo campo relevante de quantidade passa a ter o par de valor/custo correspondente quando o Pleno disponibiliza custo ou valor unitario.

## Leitura da conciliacao

Campos principais:

- `qtd_inicio`: estoque do inicio do dia no `est01_estoque_diario`.
- `valor_inicio_custo`: valor de custo do estoque inicial.
- `qtd_movimento`: soma assinada dos movimentos do `est05`.
- `valor_movimento_custo`: valor de custo assinado dos movimentos do `est05`.
- `qtd_fim_esperado`: `qtd_inicio + qtd_movimento`.
- `valor_fim_esperado_custo`: `valor_inicio_custo + valor_movimento_custo`.
- `qtd_fim_pleno`: estoque final gravado no `est01`.
- `valor_fim_pleno_custo`: valor de custo do estoque final gravado no `est01`.
- `divergencia_qtd`: diferenca nao explicada pela trilha de movimentos.
- `divergencia_valor_custo`: diferenca em valor de custo.
- `qtd_sem_causa_movimento`: movimentos no `est05` sem vinculo claro com NF, venda, boletim ou inventario.
- `valor_sem_causa_movimento`: valor de custo dos movimentos sem causa classificada.
- `qtd_nf_entrada_movimento`: entradas de notas que bateram no movimento de estoque.
- `valor_nf_entrada_movimento`: valor das entradas de notas que bateram no movimento de estoque.
- `devolucao_codigos` / `devolucao_causa_codigos` / `devolucao_causas`: trilha de devolucao vinda de `est09_troca_movimento` e `adm22_motivo_troca`.
- `retificacao_ids` / `retificacao_albarans` / `retificacao_tipos`: vinculo da movimentacao com retificacao de recebimento quando houver `fis02_notafiscal_item_id`.
- `qtd_inventario_movimento`: ajuste vindo de inventario.
- `valor_inventario_movimento`: valor de custo do ajuste vindo de inventario.

Regra de auditoria inicial:

```text
divergencia_qtd = 0      -> movimento explica o estoque
divergencia_qtd <> 0     -> investigar SKU/dia/loja
divergencia_valor_custo alto -> priorizar, mesmo quando a quantidade parece pequena
qtd_sem_causa_movimento <> 0 -> priorizar, pois o movimento existe sem causa classificada
pedido Pendente Entrada  -> verificar atraso/ausencia de entrada da nota
NF com movimentos_estoque = 0 -> nota entrou no fiscal, mas nao aparece como estoque realizado
nota pendente entrada     -> NF existente no Pleno sem check-in/entrada
inventario no dia        -> separar divergencia operacional de ajuste de contagem
```

## Proxima etapa

A dashboard local deve ler os CSVs e mostrar:

- visao por loja/dia com status OK/divergente;
- ranking de divergencias por valor de custo;
- trilha de cada SKU: estoque inicial, vendas, entradas NF, inventario, movimentos sem causa e estoque final;
- filtro de pedidos pendentes e notas de entrada sem movimento de estoque;
- historico diario para ver repeticao por loja/produto.
