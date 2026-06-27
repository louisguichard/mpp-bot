if (typeof importScripts === "function") importScripts("neutral-score-model.js", "rarity-label-model.js");

const POLYMARKET_URL = "https://gamma-api.polymarket.com/events/keyset?active=true&closed=false&limit=100&series_id=11433";
const RARITY_BONUSES = [20, 30, 50, 70, 100];
const CROWD_ALPHA = 2;
const CROWD_GOAL_BIAS = .55;
const HISTORICAL_CROWD_WEIGHT = 1;
const EXTRA_TIME_SAMPLE_SIZE = 54;
const EXTRA_TIME_STILL_DRAW = 34 / EXTRA_TIME_SAMPLE_SIZE;
const EXTRA_TIME_DECIDED = 20 / EXTRA_TIME_SAMPLE_SIZE;
const EXTRA_TIME_DRAW_DELTAS = [
  { home: 0, away: 0, weight: 30 / 34 },
  { home: 1, away: 1, weight: 4 / 34 },
];
const EXTRA_TIME_WIN_DELTAS = [
  { winner: 1, loser: 0, weight: 14 / 20 },
  { winner: 2, loser: 0, weight: 2 / 20 },
  { winner: 2, loser: 1, weight: 4 / 20 },
];
const BUCKET_CENTERS = {
  "0-40": 30,
  "40-60": 50,
  "60-80": 70,
  "80-100": 90,
  "100-120": 110,
  "120-150": 135,
  "150-1000": 175,
};
const ALIASES = {
  "algeria": ["algeria", "algérie", "algerie"],
  "argentina": ["argentina", "argentine"],
  "australia": ["australia", "australie"],
  "austria": ["austria", "autriche"],
  "belgium": ["belgium", "belgique"],
  "bosnia and herzegovina": ["bosnia and herzegovina", "bosnia-herzegovina", "bosnie-herzégovine", "bosnie herzegovine"],
  "brazil": ["brazil", "brésil", "bresil"],
  "cabo verde": ["cabo verde", "cape verde", "cap-vert", "cap vert"],
  "canada": ["canada"],
  "colombia": ["colombia", "colombie"],
  "cote d ivoire": ["côte d'ivoire", "cote d ivoire", "ivory coast"],
  "croatia": ["croatia", "croatie"],
  "curacao": ["curaçao", "curacao"],
  "czechia": ["czechia", "czech republic", "tchequie", "tchéquie", "république tchèque", "republique tcheque"],
  "dr congo": ["dr congo", "rd congo", "république démocratique du congo", "republique democratique du congo"],
  "ecuador": ["ecuador", "équateur", "equateur"],
  "egypt": ["egypt", "égypte", "egypte"],
  "england": ["england", "angleterre"],
  "france": ["france"],
  "germany": ["germany", "allemagne"],
  "ghana": ["ghana"],
  "haiti": ["haiti", "haïti"],
  "iran": ["iran", "ir iran"],
  "iraq": ["iraq", "irak"],
  "japan": ["japan", "japon"],
  "jordan": ["jordan", "jordanie"],
  "senegal": ["senegal", "sénégal"],
  "mexico": ["mexico", "mexique"],
  "morocco": ["morocco", "maroc"],
  "netherlands": ["netherlands", "pays-bas", "pays bas"],
  "new zealand": ["new zealand", "nouvelle-zélande", "nouvelle zelande"],
  "norway": ["norway", "norvège", "norvege"],
  "panama": ["panama"],
  "paraguay": ["paraguay"],
  "portugal": ["portugal"],
  "qatar": ["qatar"],
  "saudi arabia": ["saudi arabia", "arabie saoudite"],
  "scotland": ["scotland", "écosse", "ecosse"],
  "south africa": ["south africa", "afrique du sud"],
  "korea republic": ["korea republic", "south korea", "coree du sud", "corée du sud"],
  "spain": ["spain", "espagne"],
  "sweden": ["sweden", "suède", "suede"],
  "switzerland": ["switzerland", "suisse"],
  "tunisia": ["tunisia", "tunisie"],
  "turkiye": ["türkiye", "turkiye", "turkey", "turquie"],
  "united states": ["united states", "usa", "etats unis", "états-unis"],
  "uruguay": ["uruguay"],
  "uzbekistan": ["uzbekistan", "ouzbékistan", "ouzbekistan"],
};

