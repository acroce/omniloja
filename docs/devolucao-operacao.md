# Operacao de Devolucoes Pleno x AS400

Este documento centraliza o processo que estamos usando para analisar devolucoes, importar arquivos, acompanhar status e gerar novos CSVs para o AS400.

Objetivo:

- nao perder o contexto entre consultas
- saber onde cada arquivo entra
- ter uma base unica para analise
- padronizar as proximas validacoes

## Visao Geral

Hoje a base principal de consulta e o SQLite central:

- [outputs/devolucao_central.sqlite](/Users/alexandrematheuscrose/Documents/Codex/2026-05-19/tabelas-pleno-vamos-criar-uma-conex/outputs/devolucao_central.sqlite)

Essa base cruza 4 fontes principais:

1. `pleno`
   Registros de devolucao que sairam do Pleno.
2. `envios_arquivo`
   Tudo que foi gerado/enviado localmente em arquivos CSV para o AS400.
3. `as400`
   Base consolidada do AS400 importada por planilha.
4. `as400_qlik`
   Base vinda do Qlik, com todas as abas importadas.

E uma quinta fonte complementar:

5. `as400_erros`
   Erros de integracao do AS400, como data errada e outras rejeicoes.

E agora uma sexta fonte operacional:

6. `as400_db2_live`
   Consulta viva no DB2 do AS400, usada para corrigir lacunas das planilhas antigas e recalcular conciliacao real.

## Regras de Ouro

- A comparacao principal sempre parte do `Pleno` para o `AS400`.
- Nunca assumir falta olhando apenas o AS400, porque existem lojas que nao migraram para o Pleno.
- Quando chegar arquivo novo, primeiro decidir em qual tabela ele entra.
- Quando houver duvida de status, consultar `pleno_status`, nao arquivos soltos.
- Quando gerar nova nota para reenvio, sempre validar prefixos ja usados para nao duplicar no AS400.

## Onde Cada Coisa Fica

Arquivos principais:

- Base central: [outputs/devolucao_central.sqlite](/Users/alexandrematheuscrose/Documents/Codex/2026-05-19/tabelas-pleno-vamos-criar-uma-conex/outputs/devolucao_central.sqlite)
- Base de auditoria antiga: [outputs/devolucao_auditoria.sqlite](/Users/alexandrematheuscrose/Documents/Codex/2026-05-19/tabelas-pleno-vamos-criar-uma-conex/outputs/devolucao_auditoria.sqlite)
- Saida de CSVs para AS400: [outputs/devolucao_as400](/Users/alexandrematheuscrose/Documents/Codex/2026-05-19/tabelas-pleno-vamos-criar-uma-conex/outputs/devolucao_as400)
- Pasta operacional de devolucoes recebidas/enviadas: [/Users/alexandrematheuscrose/Documents/Codex/2026-05-19/Devolucoes](/Users/alexandrematheuscrose/Documents/Codex/2026-05-19/Devolucoes)

Scripts principais:

- [scripts/build_devolucao_central_db.py](/Users/alexandrematheuscrose/Documents/Codex/2026-05-19/tabelas-pleno-vamos-criar-uma-conex/scripts/build_devolucao_central_db.py)
- [scripts/import_roturas_qlik_xlsb.py](/Users/alexandrematheuscrose/Documents/Codex/2026-05-19/tabelas-pleno-vamos-criar-uma-conex/scripts/import_roturas_qlik_xlsb.py)
- [scripts/import_integracao_ok_arius.py](/Users/alexandrematheuscrose/Documents/Codex/2026-05-19/tabelas-pleno-vamos-criar-uma-conex/scripts/import_integracao_ok_arius.py)
- [scripts/import_integracao_nok_arius.py](/Users/alexandrematheuscrose/Documents/Codex/2026-05-19/tabelas-pleno-vamos-criar-uma-conex/scripts/import_integracao_nok_arius.py)
- [scripts/generate_devolucao_as400_csv.py](/Users/alexandrematheuscrose/Documents/Codex/2026-05-19/tabelas-pleno-vamos-criar-uma-conex/scripts/generate_devolucao_as400_csv.py)
- [scripts/generate_devolucao_reenviar_csv.py](/Users/alexandrematheuscrose/Documents/Codex/2026-05-19/tabelas-pleno-vamos-criar-uma-conex/scripts/generate_devolucao_reenviar_csv.py)
- [scripts/import_devolucao_folder.py](/Users/alexandrematheuscrose/Documents/Codex/2026-05-19/tabelas-pleno-vamos-criar-uma-conex/scripts/import_devolucao_folder.py)

