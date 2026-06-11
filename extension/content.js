const SOURCE = "mpp-esperance";
const state = {
  clubs: {},
  matches: new Map(),
  recommendations: new Map(),
  missing: [],
};

log("info", "Extension active sur MPP");

window.addEventListener("mpp-esperance-api", (event) => {
  const { url, data } = event.detail || {};
  if (!url || !data) return;
  const clubs = extractClubs(data);
  const matches = extractMatches(data);
  if (Object.keys(clubs).length) {
    Object.assign(state.clubs, clubs);
    log("success", `${Object.keys(clubs).length} équipes MPP détectées`);
  }
  if (matches.length) {
    matches.forEach((match) => state.matches.set(match.matchId, match));
    log("success", `${matches.length} matchs MPP reçus depuis ${shortUrl(url)}`);
  }
  if (matches.length || Object.keys(clubs).length) scheduleRefresh();
});

chrome.runtime.onMessage.addListener((message, _, sendResponse) => {
  if (message.type === "mpp-status") {
    sendResponse({
      matches: state.matches.size,
      recommendations: state.recommendations.size,
      clubs: Object.keys(state.clubs).length,
      missing: state.missing,
      displayed: document.querySelectorAll(".mpp-ev-panel").length,
    });
  }
});

const observer = new MutationObserver(() => scheduleInjection());
observer.observe(document.documentElement, { childList: true, subtree: true });

let refreshTimer;
let refreshPromise = null;
let lastRefreshFingerprint = "";

function scheduleRefresh() {
  clearTimeout(refreshTimer);
  refreshTimer = setTimeout(refresh, 200);
}

async function refresh() {
  const matches = [...state.matches.values()].map(toMatchReference).filter(Boolean);
  if (!matches.length) {
    log("warn", "Matchs reçus, mais noms d'équipes encore indisponibles");
    return;
  }
  const fingerprint = matches.map((match) => [
    match.matchId,
    match.quotations.home,
    match.quotations.draw,
    match.quotations.away,
    match.bets?.home,
    match.bets?.draw,
    match.bets?.away,
  ].join(":")).sort().join("|");
  if (refreshPromise) return refreshPromise;
  if (fingerprint === lastRefreshFingerprint && state.recommendations.size) {
    scheduleInjection();
    return;
  }
  log("info", `Recherche Polymarket pour ${matches.length} matchs`);
  refreshPromise = (async () => {
   try {
    const response = await chrome.runtime.sendMessage({ type: "polymarket-recommendations", matches });
    if (!response?.ok) throw new Error(response?.error || "Réponse Polymarket invalide");
    state.recommendations.clear();
    response.recommendations.forEach((item) => state.recommendations.set(item.matchId, item));
    state.missing = response.missing || [];
    lastRefreshFingerprint = fingerprint;
    log(
      response.recommendations.length ? "success" : "warn",
      `${response.recommendations.length}/${matches.length} matchs associés à Polymarket`
    );
    scheduleInjection();
  } catch (error) {
    log("error", `Polymarket indisponible : ${error.message}`);
  } finally {
    refreshPromise = null;
  }
  })();
  return refreshPromise;
}

function toMatchReference(match) {
  const home = teamName(match.home, state.clubs);
  const away = teamName(match.away, state.clubs);
  if (!home || !away || !match.date || !match.quotations) return null;
  return {
    matchId: match.matchId,
    home,
    away,
    date: match.date,
    quotations: match.quotations,
    bets: match.stats?.bets || null,
  };
}

let injectionTimer;
function scheduleInjection() {
  if (injectionTimer) return;
  injectionTimer = setTimeout(() => {
    injectionTimer = null;
    injectAll();
  }, 250);
}

function injectAll() {
  let changed = 0;
  for (const recommendation of state.recommendations.values()) {
    const container = findMatchContainer(recommendation.home, recommendation.away, recommendation.matchId);
    if (!container) continue;
    changed += renderRecommendation(container, recommendation);
  }
  if (changed) log("success", `${changed} espérances affichées sous les cotes MPP`);
}