chrome.runtime.onInstalled.addListener(() => clearLogs());

let polymarketFetchPromise = null;
let recommendationPromise = null;

chrome.runtime.onMessage.addListener((message, _, sendResponse) => {
  if (message.type === "mpp-log") {
    appendLog(message).then(() => sendResponse({ ok: true }));
    return true;
  }
  if (message.type === "mpp-clear-logs") {
    clearLogs().then(() => sendResponse({ ok: true }));
    return true;
  }
  if (message.type === "polymarket-recommendations") {
    const fingerprint = matchFingerprint(message.matches);
    if (!recommendationPromise || recommendationPromise.fingerprint !== fingerprint) {
      const promise = buildRecommendations(message.matches).finally(() => {
        if (recommendationPromise?.promise === promise) recommendationPromise = null;
      });
      recommendationPromise = { fingerprint, promise };
    }
    recommendationPromise.promise
      .then((result) => sendResponse({ ok: true, ...result }))
      .catch((error) => {
        appendLog({ level: "error", message: error.message, at: new Date().toISOString() });
        sendResponse({ ok: false, error: error.message });
      });
    return true;
  }
});

async function buildRecommendations(matches) {
  const payload = await fetchPolymarket();
  const events = payload.events || payload;
  const recommendations = [];
  const missing = [];
  for (const match of matches) {
    const linked = findEvent(match, events);
    if (!linked) {
      await appendLog({ level: "warn", message: `Aucun marché Polymarket : ${match.home} – ${match.away}`, at: new Date().toISOString() });
      missing.push({ matchId: match.matchId, home: match.home, away: match.away, date: match.date });
      continue;
    }
    const probabilities = moneylineProbabilities(linked.event);
    const knockout120 = isKnockoutMatch(match);
    const scoreModel = buildScoreModel(probabilities, match.quotations, 8, match.bets, knockout120);
    const options = [
      { key: "home", label: match.home },
      { key: "draw", label: "Nul" },
      { key: "away", label: match.away },
    ].map((option) => {
      const score = scoreModel.bestByOutcome[option.key];
      const outcomeProbability = scoreModel.outcomeProbabilities[option.key];
      const baseEv = outcomeProbability * Number(match.quotations[option.key]);
      return {
        ...option,
        probability: outcomeProbability,
        marketProbability90: probabilities[option.key],
        points: Number(match.quotations[option.key]),
        baseEv,
        exactEv: score.exactEv,
        ev: baseEv + score.exactEv,
        highUpside: outcomeProbability >= .20 && Number(match.quotations[option.key]) >= 150,
        bestScore: score.label,
        scoreProbability: score.probability,
        estimatedCrowdShare: score.crowdShare,
        exactBonus: score.bonus,
        expectedBonus: score.expectedBonus,
        expectedRarityLabel: score.expectedRarityLabel,
        rarityLabel: score.rarityLabel,
        robustScore: score.robust,
      };
    });
    const best = Math.max(...options.map((option) => option.ev));
    const bestKey = options.find((option) => option.ev === best)?.key;
    const majorityKey = match.bets
      ? ["home", "draw", "away"].sort((left, right) => Number(match.bets[right]) - Number(match.bets[left]))[0]
      : null;
    options.forEach((option) => {
      option.isRecommended = best - option.ev < 1;
      option.isContrarian = option.key === bestKey && majorityKey && option.key !== majorityKey;
    });
    const scoreRecommendations = Object.fromEntries(["home", "draw", "away"].map((key) => [
      key,
      scoreModel.scores
        .filter((score) => score.outcome === key)
        .map((score) => ({
          ...score,
          outcomeProbability: scoreModel.outcomeProbabilities[key],
          points: Number(match.quotations[key]),
          baseEv: scoreModel.outcomeProbabilities[key] * Number(match.quotations[key]),
          ev: scoreModel.outcomeProbabilities[key] * Number(match.quotations[key]) + score.exactEv,
        }))
        .sort((a, b) => b.ev - a.ev)
        .slice(0, 10),
    ]));
    recommendations.push({
      matchId: match.matchId,
      home: match.home,
      away: match.away,
      confidence: linked.confidence,
      liquidity: Number(linked.event.liquidity || 0),
      updatedAt: linked.event.updatedAt,
      scoreModel: {
        source: scoreModel.crowdSource,
        homeXg: scoreModel.homeXg,
        awayXg: scoreModel.awayXg,
        crowdAlpha: CROWD_ALPHA,
        crowdGoalBias: CROWD_GOAL_BIAS,
        knockout120,
      },
      scoreRecommendations,
      options,
    });
  }
  await appendLog({
    level: missing.length ? "warn" : "success",
    message: `Audit Polymarket : ${recommendations.length}/${matches.length} matchs trouvés`,
    at: new Date().toISOString(),
  });
  return { recommendations, missing, total: matches.length };
}

