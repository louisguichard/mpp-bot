const logsNode = document.querySelector("#logs");
const matchesNode = document.querySelector("#matches");
const recommendationsNode = document.querySelector("#recommendations");
const displayedNode = document.querySelector("#displayed");
const missingNode = document.querySelector("#missing");
const statusNode = document.querySelector("#status");
const auditNode = document.querySelector("#audit");

async function render() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const isMpp = tab?.url?.startsWith("https://mpp.football/");
  statusNode.textContent = isMpp ? "Actif sur MPP" : "Ouvre MPP";
  if (isMpp) {
    try {
      const result = await chrome.tabs.sendMessage(tab.id, { type: "mpp-status" });
      matchesNode.textContent = result.matches;
      recommendationsNode.textContent = result.recommendations;
      displayedNode.textContent = result.displayed;
      missingNode.textContent = result.missing.length;
      auditNode.className = `audit ${result.missing.length ? "warn" : "success"}`;
      auditNode.textContent = result.missing.length
        ? `Non trouvés : ${result.missing.map(item => `${item.home} – ${item.away}`).join(", ")}`
        : result.matches ? `Tous les ${result.matches} matchs MPP reçus ont été trouvés.` : "En attente des matchs MPP…";
    } catch {}
  }
  const { logs = [] } = await chrome.storage.local.get("logs");
  logsNode.innerHTML = logs.length ? logs.map(logHtml).join("") : '<div class="log">Aucun événement pour le moment.</div>';
}

function logHtml(log) {
  return `<div class="log ${log.level}">${escapeHtml(log.message)}<time>${new Date(log.at).toLocaleTimeString("fr-FR")}</time></div>`;
}

function escapeHtml(value) {
  const node = document.createElement("span");
  node.textContent = value;
  return node.innerHTML;
}

document.querySelector("#clear").addEventListener("click", async () => {
  await chrome.runtime.sendMessage({ type: "mpp-clear-logs" });
  render();
});

render();
