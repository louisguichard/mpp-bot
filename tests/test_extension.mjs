import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const memory = {};
globalThis.chrome = {
  runtime: {
    onInstalled: { addListener() {} },
    onMessage: { addListener() {} },
  },
  storage: {
    local: {
      async get(key) {
        if (typeof key === "string") return { [key]: memory[key] };
        return memory;
      },
      async set(values) { Object.assign(memory, values); },
      async remove(key) { delete memory[key]; },
    },
  },
};

const neutralModel = fs.readFileSync(new URL("../extension/neutral-score-model.js", import.meta.url), "utf8");
vm.runInThisContext(neutralModel);
const rarityLabelModel = fs.readFileSync(new URL("../extension/rarity-label-model.js", import.meta.url), "utf8");
vm.runInThisContext(rarityLabelModel);
const source = fs.readFileSync(new URL("../extension/background.js", import.meta.url), "utf8");
vm.runInThisContext(`${source}\nglobalThis.__mppExtension = { buildRecommendations, buildScoreModel, findEvent, moneylineProbabilities, fetchPolymarket };`);

const franceSenegalEvent = {
  title: "France vs. Senegal",
  slug: "fixture-france-senegal",
  endDate: "2026-06-16T19:00:00Z",
  updatedAt: "2026-06-16T18:30:00Z",
  markets: [
    { sportsMarketType: "moneyline", groupItemTitle: "France", gameStartTime: "2026-06-16T19:00:00Z", bestBid: .64, bestAsk: .66 },
    { sportsMarketType: "moneyline", groupItemTitle: "Draw", gameStartTime: "2026-06-16T19:00:00Z", bestBid: .20, bestAsk: .22 },
    { sportsMarketType: "moneyline", groupItemTitle: "Senegal", gameStartTime: "2026-06-16T19:00:00Z", bestBid: .13, bestAsk: .15 },
  ],
};
memory.polymarketCache = {
  savedAt: Date.now(),
  events: [
    franceSenegalEvent,
    ...Array.from({ length: 71 }, (_, index) => ({
      ...franceSenegalEvent,
      title: `Noise ${index} vs. Other ${index}`,
      slug: `noise-${index}`,
    })),
  ],
};

const result = await globalThis.__mppExtension.buildRecommendations([{
  matchId: "france-senegal",
  home: "France",
  away: "Sénégal",
  date: "2026-06-16T19:00:00Z",
  gameWeekNumber: 1,
  quotations: { home: 46, draw: 128, away: 153 },
  bets: { home: .88, draw: .09, away: .03 },
}]);

assert.equal(result.recommendations.length, 1);
assert.equal(result.missing.length, 0);
assert.equal(result.recommendations[0].matchId, "france-senegal");
assert.equal(result.recommendations[0].options.length, 3);
assert.ok(result.recommendations[0].options.every(option => Number.isFinite(option.ev)));
assert.ok(result.recommendations[0].options.every(option => option.ev > option.baseEv));
assert.ok(result.recommendations[0].options.every(option => option.bestScore));
assert.deepEqual(Object.keys(result.recommendations[0].scoreRecommendations), ["home", "draw", "away"]);
assert.ok(Object.values(result.recommendations[0].scoreRecommendations).every(scores => scores.length >= 9 && scores.length <= 10));
assert.equal(result.recommendations[0].options.filter(option => option.isRecommended).length, 1);
assert.equal(result.recommendations[0].options.find(option => option.isRecommended).key, "home");
assert.equal(result.recommendations[0].options.find(option => option.isRecommended).isContrarian, false);
const contrarianResult = await globalThis.__mppExtension.buildRecommendations([{
  matchId: "france-senegal-contrarian",
  home: "France",
  away: "Sénégal",
  date: "2026-06-16T19:00:00Z",
  gameWeekNumber: 1,
  quotations: { home: 46, draw: 128, away: 153 },
  bets: { home: .03, draw: .09, away: .88 },
}]);
assert.equal(contrarianResult.recommendations[0].options.find(option => option.isRecommended).key, "home");
assert.equal(contrarianResult.recommendations[0].options.find(option => option.isRecommended).isContrarian, true);