function buildScoreModel(target, quotations = null, maxGoals = 8, bets = null, knockout120 = false) {
  const [homeXg, awayXg] = calibratePoisson(target, maxGoals);
  const scores = knockout120
    ? applyKnockoutExtraTime(scoreDistribution(homeXg, awayXg, maxGoals), target)
    : scoreDistribution(homeXg, awayXg, maxGoals);
  const bestLabels = {};
  for (const alpha of [1.5, CROWD_ALPHA, 2.5]) {
    const modeled = addRarityEstimate(scores, alpha, quotations, bets);
    for (const key of ["home", "draw", "away"]) {
      const best = modeled.filter((score) => score.outcome === key).sort((a, b) => b.exactEv - a.exactEv)[0];
      bestLabels[alpha] ||= {};
      bestLabels[alpha][key] = best.label;
    }
  }
  const modeled = addRarityEstimate(scores, CROWD_ALPHA, quotations, bets).map((score) => ({
    ...score,
    robust: [1.5, 2.5].every((alpha) => bestLabels[alpha][score.outcome] === score.label),
  }));
  const bestByOutcome = Object.fromEntries(["home", "draw", "away"].map((key) => [
    key,
    modeled.filter((score) => score.outcome === key).sort((a, b) => b.exactEv - a.exactEv)[0],
  ]));
  return {
    homeXg,
    awayXg,
    scores: modeled,
    bestByOutcome,
    outcomeProbabilities: scoreOutcomes(modeled),
    knockout120,
    crowdSource: quotations && bets && globalThis.MPP_RARITY_LABEL_MODEL
      ? "Bonus MPP supervisé"
      : quotations && globalThis.MPP_NEUTRAL_SCORE_MODEL
      ? "Historique MPP neutre lissé"
      : "Estimation comportementale",
  };
}

function applyKnockoutExtraTime(scores, target) {
  const deltas = extraTimeDeltas(target);
  const converted = new Map();
  for (const score of scores) {
    if (score.homeScore !== score.awayScore) {
      addConvertedScore(converted, score.homeScore, score.awayScore, score.probability);
      continue;
    }
    for (const delta of deltas) {
      addConvertedScore(
        converted,
        score.homeScore + delta.home,
        score.awayScore + delta.away,
        score.probability * delta.probability,
      );
    }
  }
  return [...converted.values()].sort((left, right) => (
    left.homeScore - right.homeScore || left.awayScore - right.awayScore
  ));
}

function addConvertedScore(scores, homeScore, awayScore, probability) {
  const label = `${homeScore}-${awayScore}`;
  const existing = scores.get(label);
  if (existing) {
    existing.probability += probability;
    return;
  }
  scores.set(label, {
    homeScore,
    awayScore,
    label,
    outcome: homeScore > awayScore ? "home" : homeScore < awayScore ? "away" : "draw",
    probability,
  });
}

function extraTimeDeltas(target) {
  const denominator = Number(target.home) + Number(target.away);
  const homeShare = denominator > 0 ? Number(target.home) / denominator : .5;
  const awayShare = 1 - homeShare;
  return [
    ...EXTRA_TIME_DRAW_DELTAS.map((delta) => ({
      home: delta.home,
      away: delta.away,
      probability: EXTRA_TIME_STILL_DRAW * delta.weight,
    })),
    ...EXTRA_TIME_WIN_DELTAS.flatMap((delta) => [
      {
        home: delta.winner,
        away: delta.loser,
        probability: EXTRA_TIME_DECIDED * homeShare * delta.weight,
      },
      {
        home: delta.loser,
        away: delta.winner,
        probability: EXTRA_TIME_DECIDED * awayShare * delta.weight,
      },
    ]),
  ];
}