## Estrutura da Base Central

Tabelas atuais:

- `pleno`
- `envios_arquivo`
- `as400`
- `as400_qlik`
- `as400_erros`
- `as400_db2_live`
- `pleno_status`
- `resumo_status`
- `metadados`

## Papel de Cada Tabela

### `pleno`

Base operacional do que existe no Pleno para devolucao.

Campos de negocio mais usados:

- `loja`
- `nro_nf`
- `data_nf`
- `codigo_produto`
- `qtd_devolvida`
- `motivo`
- `tipo_unidade_venda`

Usar quando:

- precisamos saber se a devolucao existe no Pleno
- precisamos conferir itens e quantidades originais

### `envios_arquivo`

Historico do que foi gerado localmente em CSV para envio ao AS400.

Usar quando:

- precisamos saber se ja mandamos um item
- precisamos ver em qual arquivo ele foi enviado
- precisamos contar quantas vezes reenviamos

### `as400`

Base consolidada do AS400 importada por planilha.

Usar quando:

- precisamos saber se um item chegou no AS400
- precisamos ver nota e produto confirmados no AS400

### `as400_qlik`

Base do Qlik com todas as abas importadas.

Abas conhecidas hoje:

- `Confirmados`
- `Pendente`
- `Anulados`

Regra atual:

- so a aba `Confirmados` vale como conciliacao de fato
- `Pendente` e `Anulados` servem como contexto

### `as400_erros`

Base dos erros do AS400.

Usar quando:

- a devolucao foi comunicada, mas rejeitada
- precisamos saber se houve erro tipo `FE` ou outro retorno

### `as400_db2_live`

Base viva carregada diretamente do DB2 do AS400.

Usar quando:

- a planilha antiga do AS400 parecer incompleta
- um caso constar no terminal do AS400, mas nao aparecer na base local
- precisarmos recalcular a conciliacao real do `pleno_status`

Scripts ligados a essa carga:

- [scripts/import_as400_db2_live.py](/Users/alexandrematheuscrose/Documents/Codex/2026-05-19/tabelas-pleno-vamos-criar-uma-conex/scripts/import_as400_db2_live.py)
- [scripts/rebuild_pleno_status_only.py](/Users/alexandrematheuscrose/Documents/Codex/2026-05-19/tabelas-pleno-vamos-criar-uma-conex/scripts/rebuild_pleno_status_only.py)
- [scripts/import_as400_erros_db2_live.py](/Users/alexandrematheuscrose/Documents/Codex/2026-05-19/tabelas-pleno-vamos-criar-uma-conex/scripts/import_as400_erros_db2_live.py)

### `pleno_status`

Essa e a tabela principal para consulta do dia a dia.

Ela junta Pleno + arquivos enviados + AS400 + AS400 DB2 vivo + Qlik + erros do AS400.

Campos mais importantes:

- `loja`
- `nro_nf`
- `data_nf`
- `codigo_produto`
- `causa_pleno`
- `enviado`
- `conciliado_as400`
- `conciliado_qlik`
- `conciliado`
- `erro_as400`
- `primeiro_arquivo_enviado`
- `arquivos_enviados`
- `qtd_vezes_enviado_as400`
- `qtd_arquivos_enviados`
- `nota_as400_exemplo`
- `nota_qlik_exemplo`
- `origens_qlik`
- `status`

## Significado do Campo `status`

Valores mais usados hoje:

- `CONCILIADO`
  O item do Pleno apareceu no AS400 e/ou Qlik confirmado.
- `ENVIADO`
  O item saiu em arquivo, mas ainda nao apareceu confirmado.
