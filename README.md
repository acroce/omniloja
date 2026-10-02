# Tabelas Pleno - conexao MySQL

Base simples para conectar no banco MySQL do Pleno e consultar dados da tabela `conex`.

## Como usar

1. Instale as dependencias:

```bash
npm install
```

2. Crie o arquivo `.env` a partir do exemplo:

```bash
cp .env.example .env
```

3. Preencha as credenciais do MySQL do Pleno no `.env`.

4. Teste a conexao:

```bash
npm run test-connection
```

5. Consulte os dados da tabela `conex`:

```bash
npm run conex
```

## Estrutura

- `src/db.js`: cria o pool de conexao com MySQL.
- `src/test-connection.js`: valida se a conexao esta funcionando.
- `src/query-conex.js`: busca dados da tabela configurada em `CONEX_TABLE`.

## WhatsApp via Z-API

Para subir o webhook local:

```bash
npm run whatsapp-zapi
```

Depois de expor uma URL HTTPS publica e preencher o `.env`, registre o webhook:

```bash
npm run whatsapp-zapi:register
```

Documentacao: [docs/whatsapp-zapi.md](/Users/alexandrematheuscrose/Documents/Codex/2026-05-19/tabelas-pleno-vamos-criar-uma-conex/docs/whatsapp-zapi.md)

## WhatsApp Web via Playwright

Para monitorar WhatsApp Web sem webhook publico:

```bash
npm run whatsapp-web
```

Acesse o painel local:

```text
http://127.0.0.1:3108
```

Documentacao: [docs/whatsapp-playwright-linux.md](/Users/alexandrematheuscrose/Documents/Codex/2026-05-19/tabelas-pleno-vamos-criar-uma-conex/docs/whatsapp-playwright-linux.md)

## Auditoria de estoque no Pleno

No servidor, gere o pacote diario usando apenas dados do Pleno:

```bash
scripts/run_pleno_stock_audit_server.sh --date 2026-07-06 --lojas 155,203
```

Para snapshots do estoque atual em horarios fixos:

```bash
scripts/run_pleno_stock_snapshot_server.sh --label 0600
scripts/run_pleno_stock_snapshot_server.sh --label 1030
```

Na rotina diaria de auditoria, o estoque inicial do dia deve bater com o estoque
final do dia anterior. Por isso, para acompanhamento normal, basta manter um
snapshot de fechamento no servidor; o snapshot da manha fica apenas para testes
ou conferencia extra.

Na maquina local, importe o pacote para SQLite:

```bash
python3 scripts/import_pleno_stock_audit_local.py outputs/pleno_stock_audit_packages/2026-07-06_lojas_155-203.tar.gz --replace-run
```

O pacote contem CSVs separados para estoque diario, vendas, movimentos, notas de entrada, pedidos, inventarios e conciliacao por SKU.

### Aplicacao web local da auditoria

Para abrir a interface local com importacao de `.tar.gz`, trilhas de auditoria
e exportacao:

```bash
npm run audit-web
```

Ou via Docker, no mesmo padrao dos demais projetos locais:

```bash
docker compose -f docker-compose.audit.yml up -d
```

Acesse:

```text
http://127.0.0.1:8094
```

Documentacao: [docs/pleno-stock-audit.md](/Users/alexandrematheuscrose/Documents/Codex/2026-05-19/tabelas-pleno-vamos-criar-uma-conex/docs/pleno-stock-audit.md)

## Analise de devolucao CD

Documentacao operacional central:

- [docs/devolucao-operacao.md](/Users/alexandrematheuscrose/Documents/Codex/2026-05-19/tabelas-pleno-vamos-criar-uma-conex/docs/devolucao-operacao.md)

Use o script abaixo para montar o resumo de um caso de devolucao por loja, artigos e periodo. Ele cruza Pleno, origem operacional da nota, exportacao posterior e retorno AS400.

```bash
PYTHONPATH=.python_packages python3 scripts/analyze_devolucao_case.py \
  --loja 522 \
  --artigos 2358,73557,73551,60838 \
  --start-date 2026-05-20 \
  --end-date 2026-05-20
```

Campos principais da saida:

- `nf_pleno`: nota gravada/autorizada no Pleno.
- `qtd_view` e `qtd_nf`: quantidade na view de devolucao e na nota fiscal.
- `origem`: movimento operacional que originou a devolucao, normalmente `est09`.
- `nf_exportada`: numero usado no envio posterior para AS400, quando controlado localmente.
- `as400_nf` e `as400_qtd`: retorno confirmado no AS400, quando importado.

## Tesouraria - Cofre Inteligente

Para gerar o CSV contabil das transferencias `CAIXA GERAL -> COFRE INTELIGENTE`:

```bash
npm run tesouraria:cofre -- --start-date 2026-04-01 --end-date 2026-04-30 --loja 1155
```

Antes de gerar o arquivo, confira a previa:

```bash
npm run tesouraria:cofre -- --start-date 2026-04-01 --end-date 2026-04-30 --loja 1155 --preview
```

A rotina le as credenciais MySQL do `.env`, valida as duas contas financeiras da
transferencia e grava o CSV em `outputs/tesouraria_cofre_inteligente/`, com um
manifesto `.json` ao lado.