function isKnockoutMatch(match) {
  return Number(match.gameWeekNumber || 0) >= 4;
}

function calibratePoisson(target, maxGoals) {
  let best = { home: 1.4, away: 1.1, loss: Infinity };
  for (const pass of [
    { step: .15, radius: null },
    { step: .03, radius: .24 },
    { step: .01, radius: .05 },
  ]) {
    const homeStart = pass.radius === null ? .15 : Math.max(.05, best.home - pass.radius);
    const homeEnd = pass.radius === null ? 4.5 : best.home + pass.radius;
    const awayStart = pass.radius === null ? .15 : Math.max(.05, best.away - pass.radius);
    const awayEnd = pass.radius === null ? 4.5 : best.away + pass.radius;
    for (let home = homeStart; home <= homeEnd + 1e-9; home += pass.step) {
      for (let away = awayStart; away <= awayEnd + 1e-9; away += pass.step) {
        const probabilities = scoreOutcomes(scoreDistribution(home, away, maxGoals));
        const loss = ["home", "draw", "away"].reduce((sum, key) => sum + (probabilities[key] - target[key]) ** 2, 0);
        if (loss < best.loss) best = { home, away, loss };
      }
    }
  }
  return [best.home, best.away];
}

function scoreDistribution(homeXg, awayXg, maxGoals) {
  const home = poissonSeries(homeXg, maxGoals);
  const away = poissonSeries(awayXg, maxGoals);
  const scores = [];
  let total = 0;
  for (let h = 0; h <= maxGoals; h += 1) {
    for (let a = 0; a <= maxGoals; a += 1) {
      const probability = home[h] * away[a];
      total += probability;
      scores.push({ homeScore: h, awayScore: a, label: `${h}-${a}`, outcome: h > a ? "home" : h < a ? "away" : "draw", probability });
    }
  }
  return scores.map((score) => ({ ...score, probability: score.probability / total }));
}

function poissonSeries(lambda, maxGoals) {
  const values = [Math.exp(-lambda)];
  for (let goals = 1; goals <= maxGoals; goals += 1) values.push(values[goals - 1] * lambda / goals);
  return values;
}

function scoreOutcomes(scores) {
  return scores.reduce((result, score) => {
    result[score.outcome] += score.probability;
    return result;
  }, { home: 0, draw: 0, away: 0 });
}

function addRarityEstimate(scores, alpha, quotations = null, bets = null) {
  const outcomeTotals = scoreOutcomes(scores);
  const conditional = scores.map((score) => ({
    ...score,
    conditionalProbability: score.probability / outcomeTotals[score.outcome],
  }));
  const denominators = conditional.reduce((result, score) => {
    result[score.outcome] += crowdWeight(score, alpha);
    return result;
  }, { home: 0, draw: 0, away: 0 });
  const historical = historicalCrowdDistributions(quotations);
  return conditional.map((score) => {
    const heuristicShare = crowdWeight(score, alpha) / denominators[score.outcome];
    const historicalShare = historical?.[score.outcome]?.[relativeScore(score)] ?? null;
    const crowdShare = historicalShare === null
      ? heuristicShare
      : HISTORICAL_CROWD_WEIGHT * historicalShare + (1 - HISTORICAL_CROWD_WEIGHT) * heuristicShare;
    const supervised = supervisedRarity(score, quotations, bets);
    const rarity = supervised
      ? rarityFromLevel(supervised.level)
      : rarityFromShare(crowdShare);
    const expectedBonus = supervised?.expectedBonus ?? rarity.bonus;
    return {
      ...score,
      crowdShare,
      bonus: rarity.bonus,
      expectedBonus,
      expectedRarityLabel: expectedRarityLabel(expectedBonus),
      rarityLabel: rarity.label,
      exactEv: score.probability * expectedBonus,
    };
  });
}