function renderRecommendation(container, recommendation) {
  const selector = `.mpp-ev-panel[data-match-id="${recommendation.matchId}"]`;
  const existing = container.querySelector(selector);
  const signature = JSON.stringify({
    options: recommendation.options.map((option) => [
      option.ev.toFixed(3),
      option.probability.toFixed(4),
      option.bestScore,
      option.exactBonus,
      option.expectedBonus?.toFixed(1),
      option.isRecommended,
      option.isContrarian,
    ]),
    scores: Object.values(recommendation.scoreRecommendations || {}).flat().map((score) => [
      score.label,
      score.ev.toFixed(3),
      score.bonus,
      score.rarityLabel,
    ]),
  });
  if (existing?.dataset.signature === signature) return 0;
  const panel = existing || document.createElement("section");
  panel.className = "mpp-ev-panel";
  panel.dataset.matchId = recommendation.matchId;
  panel.dataset.signature = signature;
  panel.innerHTML = `
    <div class="mpp-ev-heading">
      <strong>Espérance</strong>
      <span>Polymarket</span>
    </div>
    <div class="mpp-ev-options">
      ${recommendation.options.map((option) => `
        <div class="mpp-ev-option${option.isRecommended ? " recommended" : ""}${option.isContrarian ? " contrarian" : ""}${option.ev >= 50 ? " exceptional" : ""}">
          <span class="mpp-ev-label">${escapeHtml(option.label)}</span>
          <span class="mpp-ev-probability">${(option.probability * 100).toFixed(1)}% · +${option.points}</span>
          ${option.bestScore ? `<span class="mpp-ev-score">${escapeHtml(option.bestScore)}</span>` : ""}
          <strong class="mpp-ev-number">${option.ev.toFixed(1)}</strong>
        </div>`).join("")}
    </div>
    ${renderScoreDetails(recommendation)}`;
  if (!existing) container.appendChild(panel);
  wireScoreDetails(panel);
  return 1;
}

function wireScoreDetails(panel) {
  if (panel.dataset.detailsWired) return;
  panel.dataset.detailsWired = "true";
  panel.addEventListener("click", (event) => {
    if (event.target.closest(".mpp-score-details")) return;
    const shouldOpen = !panel.classList.contains("details-open");
    document.querySelectorAll(".mpp-ev-panel.details-open").forEach((item) => item.classList.remove("details-open"));
    if (shouldOpen) panel.classList.add("details-open");
  });
}

function renderScoreDetails(recommendation) {
  const groups = recommendation.scoreRecommendations || {};
  const scores = Object.values(groups).flat();
  if (!scores.length) return "";
  const labels = Object.fromEntries(recommendation.options.map((option) => [option.key, option.label]));
  const best = Math.max(...scores.map((score) => score.ev));
  return `
    <div class="mpp-score-details">
      <div class="mpp-score-details-heading">
        <strong>Scores par issue</strong>
      </div>
      <div class="mpp-score-columns">
      ${["home", "draw", "away"].map((key) => `
        <div class="mpp-score-group">
          <b>${escapeHtml(labels[key] || key)}</b>
          ${(groups[key] || []).map((score, index) => `
            <div class="mpp-score-row${best - score.ev < 1 ? " recommended" : ""}${index === 0 ? " issue-best" : ""}">
              <strong>${escapeHtml(score.label)}</strong>
              <span class="mpp-rarity">${escapeHtml(score.expectedRarityLabel || score.rarityLabel)} · +${Math.round(score.expectedBonus || score.bonus)}</span>
              <span class="mpp-score-gain">${(score.probability * 100).toFixed(1)}% · +${score.points + score.bonus}</span>
              <b>EV ${score.ev.toFixed(1)}</b>
            </div>`).join("")}
        </div>`).join("")}
      </div>
    </div>`;
}