- `PENDENTE_ENVIO`
  O item existe no Pleno e ainda nao apareceu como enviado.

## Contador de Envios

Toda vez que um item entrar em um novo arquivo enviado ao AS400, precisamos somar `+1` no historico de envios.

Essa regra vale mesmo quando:

- a nota usa o mesmo prefixo `99`
- o arquivo e um reenvio manual
- o item ja tinha aparecido em outro CSV anterior

Ou seja:

- novo arquivo enviado = nova tentativa registrada

## Como Ler os Contadores

Campos mais importantes:

- `qtd_vezes_enviado_as400`
  Quantidade de notas geradas distintas para aquele item.
- `qtd_arquivos_enviados`
  Quantidade de arquivos distintos em que aquele item apareceu.
- `arquivos_enviados`
  Lista dos arquivos em que o item foi enviado.

Regra pratica:

- se o item saiu em um arquivo novo, isso precisa aparecer no historico
- mesmo quando o numero gerado nao muda, o arquivo novo deve ser registrado
- por isso o acompanhamento mais seguro do dia a dia deve olhar tambem `qtd_arquivos_enviados`

Exemplo:

- envio 1: `DEVOLUCAO_A.csv`
- envio 2: `DEVOLUCAO_B.csv`
- envio 3: `DEVOLUCAO_C.csv`

Resultado esperado:

- `qtd_arquivos_enviados = 3`
- `arquivos_enviados` deve listar os 3 arquivos

Se, alem disso, mudamos a numeracao da nota:

- original
- `99XXXX`
- `98XXXX`

Entao tambem esperamos crescimento em:

- `qtd_vezes_enviado_as400`

## Regra obrigatoria apos cada envio

Sempre que um novo CSV for enviado ao AS400:

1. registrar o arquivo na base `envios_arquivo`
2. recalcular a `pleno_status`
3. confirmar se o historico daquele caso somou mais 1

Checklist rapido:

- arquivo novo foi salvo?
- arquivo novo foi registrado em `envios_arquivo`?
- `pleno_status` foi recalculada?
- `qtd_arquivos_enviados` aumentou?
- se houve nova numeracao, `qtd_vezes_enviado_as400` aumentou?

Resumo atual da base:

- `ENVIADO`: 51154
- `PENDENTE_ENVIO`: 32504
- `CONCILIADO`: 25716

## Fluxo Operacional

### 1. Receber um arquivo novo

Antes de importar, decidir a origem:

- planilha consolidada do AS400: vai para `as400`
- arquivo Qlik `.xlsb`: vai para `as400_qlik`
- planilha de erro do AS400: vai para `as400_erros`
- arquivos CSV enviados para AS400: vao para `envios_arquivo`
- nova extracao do Pleno: atualiza `pleno`

Regra combinada:

- sempre que chegar um arquivo novo, perguntar primeiro em qual tabela ele entra

### 2. Importar a fonte

Exemplos de scripts:

- Qlik: `scripts/import_roturas_qlik_xlsb.py`
- OK Arius/AS400: `scripts/import_integracao_ok_arius.py`
- NOK Arius/erros: `scripts/import_integracao_nok_arius.py`
- pasta de devolucoes CSV: `scripts/import_devolucao_folder.py`

### 3. Reconstruir a base central

Depois de atualizar as fontes, reconstruir a base central com:

- `scripts/build_devolucao_central_db.py`

### 4. Consultar

Sempre que possivel, consultar primeiro `pleno_status`.

## Convencao de Numeracao de Reenvio

Quando a mesma nota precisa ser reenviada:

- primeira variacao: `99XXXX`
- segunda variacao: `98XXXX`
- terceira variacao: `97XXXX`
- quarta variacao: `96XXXX`

Importante:

- nunca repetir uma numeracao ja usada por loja
- antes de gerar, verificar historico em `envios_arquivo` e nos arquivos locais
- antes de afirmar que "nao foi enviado", sempre procurar tambem as variantes prefixadas

### Regra obrigatoria de procura por prefixo

Sempre que analisarmos uma devolucao, nao basta procurar apenas a nota original.

Temos que procurar:

