# WhatsApp Web com Playwright

Este modulo monitora o WhatsApp Web por Playwright, grava mensagens em SQLite e
exibe uma pagina web local para classificacao operacional.

## Rodar o painel

Requisitos no Linux:

```bash
node -v
npm install
npx playwright install chromium
```

Use Node 22+; esta implementacao usa SQLite nativo do Node.

```bash
npm run whatsapp-web
```

Acesse:

```text
http://127.0.0.1:3108
```

No WhatsApp Web, abra/deixe na tela o grupo ou conversa que voce quer
acompanhar. No painel, `Grupo monitorado` e opcional: se ficar vazio, o watcher
captura a conversa aberta na tela; se preencher, ele so captura quando a conversa
aberta tiver esse nome.

## Primeiro login

No primeiro uso, o Playwright abre o Chromium em modo visivel para escanear o QR
Code do WhatsApp Web. A sessao fica salva em:

```text
outputs/whatsapp-web/chrome-profile
```

Em Linux sem interface grafica, rode com `xvfb-run`:

```bash
xvfb-run -a npm run whatsapp-web:watch
```

Depois que a sessao estiver autenticada, voce pode tentar rodar headless:

```bash
WHATSAPP_WEB_HEADLESS=true npm run whatsapp-web:watch
```

## Banco de dados

As mensagens sao gravadas em:

```text
outputs/whatsapp-web/messages.db
```

Tabelas principais:

- `contacts`: contatos/conversas vistos pelo monitor.
- `messages`: mensagens capturadas, categoria, prioridade, sentimento e status.
- `events`: logs do watcher e do servidor.

## Configuracao

Variaveis opcionais no `.env`:

```bash
WHATSAPP_WEB_HOST=127.0.0.1
WHATSAPP_WEB_PORT=3108
WHATSAPP_WEB_DB_FILE=outputs/whatsapp-web/messages.db
WHATSAPP_WEB_USER_DATA_DIR=outputs/whatsapp-web/chrome-profile
WHATSAPP_WEB_HEADLESS=false
WHATSAPP_WEB_AUTO_START_WATCHER=false
WHATSAPP_WEB_SCAN_INTERVAL_MS=15000
WHATSAPP_WEB_MAX_CHATS_PER_SCAN=25
WHATSAPP_WEB_MAX_MESSAGES_PER_CHAT=20
WHATSAPP_WEB_BROWSER_EXECUTABLE_PATH=

# Opcional: melhora classificacao usando IA. Sem chave, usa regras locais.
OPENAI_API_KEY=
OPENAI_MODEL=gpt-5-mini
```

## Escopo do monitoramento

O watcher so captura mensagens da conversa aberta no WhatsApp Web. Se
`Grupo monitorado` estiver preenchido, ele tambem confere se o nome da conversa
aberta contem esse texto antes de gravar.

## Observacoes importantes

O WhatsApp Web nao oferece API publica oficial para esse uso. O monitor depende
da tela/DOM do WhatsApp Web, entao seletores podem precisar de ajuste se o
WhatsApp mudar a interface. Para reduzir risco, o watcher apenas le e classifica
mensagens; envio automatico deve ser adicionado como uma etapa separada, com
confirmacao humana e limites.