const scoreModel = globalThis.__mppExtension.buildScoreModel({ home: .5, draw: .3, away: .2 });
assert.ok(scoreModel.bestByOutcome.home.exactEv > 0);
assert.ok(scoreModel.bestByOutcome.draw.crowdShare <= 1);
assert.equal(scoreModel.scores.length, 81);
const knockoutScoreModel = globalThis.__mppExtension.buildScoreModel(
  { home: .5, draw: .25, away: .25 },
  null,
  8,
  null,
  true,
);
assert.equal(knockoutScoreModel.knockout120, true);
assert.ok(knockoutScoreModel.outcomeProbabilities.draw < scoreModel.outcomeProbabilities.draw);
assert.ok(Math.abs(
  Object.values(knockoutScoreModel.outcomeProbabilities).reduce((sum, value) => sum + value, 0) - 1
) < 1e-9);
const neutralHistorical = globalThis.__mppExtension.buildScoreModel(
  { home: .5, draw: .3, away: .2 },
  { home: 60, draw: 120, away: 150 },
);
assert.equal(neutralHistorical.crowdSource, "Historique MPP neutre lissé");
const supervisedHistorical = globalThis.__mppExtension.buildScoreModel(
  { home: .5, draw: .3, away: .2 },
  { home: 60, draw: 120, away: 150 },
  8,
  { home: .6, draw: .25, away: .15 },
);
assert.equal(supervisedHistorical.crowdSource, "Bonus MPP supervisé");
assert.ok(supervisedHistorical.scores.every(score => Number.isFinite(score.expectedBonus)));
assert.ok(supervisedHistorical.scores.every(score => score.expectedBonus >= 20 && score.expectedBonus <= 100));
assert.ok(supervisedHistorical.scores.every(score => score.expectedRarityLabel));
assert.ok(neutralHistorical.scores.find(score => score.label === "1-0").crowdShare > 0);
const symmetricNeutral = globalThis.__mppExtension.buildScoreModel(
  { home: .4, draw: .2, away: .4 },
  { home: 60, draw: 120, away: 60 },
);
assert.ok(Math.abs(
  symmetricNeutral.scores.find(score => score.label === "1-0").crowdShare
  - symmetricNeutral.scores.find(score => score.label === "0-1").crowdShare
) < 1e-9);
const belowBoundary = globalThis.__mppExtension.buildScoreModel(
  { home: .5, draw: .3, away: .2 },
  { home: 59.9, draw: 120, away: 150 },
);
const aboveBoundary = globalThis.__mppExtension.buildScoreModel(
  { home: .5, draw: .3, away: .2 },
  { home: 60.1, draw: 120, away: 150 },
);
assert.ok(Math.abs(
  belowBoundary.scores.find(score => score.label === "1-0").crowdShare
  - aboveBoundary.scores.find(score => score.label === "1-0").crowdShare
) < .01);
const knockoutResult = await globalThis.__mppExtension.buildRecommendations([{
  matchId: "france-senegal-ko",
  home: "France",
  away: "Sénégal",
  date: "2026-06-16T19:00:00Z",
  gameWeekNumber: 4,
  quotations: { home: 46, draw: 128, away: 153 },
  bets: { home: .88, draw: .09, away: .03 },
}]);
assert.equal(knockoutResult.recommendations[0].scoreModel.knockout120, true);
const knockoutDraw = knockoutResult.recommendations[0].options.find(option => option.key === "draw");
assert.ok(knockoutDraw.probability < knockoutDraw.marketProbability90);
const extremeUpset = globalThis.__mppExtension.buildScoreModel({ home: .97, draw: .02, away: .01 });
assert.ok(extremeUpset.scores.find(score => score.label === "0-1").crowdShare > .30);

const algeria = globalThis.__mppExtension.findEvent({
  home: "Algérie",
  away: "Autriche",
  date: "2026-06-27T02:00:00Z",
}, [{
  title: "Algeria vs. Austria",
  endDate: "2026-06-27T02:00:00Z",
  markets: [
    { sportsMarketType: "moneyline" },
    { sportsMarketType: "moneyline" },
    { sportsMarketType: "moneyline" },
  ],
}]);
assert.ok(algeria);

delete memory.polymarketCache;
const fullPayload = await globalThis.__mppExtension.fetchPolymarket();
assert.ok(fullPayload.events.length > 0);
assert.ok(fullPayload.events.every(event => event.markets.filter(market => market.sportsMarketType === "moneyline").length >= 3));
assert.ok(JSON.stringify(memory.polymarketCache).length < 200_000);
for (const event of fullPayload.events) {
  const probabilities = globalThis.__mppExtension.moneylineProbabilities(event);
  const model = globalThis.__mppExtension.buildScoreModel(probabilities);
  assert.ok(Object.values(model.bestByOutcome).every(score => Number.isFinite(score.exactEv)));
}
console.log("Extension: association Polymarket réelle et calcul des espérances OK");
