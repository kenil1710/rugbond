// docs/SUBMISSION.md: one-liner (<= 180), description (<= 1000), review verification (<= 500), plain ASCII,
// with the counts read from the repository's evidence files. Fails if a text is too long or not ASCII.
//   node tools/submission.mjs
import { readFileSync, writeFileSync, existsSync } from "node:fs";
const root = new URL("..", import.meta.url).pathname;
const j = (p) => JSON.parse(readFileSync(root + p, "utf8"));
const dep = j("deployments.json").contracts;
const feas = j("docs/feasibility.json"), rw = j("docs/real_world.json"), g = j("docs/feasibility_genvm.json");
const fc = existsSync(root + "docs/final_check.json") ? j("docs/final_check.json") : { passed: 0, total: 0, checks: [] };
const au = existsSync(root + "docs/audit.json") ? j("docs/audit.json") : { ok: 0, total: 14 };
const seeds = existsSync(root + "docs/seed-verify.json") ? j("docs/seed-verify.json").registries[0].rows : [];
const tests = fc.checks.find((c) => c.name === "tests")?.detail ?? "";
const off = tests.match(/offline contract suite (\d+)/)?.[1] ?? "?", kp = tests.match(/keeper suite (\d+)/)?.[1] ?? "?", dm = tests.match(/Direct Mode (\d+)/)?.[1] ?? "?";
const rugs = feas.cases.filter((c) => c.expect === "RUGGED"), held = feas.cases.filter((c) => c.expect === "HELD");
const ethR = rugs.filter((c) => c.chain === "ethereum").length, baseR = rugs.filter((c) => c.chain === "base").length;
const gOk = g.rows.filter((r) => r.identical).length;

const one = "RugBond: a token team bonds GEN behind a frozen liquidity promise; if the LP is pulled early, code on GenLayer pays the bond to the holders.";
const desc = `A team or launchpad posts GEN behind a frozen promise: these wallets keep at least this much of a Uniswap V2-style pool's LP until a set time. Validators read LP Transfer logs and balances from two log RPCs and two state RPCs that must agree. The first block below the floor is the rug: holders then claim bond x min(balance at start, at R-1) / claimable supply; tokens bought after the start or received from the team earn nothing; the rest goes to a victim fund after the window. A held promise returns the bond. Errors are PENDING, never a verdict. LaunchGate answers per bond or team, never favorably on stale data. Built on ${feas.cases.length} real cases (${rugs.length} rugs: ${ethR} Ethereum, ${baseR} Base; ${held.length} held), ${rw.rows.filter((r) => r.agree).length}/${rw.rows.length} confirmed by independent chain signals; canonical seeds are replays created after the events.`;
const rev = `Open https://rugbond.vercel.app/verify (on-chain code = build/ at one commit). Run sh test/run_offline.sh (${off} tests) and pytest tests/direct (${dm}). docs/DEMO.md: a real Base Sepolia rug, claims, refusals, payouts checked at recipients, registry balance 0. docs/SEEDS.md: ${seeds.length} replay bonds settled. node tools/final_check.mjs: ${fc.passed}/${fc.total}; docs/AUDIT.md: ${au.ok}/${au.total}.`;
const bad = [];
for (const [name, t, max] of [["one-liner", one, 180], ["description", desc, 1000], ["review verification", rev, 500]]) {
  if (t.length > max) bad.push(`${name} is ${t.length} > ${max}`);
  if (!/^[\x20-\x7e]*$/.test(t)) bad.push(`${name} is not plain ASCII`);
}
const L = ["# Submission", "", "## One-liner", "", one, "", `(${one.length} characters)`, "", "## Description", "", desc, "", `(${desc.length} characters)`, "",
  "## Review verification", "", rev, "", `(${rev.length} characters)`, "", "## Counts", "",
  `- real cases: ${feas.cases.length} (${rugs.length} rugs: ${ethR} Ethereum, ${baseR} Base; ${held.length} held), all verdicts as expected`,
  `- GenVM reads identical to this machine's: ${gOk}/${g.rows.length}, claim reads ${(g.claim_reads?.rows ?? []).filter((r) => r.identical).length}/${(g.claim_reads?.rows ?? []).length}`,
  `- real-world check: ${rw.rows.filter((r) => r.agree).length}/${rw.rows.length}`,
  `- tests: offline ${off}, keeper ${kp}, Direct Mode ${dm}, Playwright e2e on the live site`,
  `- canonical replay bonds: ${seeds.length}, settled ${seeds.filter((r) => r.settled_at).length}`,
  `- final check ${fc.passed}/${fc.total}, audit ${au.ok}/${au.total}`, "",
  "## Addresses (GenLayer Studio Dev, chain 61997)", "",
  ...Object.entries(dep).map(([k, v]) => `- ${k}: \`${v.address}\``), "", `All four deployed from commit \`${dep.RugBond.commit}\`.`, ""];
writeFileSync(root + "docs/SUBMISSION.md", L.join("\n"));
console.log(bad.length ? "PROBLEMS: " + bad.join("; ") : `ok: ${one.length} / ${desc.length} / ${rev.length}`);
process.exit(bad.length ? 1 : 0);
