# Integracao WhatsApp via Z-API

Este modulo recebe mensagens da Z-API por webhook e pode responder automaticamente.

## Arquivos

- `src/whatsapp-zapi/server.mjs`: servidor HTTP com webhook `/webhooks/zapi/receive`.
- `src/whatsapp-zapi/register-webhook.mjs`: registra a URL publica HTTPS na Z-API.
- `src/whatsapp-zapi/zapi-client.mjs`: cliente para enviar mensagens e configurar webhooks.
- `outputs/whatsapp-zapi-events.jsonl`: log local de eventos e respostas.

## Configuracao

No `.env`, preencha:

```bash
ZAPI_INSTANCE_ID=sua_instancia
ZAPI_TOKEN=token_da_instancia
ZAPI_CLIENT_TOKEN=client_token_da_conta
WHATSAPP_ZAPI_PUBLIC_BASE_URL=https://sua-url-publica
WHATSAPP_ZAPI_WEBHOOK_SECRET=um-segredo-grande

# Comece assim para testar sem enviar resposta real.
WHATSAPP_AUTO_REPLY=false
WHATSAPP_DRY_RUN=true

# Opcional, para resposta com IA.
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-5-mini
WHATSAPP_SYSTEM_PROMPT=Voce atende clientes pelo WhatsApp...
```

## Rodar localmente

```bash
npm run whatsapp-zapi
```

Teste a saude:

```bash
curl http://127.0.0.1:3097/health
```

Para a Z-API chamar sua maquina local, exponha o servidor com uma URL HTTPS
publica, por exemplo Cloudflare Tunnel, ngrok ou deploy em VPS. A Z-API nao
aceita webhook HTTP.

## Registrar webhook na Z-API

Depois de configurar `WHATSAPP_ZAPI_PUBLIC_BASE_URL`:

```bash
npm run whatsapp-zapi:register
```

Isso configura o webhook de recebimento em:

```text
https://sua-url-publica/webhooks/zapi/receive?secret=...
```

## Ligar resposta automatica

Depois de validar os logs:

```bash
WHATSAPP_AUTO_REPLY=true
WHATSAPP_DRY_RUN=false
```

Por padrao, grupos, newsletters, broadcasts, notificacoes e mensagens enviadas
pelo proprio numero sao ignoradas.
