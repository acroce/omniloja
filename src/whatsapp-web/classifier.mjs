import { config } from "./config.mjs";
import { classificationOptions, listCategories } from "./db.mjs";

export function classifyByRules(text) {
  const normalized = String(text || "").toLowerCase();
  for (const rule of listCategories({ activeOnly: true })) {
    const words = String(rule.keywords || "")
      .split(",")
      .map((word) => word.trim().toLowerCase())
      .filter(Boolean);
    if (words.some((word) => normalized.includes(word))) {
      return {
        category: rule.name,
        priority: rule.priority,
        sentiment: rule.sentiment,
        confidence: 0.72,
      };
    }
  }
  return { category: "outro", priority: "normal", sentiment: "Checking", confidence: 0.45 };
}

export async function classifyMessage(text) {
  const fallback = classifyByRules(text);
  if (!config.openaiApiKey || !text || text.length < 4) return fallback;
  const categoryNames = [...new Set([...listCategories({ activeOnly: true }).map((item) => item.name), "outro"])];

  const response = await fetch("https://api.openai.com/v1/responses", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${config.openaiApiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      model: config.openaiModel,
      instructions: `Classifique mensagens de WhatsApp para uma fila operacional. Responda somente JSON valido com category, priority, sentiment e confidence. category deve ser um de: ${categoryNames.join(", ")}. priority: alta, normal, baixa. sentiment deve ser um de: ${classificationOptions.join(", ")}. confidence entre 0 e 1.`,
      input: `Mensagem: ${text}`,
      text: {
        format: {
          type: "json_schema",
          name: "whatsapp_message_classification",
          schema: {
            type: "object",
            additionalProperties: false,
            required: ["category", "priority", "sentiment", "confidence"],
            properties: {
              category: { type: "string", enum: categoryNames },
              priority: { type: "string", enum: ["alta", "normal", "baixa"] },
              sentiment: { type: "string", enum: classificationOptions },
              confidence: { type: "number", minimum: 0, maximum: 1 },
            },
          },
        },
      },
    }),
  });

  const payload = await response.json();
  if (!response.ok) return fallback;
  try {
    return { ...fallback, ...JSON.parse(payload.output_text) };
  } catch {
    return fallback;
  }
}
