import { config, requireZapiConfig } from "./config.mjs";
import { updateNotifySentByMe, updateReceiveWebhook } from "./zapi-client.mjs";

requireZapiConfig();

if (!config.publicBaseUrl) {
  throw new Error("Configure WHATSAPP_ZAPI_PUBLIC_BASE_URL com uma URL HTTPS publica.");
}

const baseUrl = config.publicBaseUrl.replace(/\/+$/, "");
const secret = config.webhookSecret
  ? `?secret=${encodeURIComponent(config.webhookSecret)}`
  : "";
const receiveUrl = `${baseUrl}/webhooks/zapi/receive${secret}`;

console.log(`Registrando webhook de recebimento: ${receiveUrl}`);
const webhookResult = await updateReceiveWebhook(receiveUrl);
console.log("Webhook:", webhookResult);

const notifyResult = await updateNotifySentByMe(false);
console.log("Notify sent by me:", notifyResult);