- nota original: `XXXX`
- primeira variacao: `99XXXX`
- segunda variacao: `98XXXX`
- terceira variacao: `97XXXX`
- quarta variacao: `96XXXX`
- e assim por diante, se houver mais tentativas

Exemplo:

- nota original `81`
- procurar `81`, `990081`, `980081`, `970081`, `960081`

Se a nota ja passou por `99`, `98` e `97`, isso significa que ela ja foi reenviada ao menos 3 vezes. Nesses casos, nunca tratar como "nao enviado" sem antes revisar esse historico.

## Ordem obrigatoria de verificacao antes de concluir "nao enviado"

Para qualquer consulta de divergencia, seguir sempre esta ordem:

1. Procurar a nota original no `pleno_status`.
2. Procurar no historico de arquivos enviados (`envios_arquivo` e pasta de CSVs locais).
3. Procurar as variacoes `99/98/97/96...` da mesma nota.
4. Procurar no `as400`.
5. Procurar no `as400_qlik`, principalmente aba `Confirmados`.
6. Procurar no `as400_erros`.

So depois disso podemos classificar o caso como:

- `nao enviado`
- `enviado e nao conciliado`
- `com erro no AS400`
- `divergencia sistemica`

## Regra de Data para Reenvio

Quando a data original da devolucao for antiga, usamos a data do mes anterior ao atual.

Exemplos:

- `01/04` pode virar `01/05`
- `03/03` pode virar `03/05`

Regra pratica atual:

- se a data for anterior ao mes anterior ao atual, normalizar para o mes anterior mantendo o dia quando possivel

## Casos Tipicos e Como Consultar

### 1. "Essa nota existe no Pleno?"

```sql
SELECT *
FROM pleno_status
WHERE loja = 428
  AND nro_nf = 153
ORDER BY codigo_produto;
```

### 2. "Ja enviamos essa devolucao para o AS400?"

```sql
SELECT
    loja,
    nro_nf,
    codigo_produto,
    enviado,
    primeiro_arquivo_enviado,
    qtd_vezes_enviado_as400
FROM pleno_status
WHERE loja = 428
  AND nro_nf = 153
ORDER BY codigo_produto;
```

Observacao:

- essa consulta e o primeiro passo
- se ela nao mostrar envio para a nota original, ainda precisamos procurar as variantes `99/98/97/96...`

### 3. "Ela chegou no AS400 ou no Qlik?"

```sql
SELECT
    loja,
    nro_nf,
    codigo_produto,
    conciliado_as400,
    conciliado_qlik,
    conciliado,
    nota_as400_exemplo,
    nota_qlik_exemplo,
    origens_qlik
FROM pleno_status
WHERE loja = 428
  AND nro_nf = 153
ORDER BY codigo_produto;
```

### 4. "Deu erro no AS400?"

```sql
SELECT
    loja,
    numero_nota,
    numero_nota_original,
    codigo_produto,
    erro_as400,
    codigo_transacao
FROM as400_erros
WHERE loja = 428
  AND (numero_nota_original = 153 OR numero_nota = 153)
ORDER BY codigo_produto;
```

### 5. "Em qual arquivo mandamos?"

```sql
SELECT DISTINCT
    loja,
    nro_nf,
    primeiro_arquivo_enviado,
    arquivos_enviados
FROM pleno_status
WHERE loja = 428
  AND nro_nf = 153;
```

### 6. "Quantas vezes esse item foi reenviado?"

```sql
SELECT
    loja,
    nro_nf,
    codigo_produto,
    qtd_vezes_enviado_as400,
    qtd_arquivos_enviados
FROM pleno_status
WHERE loja = 428
  AND nro_nf = 153
ORDER BY codigo_produto;
```

### 6.1 "Quais prefixos dessa nota ja foram usados?"

Essa verificacao deve ser feita sempre que houver duvida se a devolucao ja foi reenviada.

```sql
SELECT DISTINCT
    loja,
    nro_nf,
    primeiro_arquivo_enviado,
    qtd_vezes_enviado_as400
FROM pleno_status
WHERE loja = 488
  AND nro_nf IN (81, 990081, 980081, 970081, 960081)
ORDER BY nro_nf;
```

