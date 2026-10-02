# Robo Prevencao e Perdas

Automacao Playwright/Linux para tratar retificacoes de sobra e falta no Pleno sem OCR.

## Fluxo

1. Acessa `PREV_PERDAS_RETIFICACAO_URL` ou `https://172.22.20.101/retificacao-sobra-falta-dia`.
2. Faz login com `PLENO_USER` e `PLENO_PASSWORD`.
3. Abre o filtro avancado, define o periodo e marca:
   - `PENDENTE CRIACAO DE NF`
   - `AGUARDANDO EMISSAO DE NF`
4. Abre o link da nota fiscal de transferencia de saida.
5. Clica em `Verifica NF`, depois `Emitir NF-e`.
6. Aguarda mensagem de sucesso ou erro no Pleno e grava o resultado no acompanhamento.

## Execucao visivel

```sh
npm run prevencao-perdas
```

Variaveis uteis:

```sh
PREV_PERDAS_LIMIT=10
PREV_PERDAS_START_DATE=25/07/2026
PREV_PERDAS_END_DATE=24/08/2026
PREV_PERDAS_DRY_RUN=1
```

## Docker Linux

```sh
docker compose -f docker-compose.prevencao-perdas.yml up -d --build
```

Painel:

```text
http://localhost:8096/prevencao-perdas.html
```

O container instala cron e roda o agendamento configurado em `PREV_PERDAS_CRON` ou, por padrao, `0 9,15 * * *`.

## Arquivos gerados

- `outputs/prevencao_perdas/acompanhamento.sqlite`
- `outputs/prevencao_perdas/execucao.json`
- `outputs/prevencao_perdas/cron.log`
- `outputs/prevencao_perdas/erro_*.png`
