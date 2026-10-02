import { appendFile, mkdir } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { config } from "./config.mjs";

export async function logEvent(type, data) {
  const file = resolve(process.cwd(), config.logFile);
  await mkdir(dirname(file), { recursive: true });
  await appendFile(
    file,
    `${JSON.stringify({ at: new Date().toISOString(), type, data })}\n`,
    "utf8"
  );
}