function findMatchContainer(home, away, matchId) {
  const existing = document.querySelector(`.mpp-ev-panel[data-match-id="${matchId}"]`);
  if (existing?.parentElement) return existing.parentElement;
  const homeKey = normalize(home);
  const awayKey = normalize(away);
  const candidates = [...document.querySelectorAll("div, article, section, li")]
    .filter((node) => {
      if (node.closest(".mpp-ev-panel")) return false;
      const text = normalize(node.innerText || "");
      return text.includes(homeKey) && text.includes(awayKey) && node.querySelectorAll("input").length >= 2 && text.length < 1600;
    })
    .sort((a, b) => (a.innerText || "").length - (b.innerText || "").length);
  return candidates[0] ? matchCardRoot(candidates[0], homeKey, awayKey) : null;
}

function matchCardRoot(candidate, homeKey, awayKey) {
  let root = candidate;
  let current = candidate.parentElement;
  const inputCount = candidate.querySelectorAll("input").length;
  while (current && current !== document.body) {
    const text = normalize(current.innerText || "");
    const currentInputs = current.querySelectorAll("input").length;
    const rootWidth = root.getBoundingClientRect().width;
    const currentWidth = current.getBoundingClientRect().width;
    if (
      !text.includes(homeKey)
      || !text.includes(awayKey)
      || currentInputs !== inputCount
      || text.length >= 1800
      || (rootWidth > 0 && currentWidth > rootWidth * 1.25)
    ) break;
    root = current;
    current = current.parentElement;
  }
  return root;
}

function extractMatches(data) {
  const found = [];
  walk(data, (value) => {
    if (!value || typeof value !== "object" || Array.isArray(value)) return;
    if (!value.matchId || !value.home || !value.away || !value.quotations) return;
    if (!["home", "draw", "away"].every((key) => Number(value.quotations[key]) > 0)) return;
    found.push(value);
  });
  return uniqueBy(found, (match) => match.matchId);
}

function extractClubs(data) {
  const clubs = {};
  walk(data, (value, key) => {
    if (!value || typeof value !== "object" || Array.isArray(value)) return;
    if (!value.name || !value.defaultAssets) return;
    const id = value.clubId || value.id || key;
    if (id) clubs[id] = value;
  });
  return clubs;
}

function walk(value, callback, key = "") {
  callback(value, key);
  if (!value || typeof value !== "object") return;
  for (const [childKey, child] of Object.entries(value)) walk(child, callback, childKey);
}

function teamName(side, clubs) {
  if (!side) return "";
  const club = clubs[side.clubId] || side;
  const names = club.name || {};
  return names["fr-FR"] || names["en-GB"] || names["en-US"] || club.shortName || side.name || "";
}

function uniqueBy(items, key) {
  return [...new Map(items.map((item) => [key(item), item])).values()];
}

function normalize(value) {
  return String(value).toLowerCase().normalize("NFD").replace(/\p{Diacritic}/gu, "").replace(/[^a-z0-9]+/g, " ").trim();
}

function shortUrl(url) {
  try { return new URL(url).pathname; } catch { return url; }
}

function age(value) {
  if (!value) return "inconnue";
  const seconds = Math.max(0, (Date.now() - new Date(value).getTime()) / 1000);
  if (seconds < 90) return `il y a ${Math.round(seconds)} s`;
  if (seconds < 5400) return `il y a ${Math.round(seconds / 60)} min`;
  return `il y a ${(seconds / 3600).toFixed(1)} h`;
}

function money(value) {
  return value ? `${Math.round(value).toLocaleString("fr-FR")} $` : "inconnue";
}

function escapeHtml(value) {
  const node = document.createElement("span");
  node.textContent = value;
  return node.innerHTML;
}

async function log(level, message) {
  try {
    await chrome.runtime.sendMessage({ type: "mpp-log", level, message, at: new Date().toISOString(), source: SOURCE });
  } catch {}
}