function supervisedRarity(score, quotations, bets) {
  const model = globalThis.MPP_RARITY_LABEL_MODEL;
  if (!model?.rows?.length || !quotations || !bets) return null;
  const issue = score.outcome;
  const quotation = Number(quotations[issue]);
  const betShare = Number(bets[issue]);
  if (!Number.isFinite(quotation) || !Number.isFinite(betShare)) return null;
  const parameters = model.parameters;
  const kind = issue === "draw" ? "draw" : "win";
  const winnerGoals = Math.max(score.homeScore, score.awayScore);
  const loserGoals = Math.min(score.homeScore, score.awayScore);
  const neighbors = model.rows
    .filter((row) => row.k === kind)
    .map((row) => {
      const left = parameters.score_representation === "total_margin"
        ? [row.w + row.l, row.w - row.l]
        : [row.w, row.l];
      const right = parameters.score_representation === "total_margin"
        ? [winnerGoals + loserGoals, winnerGoals - loserGoals]
        : [winnerGoals, loserGoals];
      const differences = left.map((value, index) => Math.abs(value - right[index]));
      const goalWeight = parameters.goal_weight ?? parameters.goal_distance_weight ?? 1;
      const quotationWeight = parameters.quotation_weight ?? parameters.quotation_distance_weight ?? 1;
      const betWeight = parameters.bet_weight ?? parameters.bet_share_distance_weight ?? 3;
      const weighted = [
        ...differences.map((value) => goalWeight * value),
        quotationWeight * Math.abs(row.q - quotation) / 50,
        betWeight * Math.abs(row.b - betShare),
      ];
      let distance = parameters.metric === "euclidean"
        ? Math.sqrt(weighted.reduce((sum, value) => sum + value ** 2, 0))
        : weighted.reduce((sum, value) => sum + value, 0);
      if (differences.some(Boolean)) {
        distance += parameters.identity_penalty ?? parameters.score_identity_penalty ?? 1;
      }
      return { distance, level: row.y, international: row.i };
    })
    .sort((left, right) => left.distance - right.distance)
    .slice(0, parameters.neighbors);
  const votes = neighbors.reduce((result, neighbor) => {
    const competitionWeight = neighbor.international ? (parameters.international_weight ?? 1) : 1;
    const power = parameters.distance_power ?? 1;
    const distanceWeight = power === 0
      ? 1
      : 1 / ((parameters.distance_floor ?? .15) + neighbor.distance) ** power;
    result[neighbor.level] = (result[neighbor.level] || 0)
      + competitionWeight * distanceWeight;
    return result;
  }, {});
  const ranked = Object.entries(votes).sort((left, right) => right[1] - left[1]);
  const level = Number(ranked[0]?.[0]) || null;
  const totalWeight = ranked.reduce((sum, [, weight]) => sum + weight, 0);
  if (!level || !totalWeight) return null;
  const expectedBonus = ranked.reduce(
    (sum, [candidateLevel, weight]) => sum + RARITY_BONUSES[Number(candidateLevel) - 1] * weight,
    0,
  ) / totalWeight;
  return { level, expectedBonus: Math.min(100, Math.max(20, expectedBonus)) };
}

function rarityFromLevel(level) {
  const labels = ["exact", "rare", "très rare", "méga rare", "ultra rare"];
  return { bonus: RARITY_BONUSES[level - 1], label: labels[level - 1] };
}

function expectedRarityLabel(bonus) {
  if (bonus <= 25) return "exact";
  if (bonus <= 35) return "rare";
  if (bonus < 45) return "rare / très rare";
  if (bonus <= 55) return "très rare";
  if (bonus < 65) return "très rare / méga rare";
  if (bonus <= 80) return "méga rare";
  if (bonus < 95) return "méga rare / ultra rare";
  return "ultra rare";
}

function historicalCrowdDistributions(quotations) {
  const model = globalThis.MPP_NEUTRAL_SCORE_MODEL?.distributions;
  if (!model || !quotations) return null;
  return {
    home: interpolatedDistribution(model, "win", Number(quotations.home)),
    draw: interpolatedDistribution(model, "draw", Number(quotations.draw)),
    away: interpolatedDistribution(model, "win", Number(quotations.away)),
  };
}

