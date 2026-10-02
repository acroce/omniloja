import { config } from "./config.mjs";

const HANDOFF_WORDS = [
  "humano",
  "atendente",
  "reclamacao",
  "reclamação",
  "cancelar",
  "urgente",
  "processo",
  "advogado",
  "juridico",
  "jurídico",
];

export function extractTextMessage(event) {
  if (event?.text?.message) return String(event.text.message).trim();
  if (event?.image?.caption) return String(event.image.caption).trim();
  if (event?.audio) return "[audio recebido]";
  if (event?.document) return "[documento recebido]";
  if (event?.video) return "[video recebido]";
  return "";
}

function needsHuman(text) {
  const normalized = text.toLowerCase();
  return HANDOFF_WORDS.some((word) => normalized.includes(word));
}

function fallbackReply(text) {
  if (!text) {
    return "Recebi sua mensagem. Pode me mandar em texto o que voce precisa para eu te ajudar melhor?";
  }

  if (needsHuman(text)) {
    return "Entendi. Vou encaminhar sua mensagem para uma pessoa da equipe te ajudar com mais cuidado.";
  }

  return `Oi! Recebi sua mensagem: "${text}". Ja vou verificar e te retorno por aqui.`;
}

export async function buildReply({ text, contactName, phone }) {
  if (!config.openaiApiKey) return fallbackReply(text);

  const response = await fetch("https://api.openai.com/v1/responses", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${config.openaiApiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      model: config.openaiModel,
      instructions: config.systemPrompt,
      input: [
        {
          role: "user",
          content: [
            {
              type: "input_text",
              text: [
                `Nome do contato: ${contactName || "nao informado"}`,
                `Telefone: ${phone}`,
                `Mensagem recebida: ${text || "(sem texto)"}`,
              ].join("\n"),
            },
          ],
        },
      ],
    }),
  });

  const payload = await response.json();
  if (!response.ok) {
    throw new Error(`OpenAI HTTP ${response.status}: ${JSON.stringify(payload)}`);
  }

  return String(payload.output_text || "").trim() || fallbackReply(text);
}
