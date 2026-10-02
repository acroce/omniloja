#!/usr/bin/env node
import { spawn } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const statusFile = process.env.CRON_MONITOR_STATUS_FILE
  || path.join(ROOT, "outputs", "pleno_cron_monitor", "status.json");

const [jobId, separator, ...commandParts] = process.argv.slice(2);

if (!jobId || separator !== "--" || commandParts.length === 0) {
  console.error("Uso: pleno_cron_monitor_record.mjs <job_id> -- <comando>");
  process.exit(64);
}

function isoNow() {
  return new Date().toISOString();
}

async function readStatus() {
  try {
    return JSON.parse(await fs.readFile(statusFile, "utf8"));
  } catch {
    return { collector: "pleno_cron_monitor_record.mjs", runs: {} };
  }
}

async function writeStatus(status) {
  await fs.mkdir(path.dirname(statusFile), { recursive: true });
  const tempFile = `${statusFile}.tmp`;
  await fs.writeFile(tempFile, `${JSON.stringify(status, null, 2)}\n`, "utf8");
  await fs.rename(tempFile, statusFile);
}

async function updateRun(fields) {
  const status = await readStatus();
  status.collector = "pleno_cron_monitor_record.mjs";
  status.updatedAt = isoNow();
  status.runs = status.runs || {};
  status.runs[jobId] = {
    ...(status.runs[jobId] || {}),
    id: jobId,
    ...fields,
  };
  await writeStatus(status);
}

await updateRun({
  status: "running",
  lastStartedAt: isoNow(),
  lastFinishedAt: "",
  exitCode: "",
  command: commandParts.join(" "),
});

const child = spawn(commandParts.join(" "), {
  shell: true,
  stdio: "inherit",
});

child.on("error", async (error) => {
  await updateRun({
    status: "error",
    lastFinishedAt: isoNow(),
    exitCode: 127,
    logTail: error.message,
  });
  process.exit(127);
});

child.on("close", async (code, signal) => {
  const exitCode = code ?? 128;
  await updateRun({
    status: exitCode === 0 ? "ok" : "error",
    lastFinishedAt: isoNow(),
    exitCode,
    signal: signal || "",
  });
  process.exit(exitCode);
});