function interpolatedDistribution(model, type, quotation) {
  const candidates = Object.entries(model)
    .filter(([key]) => key.startsWith(`${type}:`))
    .map(([key, value]) => ({ center: BUCKET_CENTERS[key.split(":")[1]], scores: value.scores }))
    .filter((item) => Number.isFinite(item.center))
    .sort((a, b) => a.center - b.center);
  if (!candidates.length) return {};
  const upperIndex = candidates.findIndex((item) => item.center >= quotation);
  if (upperIndex <= 0) return candidates[0].scores;
  if (upperIndex < 0) return candidates[candidates.length - 1].scores;
  const lower = candidates[upperIndex - 1];
  const upper = candidates[upperIndex];
  const upperWeight = (quotation - lower.center) / (upper.center - lower.center);
  const labels = new Set([...Object.keys(lower.scores), ...Object.keys(upper.scores)]);
  return Object.fromEntries([...labels].map((label) => [
    label,
    (lower.scores[label] || 0) * (1 - upperWeight) + (upper.scores[label] || 0) * upperWeight,
  ]));
}

function relativeScore(score) {
  return score.outcome === "away"
    ? `${score.awayScore}-${score.homeScore}`
    : score.label;
}

function crowdWeight(score, alpha) {
  const totalGoals = score.homeScore + score.awayScore;
  const margin = Math.abs(score.homeScore - score.awayScore);
  const simpleResultBoost = margin === 1 ? 1.25 : 1;
  return score.conditionalProbability ** alpha
    * Math.exp(-CROWD_GOAL_BIAS * totalGoals)
    * simpleResultBoost;
}

function rarityFromShare(share) {
  if (share < .005) return { bonus: RARITY_BONUSES[4], label: "ultra rare" };
  if (share < .05) return { bonus: RARITY_BONUSES[3], label: "méga rare" };
  if (share < .20) return { bonus: RARITY_BONUSES[2], label: "très rare" };
  if (share <= .30) return { bonus: RARITY_BONUSES[1], label: "rare" };
  return { bonus: RARITY_BONUSES[0], label: "exact" };
}

async function fetchPolymarket() {
  const { polymarketCache } = await storageGet("polymarketCache");
  if (
    polymarketCache
    && Date.now() - polymarketCache.savedAt < 60_000
    && (polymarketCache.events || []).length >= 72
  ) return { events: polymarketCache.events };
  if (polymarketFetchPromise) return polymarketFetchPromise;
  polymarketFetchPromise = fetchPolymarketFresh().finally(() => {
    polymarketFetchPromise = null;
  });
  return polymarketFetchPromise;
}

async function fetchPolymarketFresh() {
  const events = [];
  let cursor = "";
  for (let page = 0; page < 5; page += 1) {
    const url = cursor ? `${POLYMARKET_URL}&after_cursor=${encodeURIComponent(cursor)}` : POLYMARKET_URL;
    const response = await fetch(url);
    if (!response.ok) throw new Error(`Polymarket HTTP ${response.status}`);
    const payload = await response.json();
    events.push(...(payload.events || []).filter(hasCompleteMoneyline).map(compactEvent));
    cursor = payload.next_cursor || "";
    if (!cursor || (payload.events || []).length < 100) break;
  }
  const payload = { events };
  await storageRemove("polymarketCache");
  await storageSet({ polymarketCache: { savedAt: Date.now(), events } });
  await appendLog({ level: "success", message: `${events.length} matchs Polymarket chargés`, at: new Date().toISOString() });
  return payload;
}

function compactEvent(event) {
  return {
    title: event.title,
    slug: event.slug,
    endDate: event.endDate,
    liquidity: event.liquidity,
    updatedAt: event.updatedAt,
    markets: (event.markets || []).filter((market) => market.sportsMarketType === "moneyline").map((market) => ({
      sportsMarketType: market.sportsMarketType,
      groupItemTitle: market.groupItemTitle,
      gameStartTime: market.gameStartTime,
      bestBid: market.bestBid,
      bestAsk: market.bestAsk,
      outcomePrices: market.outcomePrices,
    })),
  };
}