Observacao:

- dependendo da carga, o `pleno_status` pode ficar mais forte para a nota original
- por isso, em paralelo, tambem vale procurar diretamente nos arquivos CSV

Exemplo de busca em arquivo:

```bash
rg -n '^488;(81|990081|980081|970081|960081);' /Users/alexandrematheuscrose/Documents/Codex/2026-05-19/Devolucoes -g '*.csv'
```

### 7. "O que ainda falta mandar para o AS400?"

```sql
SELECT
    loja,
    nro_nf,
    data_nf,
    codigo_produto,
    qtd_devolvida,
    causa_pleno,
    status
FROM pleno_status
WHERE status = 'PENDENTE_ENVIO'
ORDER BY data_nf, loja, nro_nf, codigo_produto;
```

### 8. "O que ja foi enviado, mas ainda nao conciliou?"

```sql
SELECT
    loja,
    nro_nf,
    data_nf,
    codigo_produto,
    primeiro_arquivo_enviado,
    qtd_vezes_enviado_as400,
    status
FROM pleno_status
WHERE status = 'ENVIADO'
ORDER BY data_nf, loja, nro_nf, codigo_produto;
```

## Padrao de Resposta para Analises

Quando formos responder uma consulta manual, usar este formato:

```text
Nota/Ticket: XXXXXX
Comunicado com o AS400: SIM/NAO
Arquivo Comunicado: DEVOLUCAO_XXXXX.csv
Artigo XXXX Causa: Foto-X Pleno-X AS400-X Confirmado no AS400: SIM/NAO
```

Ajustes combinados:

- tickets maiores que `1500`: classificar como `MASTER`
- quando nao aparecer no AS400 e nao houver erro formal: usar `EM INVESTIGACAO DE ERRO`

## Como Decidir a Tratativa

### Reenviar

Quando:

- existe no Pleno
- nao apareceu no AS400
- nao apareceu no Qlik confirmado
- nao existe erro impeditivo conhecido
- e ja confirmamos se houve ou nao envios prefixados `99/98/97/96...`

### Nao reenviar ainda

Quando:

- ja foi reenviado varias vezes
- o caso tem cara de divergencia sistemica
- existe risco de duplicar numeracao ou poluir investigacao
- ja identificamos historico com `99/98/97/96...` sem conciliacao posterior

### Pedir regravacao da loja

Quando:

- a nota nao existe nas bases do Pleno
- a quantidade ou os itens nao batem com o documento de origem
- o problema esta na gravacao inicial da devolucao e nao no transporte para o AS400

## Observacoes Importantes dos Ultimos Ajustes

- A base do Qlik agora sobe todas as abas, nao apenas `Confirmados`.
- A conciliacao por Qlik so considera a aba `Confirmados`.
- O campo de causa do AS400 pode nao ser confiavel em todas as planilhas.
- Em comparacoes principais, a causa nao deve ser o unico criterio de decisao.
- A contagem de envios por item esta guardada em `qtd_vezes_enviado_as400`.

## Processo Recomendado para a Proxima Consulta

1. Identificar o tipo do arquivo novo.
2. Decidir em qual tabela ele entra.
3. Importar a fonte correspondente.
4. Reconstruir a base central.
5. Consultar `pleno_status`.
6. Se faltar algo, abrir detalhe em `pleno`, `envios_arquivo`, `as400`, `as400_qlik` e `as400_erros`.
7. So depois decidir entre reenviar, investigar ou pedir regravacao.

## Consulta Rapida de Sanidade

```sql
SELECT * FROM resumo_status;
```

```sql
SELECT origem_aba, COUNT(*)
FROM as400_qlik
GROUP BY origem_aba;
```

```sql
SELECT status, COUNT(*)
FROM pleno_status
GROUP BY status;
```

## Manutencao

Se algum arquivo novo chegar e a gente ainda nao souber onde encaixar:

- parar a importacao
- classificar a origem
- documentar aqui a decisao

Esse documento deve ser atualizado sempre que:

- entrar uma fonte nova
- mudar a regra de numeracao
- mudar a regra de data
- mudar a definicao de status
