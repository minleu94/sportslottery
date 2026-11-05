import assert from "node:assert/strict"
import { after, before, test } from "node:test"
import { execFileSync } from "node:child_process"
import { existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs"
import { dirname, join, resolve, sep } from "node:path"
import { fileURLToPath, pathToFileURL } from "node:url"

const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..")
const testOutputParent = join(frontendRoot, "node_modules", ".cache")
let compiledOutput
let provenance
let radarSnapshots

before(() => {
  mkdirSync(testOutputParent, { recursive: true })
  compiledOutput = mkdtempSync(join(testOutputParent, "ui-regression-"))
  const buildInfoFile = join(compiledOutput, "test.tsbuildinfo")
  execFileSync(process.execPath, [
    join(frontendRoot, "node_modules", "typescript", "bin", "tsc"),
    "--project", join(frontendRoot, "tsconfig.app.json"),
    "--noEmit", "false",
    "--rootDir", join(frontendRoot, "src"),
    "--outDir", compiledOutput,
    "--tsBuildInfoFile", buildInfoFile,
  ], { cwd: frontendRoot, stdio: "pipe" })
  writeFileSync(join(compiledOutput, "package.json"), '{"type":"module"}\n')

  const modulePath = (file) => {
    const nestedPath = join(compiledOutput, "src", "lib", file)
    return existsSync(nestedPath) ? nestedPath : join(compiledOutput, "lib", file)
  }
  provenance = import(pathToFileURL(modulePath("probabilityProvenance.js")).href)
  radarSnapshots = import(pathToFileURL(modulePath("radarSnapshot.js")).href)
})

after(() => {
  if (!compiledOutput || !existsSync(compiledOutput)) return
  const cacheRoot = realpathSync(testOutputParent)
  const outputPath = realpathSync(compiledOutput)
  assert.ok(outputPath.startsWith(`${cacheRoot}${sep}`), "test compilation output must stay inside frontend/node_modules/.cache")
  rmSync(outputPath, { recursive: true, force: true })
})

test("Sharp probability, label, and per-leg/parlay EV all use Sharp evidence", async () => {
  const { getLegEvInfo, getLegProbabilityInfo, getQualifiedMarketBenchmarkInfo, getParlayEvInfo, getParlayProbabilityInfo } = await provenance
  const sharpLeg = {
    taiwan_odds: 2,
    expected_value_pct: 9,
    signal_evidence: {
      probability_status: "MARKET_BASELINE_ONLY",
      market_benchmark_status: "AVAILABLE",
      market_source_qualification: "SHARP_QUALIFIED",
      sharp_fair_probability: 0.64,
      sharp_expected_value_pct: 28,
      market_benchmark_fair_probability: 0.52,
      market_benchmark_ev_pct: 4,
    },
  }

  assert.deepEqual(getLegProbabilityInfo(sharpLeg), {
    value: 0.64,
    source: "SHARP_MARKET",
    label: "合格 Sharp 市場估計",
    validationLabel: "市場基準；非模型驗證",
  })
  assert.equal(getQualifiedMarketBenchmarkInfo(sharpLeg.signal_evidence).value, 0.64)
  const sharpLegEv = getLegEvInfo(sharpLeg)
  assert.equal(sharpLegEv.label, "Sharp EV")
  assert.ok(Math.abs(sharpLegEv.value - 28) < 1e-9)

  const sharpParlay = {
    has_sharp_benchmark: true,
    sharp_joint_probability: 0.4,
    sharp_parlay_ev_pct: 999,
    joint_probability: 0.5,
    parlay_ev_pct: 0,
    total_odds_exact: 2,
    total_odds: 2,
  }
  assert.equal(getParlayProbabilityInfo(sharpParlay).value, 0.4)
  const sharpParlayEv = getParlayEvInfo(sharpParlay)
  assert.equal(sharpParlayEv.label, "Sharp 市場估計 EV")
  assert.equal(sharpParlayEv.credible, false)
  assert.ok(Math.abs(sharpParlayEv.value + 20) < 1e-9)
})

test("international benchmarks remain separate and missing Sharp probability is never relabeled", async () => {
  const { getLegEvInfo, getLegProbabilityInfo, getQualifiedMarketBenchmarkInfo } = await provenance
  const international = {
    taiwan_odds: 2,
    expected_value_pct: 11,
    signal_evidence: {
      probability_status: "MARKET_BASELINE_ONLY",
      market_benchmark_status: "AVAILABLE",
      market_source_qualification: "INTERNATIONAL_MARKET",
      sharp_fair_probability: 0.64,
      market_benchmark_fair_probability: 0.52,
    },
  }
  assert.equal(getLegProbabilityInfo(international).value, 0.52)
  assert.equal(getLegProbabilityInfo(international).source, "INTERNATIONAL_MARKET")
  const internationalEv = getLegEvInfo(international)
  assert.equal(internationalEv.label, "國際市場 EV")
  assert.ok(Math.abs(internationalEv.value - 4) < 1e-9)
  assert.equal(getQualifiedMarketBenchmarkInfo(international.signal_evidence).value, 0.52)

  const missingSharp = {
    taiwan_odds: 2,
    signal_evidence: {
      probability_status: "MARKET_BASELINE_ONLY",
      market_benchmark_status: "AVAILABLE",
      market_source_qualification: "SHARP_QUALIFIED",
      sharp_fair_probability: null,
      market_benchmark_fair_probability: 0.52,
    },
  }
  assert.notEqual(getLegProbabilityInfo(missingSharp).source, "SHARP_MARKET")
  assert.deepEqual(getQualifiedMarketBenchmarkInfo(missingSharp.signal_evidence), {
    value: null,
    source: "UNAVAILABLE",
    label: "無有效估計",
    validationLabel: "缺少 Sharp 專屬去水機率",
  })
})

test("shared radar loader refreshes one snapshot and notifies RadarView without duplicate requests", async () => {
  const { getCachedRadarSnapshot, loadRadarSnapshot, subscribeRadarSnapshot } = await radarSnapshots
  const calls = []
  const publishedSnapshots = []
  const unsubscribe = subscribeRadarSnapshot(() => publishedSnapshots.push(getCachedRadarSnapshot()))
  let resolveInitialRadar
  const api = {
    getRadar(forceRefresh) {
      calls.push(["radar", forceRefresh])
      if (calls.length === 1) {
        return new Promise((resolvePromise) => { resolveInitialRadar = resolvePromise })
      }
      return Promise.resolve({ radar: [{ name: "fresh" }] })
    },
    async getLegs(...args) {
      calls.push(["legs", ...args])
      return { legs: [{ event_id: "fresh-event" }] }
    },
  }

  const initialLoad = loadRadarSnapshot(api)
  const forcedRefresh = loadRadarSnapshot(api, true)
  assert.deepEqual(calls, [["radar", false]])
  resolveInitialRadar({ radar: [{ name: "initial" }] })
  await Promise.all([initialLoad, forcedRefresh])

  assert.deepEqual(calls, [
    ["radar", false],
    ["legs"],
    ["radar", true],
    ["legs"],
  ])
  assert.deepEqual(getCachedRadarSnapshot().leagues, [{ name: "fresh" }])
  assert.deepEqual(getCachedRadarSnapshot().legs, [{ event_id: "fresh-event" }])
  assert.equal(publishedSnapshots.length, 2)
  assert.deepEqual(publishedSnapshots.at(-1).leagues, [{ name: "fresh" }])

  await loadRadarSnapshot(api)
  assert.equal(calls.length, 4, "fresh snapshot reuse must not issue duplicate API requests")
  unsubscribe()

  const appSource = readFileSync(join(frontendRoot, "src", "App.tsx"), "utf8")
  const radarSource = readFileSync(join(frontendRoot, "src", "views", "RadarView.tsx"), "utf8")
  assert.match(appSource, /loadRadarSnapshot\(api, true\)/)
  assert.doesNotMatch(appSource, /api\.getRadar\(true\)|api\.getLegs\(undefined,\s*true\)/)
  assert.match(radarSource, /useSyncExternalStore\(subscribeRadarSnapshot, getCachedRadarSnapshot, getCachedRadarSnapshot\)/)
})

test("ticket controls explain they record an already placed bet locally", () => {
  const card = readFileSync(join(frontendRoot, "src", "components", "ParlayResultCard.tsx"), "utf8")
  const modal = readFileSync(join(frontendRoot, "src", "components", "BetModal.tsx"), "utf8")
  const wallet = readFileSync(join(frontendRoot, "src", "views", "WalletView.tsx"), "utf8")

  assert.match(card, /記錄已投注注單/)
  assert.match(modal, /於台灣運彩官方完成投注/)
  assert.match(modal, /不會向台灣運彩官方送出投注/)
  assert.match(modal, /注單已記錄/)
  assert.match(modal, /記錄注單失敗/)
  assert.match(modal, /重試記錄/)
  assert.doesNotMatch(modal, /下注成功|確認下注/)
  assert.match(wallet, /記錄已投注組合/)
})