function findEvent(match, events) {
  const matchDate = new Date(match.date).getTime();
  const candidates = events.map((event) => {
    if (!hasCompleteMoneyline(event)) return null;
    const [home, away] = String(event.title || "").split(" vs. ").map(cleanTeamLabel);
    if (!home || !away) return null;
    const eventDate = new Date(event.markets?.find((market) => market.gameStartTime)?.gameStartTime || event.endDate).getTime();
    const minutes = Math.abs(matchDate - eventDate) / 60_000;
    const direct = (similarity(match.home, home) + similarity(match.away, away)) / 2;
    const reversed = (similarity(match.home, away) + similarity(match.away, home)) / 2;
    const teamScore = Math.max(direct, reversed);
    if (minutes > 480 || teamScore < .72) return null;
    return { event, confidence: .85 * teamScore + .15 * Math.max(0, 1 - minutes / 480) };
  }).filter(Boolean).sort((a, b) => b.confidence - a.confidence);
  if (!candidates.length) return null;
  if (candidates[1] && candidates[0].confidence - candidates[1].confidence < .08) return null;
  return candidates[0];
}

function cleanTeamLabel(value) {
  return String(value).replace(/\s+-\s+(Exact Score|Halftime Result).*$/i, "").trim();
}

function hasCompleteMoneyline(event) {
  return (event.markets || []).filter((market) => market.sportsMarketType === "moneyline").length >= 3;
}

function moneylineProbabilities(event) {
  const [home, away] = event.title.split(" vs. ");
  const values = {};
  for (const market of event.markets || []) {
    if (market.sportsMarketType !== "moneyline") continue;
    const label = market.groupItemTitle || "";
    const key = label === home ? "home" : label === away ? "away" : label.toLowerCase().startsWith("draw") ? "draw" : null;
    if (!key) continue;
    const bid = Number(market.bestBid);
    const ask = Number(market.bestAsk);
    const fallback = Number(JSON.parse(market.outcomePrices || "[]")[0]);
    values[key] = bid && ask ? (bid + ask) / 2 : fallback;
  }
  if (!["home", "draw", "away"].every((key) => values[key])) throw new Error(`Marché 1N2 incomplet : ${event.title}`);
  const total = values.home + values.draw + values.away;
  return Object.fromEntries(Object.entries(values).map(([key, value]) => [key, value / total]));
}

function similarity(left, right) {
  const a = canonical(left);
  const b = canonical(right);
  if (a === b) return 1;
  const aa = new Set(a.split(" "));
  const bb = new Set(b.split(" "));
  const intersection = [...aa].filter((token) => bb.has(token)).length;
  return intersection / new Set([...aa, ...bb]).size;
}

function canonical(value) {
  const normalized = normalize(value);
  for (const [key, variants] of Object.entries(ALIASES)) {
    if (variants.map(normalize).includes(normalized)) return key;
  }
  return normalized;
}

function normalize(value) {
  return String(value).toLowerCase().normalize("NFD").replace(/\p{Diacritic}/gu, "").replace(/[^a-z0-9]+/g, " ").trim();
}

async function appendLog(entry) {
  const { logs = [] } = await storageGet("logs");
  logs.unshift({ level: entry.level || "info", message: entry.message, at: entry.at || new Date().toISOString() });
  await storageSet({ logs: logs.slice(0, 60) });
}

async function clearLogs() {
  await storageSet({ logs: [] });
}

function matchFingerprint(matches) {
  return matches.map((match) => [
    match.matchId,
    match.gameWeekNumber,
    match.quotations.home,
    match.quotations.draw,
    match.quotations.away,
    match.bets?.home,
    match.bets?.draw,
    match.bets?.away,
  ].join(":")).sort().join("|");
}

async function storageGet(key) {
  try {
    return await chrome.storage.local.get(key);
  } catch {
    return {};
  }
}

async function storageSet(values) {
  try {
    await chrome.storage.local.set(values);
  } catch {
    // A cache or a diagnostic log must never prevent the recommendations.
  }
}

async function storageRemove(key) {
  try {
    await chrome.storage.local.remove(key);
  } catch {
    // Older oversized caches are harmless once reads and writes are guarded.
  }
}
