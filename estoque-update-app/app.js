const $ = (id) => document.getElementById(id);
const today = new Date().toISOString().slice(0, 10);
const monthStart = `${today.slice(0, 8)}01`;
$("startDate").value = monthStart;
$("endDate").value = today;

async function request(path, options) {
  const response = await fetch(path, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || "Nao foi possivel concluir a solicitacao.");
  return data;
}

function render(data) {
  const running = data.status === "running";
  const completed = data.status === "completed";
  const failed = data.status === "failed";
  $("runButton").disabled = running;
  $("runButton").textContent = running ? "Atualizacao em andamento" : "Executar atualizacao";
  $("statusDot").className = running ? "running" : failed ? "failed" : completed ? "completed" : "";
  $("status").textContent = running ? "Sincronizando XMLs e processando estoque" : failed ? "Falhou" : completed ? "Concluido" : "Pronto para executar";
  $("log").textContent = (data.log || ["Aguardando."]).join("\n");
  const period = data.period;
  $("period").textContent = period ? `Periodo: ${period.start.split("-").reverse().join("/")} ate ${period.end.split("-").reverse().join("/")}.` : "";
  $("progress").textContent = data.progress ? `Arquivo atual: ${data.progress.file} - ${(data.progress.bytes / 1024 / 1024).toFixed(1)} MB` : "";
  $("resultActions").hidden = !completed;
  if (completed) {
    $("result").textContent = `Arquivo final: ${data.result.name}`;
    $("download").href = `/api/download?path=${encodeURIComponent(data.result.file)}`;
    const deployment = data.deployment || {};
    const deploying = deployment.status === "sending";
    $("deploy").disabled = Boolean(data.result.deployed) || deploying;
    $("deploy").textContent = data.result.deployed ? "Enviado ao Pleno" : deploying ? "Enviando ao Pleno" : "Enviar ao Pleno";
    $("deployStatus").textContent = deployment.message || "";
    $("deployStatus").className = `deploy-status ${deployment.status || ""}`;
  } else if (failed) {
    $("result").textContent = data.error || "A rotina nao foi concluida.";
  } else if (running) {
    $("result").textContent = "A rotina sincroniza XMLs rejeitados, audita, gera o consolidado e atualiza o estoque. Esta tela acompanha todas as etapas.";
  }
}

async function refresh() {
  try {
    render(await request("/api/status"));
    const history = await request("/api/deployments");
    $("deployHistory").querySelector("tbody").innerHTML = history.map((item) => `<tr><td>${item.sent_at.replace("T", " ")}</td><td>${item.file}</td><td>${item.method === "manual" ? "Manual" : "Painel"}</td><td>${item.destination}</td></tr>`).join("") || "<tr><td colspan=\"4\">Nenhum envio registrado.</td></tr>";
  } catch (_) {}
}

$("runButton").addEventListener("click", async () => {
  try {
    const password = $("runPassword").value;
    if (!password) throw new Error("Informe a senha do Pleno para sincronizar os XMLs rejeitados.");
    await request("/api/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ startDate: $("startDate").value, endDate: $("endDate").value, password }) });
    $("runPassword").value = "";
    await refresh();
  } catch (error) { $("result").textContent = error.message; }
});

$("openFolder").addEventListener("click", async () => {
  try { await request("/api/open-folder", { method: "POST" }); } catch (error) { $("result").textContent = error.message; }
});

$("deploy").addEventListener("click", async () => {
  try {
    await request("/api/deploy", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ password: $("deployPassword").value }) });
    $("deployPassword").value = "";
    await refresh();
  } catch (error) { $("result").textContent = error.message; }
});

$("registerManual").addEventListener("click", async () => {
  try { await request("/api/register-manual-deploy", { method: "POST" }); await refresh(); } catch (error) { $("result").textContent = error.message; }
});

refresh();
setInterval(refresh, 1500);
