const providers = document.querySelector("#providers");
const details = document.querySelector("#details");
const notice = document.querySelector("#notice");
const timestamp = document.querySelector("#timestamp");
const refreshButton = document.querySelector("#refresh");
const names = { apiFootball: "API-Football", oddsApiIo: "odds-api.io", polymarket: "Polymarket" };

function age(value) {
  if (!value) return "non annoncée";
  const seconds = Math.max(0, (Date.now() - new Date(value).getTime()) / 1000);
  if (seconds < 90) return `${Math.round(seconds)} s`;
  if (seconds < 5400) return `${Math.round(seconds / 60)} min`;
  return `${(seconds / 3600).toFixed(1)} h`;
}

function money(value) {
  return value == null ? "–" : `${Math.round(Number(value)).toLocaleString("fr-FR")} $`;
}

function providerCard(snapshot, key) {
  const status = snapshot.error ? "erreur" : snapshot.found ? "match trouvé" : "indisponible";
  const metrics = key === "oddsApiIo" ? [
    [snapshot.bookmakers?.length ?? 0, "bookmakers"], [snapshot.market_count ?? 0, "marchés"],
    [snapshot.selection_count ?? 0, "sélections"], [age(snapshot.freshest_update), "fraîcheur"],
  ] : key === "polymarket" ? [
    [money(snapshot.event?.liquidity), "liquidité"], [money(snapshot.event?.volume24hr), "volume 24 h"],
    [snapshot.moneylines?.length ?? 0, "marchés 1N2"], [age(snapshot.event?.updatedAt), "fraîcheur"],
  ] : [
    [snapshot.found ? "oui" : "non", "match trouvé"], [Object.keys(snapshot.plan_errors || {}).length, "erreurs forfait"],
    [Object.keys(snapshot.quota || {}).length, "infos quota"], [`${snapshot.latency_ms ?? "–"} ms`, "latence"],
  ];
  return `<article class="provider">
    <div class="provider-head"><h3>${names[key]}</h3><span class="pill ${snapshot.found ? "found" : ""}">${status}</span></div>
    ${snapshot.error ? `<p class="notice">${escapeHtml(snapshot.error)}</p>` : ""}
    ${snapshot.plan_errors ? `<p class="notice">${escapeHtml(Object.values(snapshot.plan_errors).join(" "))}</p>` : ""}
    <div class="metrics">${metrics.map(([value, label]) => `<div class="metric"><strong>${value}</strong><span>${label}</span></div>`).join("")}</div>
  </article>`;
}

function probabilityRows(probabilities) {
  if (!probabilities) return "";
  return `<div class="outcomes">${[["home", "France"], ["draw", "Nul"], ["away", "Sénégal"]].map(([key, label]) =>
    `<div><span>${label}</span><strong>${(probabilities[key] * 100).toFixed(1)}%</strong><small>cote théorique ${(1 / probabilities[key]).toFixed(2)}</small></div>`
  ).join("")}</div>`;
}

function moneylineRows(rows = []) {
  return rows.map(row => `<article class="market-row"><strong>${row.bookmaker}</strong><span>${row.name}</span><code>${escapeHtml(JSON.stringify(row.odds))}</code><small>${age(row.updatedAt)}</small></article>`).join("");
}

function scoreRows(rows = []) {
  const scores = rows.flatMap(row => row.odds.map(item => ({ ...item, bookmaker: row.bookmaker })));
  return scores.sort((a, b) => Number(a.odds) - Number(b.odds)).slice(0, 20)
    .map(score => `<span class="score"><strong>${score.label}</strong>${score.odds} <small>${score.bookmaker}</small></span>`).join("");
}

function detailCard(snapshot, key) {
  const main = key === "polymarket" ? `
      ${probabilityRows(snapshot.probabilities)}
      <div class="market-list">${(snapshot.moneylines || []).map(row => `<article class="market-row"><strong>${row.groupItemTitle}</strong><span>bid ${row.bestBid} · ask ${row.bestAsk} · spread ${row.spread}</span><span>${money(row.liquidity)} liquides · ${money(row.volume)} échangés</span><small>${age(row.updatedAt)}</small></article>`).join("")}</div>`
    : key === "oddsApiIo" ? `
      <p><strong>Liens :</strong> ${Object.entries(snapshot.urls || {}).map(([book, url]) => `<a href="${url}" target="_blank">${book}</a>`).join(" · ") || "aucun"}</p>
      <h4>1N2 reçu</h4><div class="market-list">${moneylineRows(snapshot.moneyline)}</div>
      <h4>20 scores exacts les plus probables</h4><div class="scores">${scoreRows(snapshot.correct_score)}</div>
      <h4>${snapshot.market_names?.length || 0} marchés disponibles</h4><p class="market-names">${(snapshot.market_names || []).join(" · ")}</p>`
    : `<p class="notice">${escapeHtml(Object.values(snapshot.plan_errors || {}).join(" ") || snapshot.error || "Aucune donnée reçue.")}</p>`;
  return `<article class="detail-card">
    <div class="provider-head"><h3>${names[key]}</h3><span class="pill">${snapshot.latency_ms ?? "–"} ms</span></div>
    ${main}
    <details><summary>Voir la réponse brute complète</summary><pre>${escapeHtml(JSON.stringify(snapshot.raw || snapshot, null, 2))}</pre></details>
  </article>`;
}

function escapeHtml(value) {
  const node = document.createElement("span");
  node.textContent = value;
  return node.innerHTML;
}

async function load() {
  refreshButton.disabled = true;
  notice.textContent = "Appels réels en cours…";
  try {
    const response = await fetch("/api/match-detail?home=France&away=Senegal");
    const data = await response.json();
    const snapshots = [["apiFootball", data.apiFootball], ["oddsApiIo", data.oddsApiIo], ["polymarket", data.polymarket]];
    providers.innerHTML = snapshots.map(([key, value]) => providerCard(value, key)).join("");
    details.innerHTML = snapshots.map(([key, value]) => detailCard(value, key)).join("");
    notice.textContent = "Toutes les valeurs ci-dessous viennent d'appels réels effectués au rafraîchissement.";
    timestamp.textContent = `Mesuré le ${new Date().toLocaleString("fr-FR")}`;
  } catch (error) {
    notice.textContent = `Impossible de charger la comparaison : ${error.message}`;
  } finally {
    refreshButton.disabled = false;
  }
}

refreshButton.addEventListener("click", load);
load();
