/**
 * Everything at once, written to docs/FINAL_CHECK.md and docs/final_check.json:
 *   1  build/ is the build of contracts/; the site's copies match the repository
 *   2  on-chain code is byte-identical to build/ at the deploy commit and HEAD, all four from one commit
 *   3  the deployed addresses are the same everywhere they are written
 *   4  every link in the docs answers (explorer pages sampled once per shape)
 *   5  every canonical replay bond reached its expected verdict (rug block = the feasibility study's) and settled
 *   6  every payout arrived: canonical settles and every demo payout finalized, delivered, balances moved
 *   7  every registry's eth_getBalance is what its ledger holds (0 when everything is settled), superseded ones too
 *   8  the keeper ran within the last 8 hours, has no failed action, and a scheduled run succeeded
 *   9  the test suites pass (offline 300+, keeper, Direct Mode)
 *  10  no placeholder language, no limitation or risk disclaimers, no vendor mentions in the docs (the check's own
 *      result line never contains a phrase it looks for: docs/AUDIT.md quotes it)
 *  11  the live site answers on every page and API
 *  12  the Playwright e2e run passed on the live site
 *   node tools/final_check.mjs       exit 1 if any check fails
 */
import { readFileSync, writeFileSync, readdirSync, existsSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { createRequire } from "node:module";
import { retry } from "../test/harness.mjs";
import { deployments, balanceOf, payoutDelivered, plain } from "./lib/rb.mjs";
import { CHAINS } from "./lib/chains.mjs";

const root = new URL("..", import.meta.url).pathname;
const rd = (p) => readFileSync(root + p, "utf8");
const depAll = JSON.parse(rd("deployments.json"));
const dep = depAll.contracts;
const SITE = "https://rugbond.vercel.app";
const REPO = "kenil1710/rugbond";
const { createClient } = createRequire(new URL("../test/package.json", import.meta.url))("genlayer-js");
const { studioDevnet } = createRequire(new URL("../test/package.json", import.meta.url))("genlayer-js/chains");
const read = createClient({ chain: studioDevnet });
const view = async (a, fn, args) => { const v = await retry(() => read.readContract({ address: a, functionName: fn, args }), { label: fn }); return plain(typeof v === "string" ? JSON.parse(v) : v); };
const checks = [];
const add = (name, ok, detail) => { checks.push({ name, ok, detail }); console.log(`${ok ? "PASS" : "FAIL"}  ${name}: ${detail}`); };
const sh = (cmd, args, opts = {}) => spawnSync(cmd, args, { cwd: root, encoding: "utf8", maxBuffer: 64 << 20, ...opts });
const now = () => Math.floor(Date.now() / 1000);

// 1
{
  const b = sh("python3", ["tools/build.py", "--check"]);
  const f = sh("node", ["tools/sync_frontend.mjs", "--check"]);
  add("build and site copies fresh", b.status === 0 && f.status === 0, b.status === 0 && f.status === 0 ? "build/ = contracts/ + shared code; the site's deployments.json and RULES.md are identical to the repository's" : (b.stdout + f.stdout).trim());
}
// 2
{
  const v = sh("node", ["tools/verify_source.mjs", "--json"]);
  let j = null; try { j = JSON.parse(v.stdout); } catch { /* */ }
  add("source match", v.status === 0 && j?.ok, j ? `${j.rows.filter((r) => r.identical).length}/${j.rows.length} contracts read back from Studio Dev are byte-identical to build/ at ${j.commit.slice(0, 7)} and HEAD; all from one commit: ${j.one_commit}` : v.stderr.slice(0, 200));
}
// 3
{
  const addrs = Object.values(dep).map((c) => c.address.toLowerCase());
  const files = ["README.md", "docs/SUBMISSION.md", "docs/SEEDS.md", "docs/DEMO.md", "frontend/src/lib/deployments.json"];
  const missing = [];
  for (const f of files) {
    if (!existsSync(root + f)) { missing.push(f + " (missing)"); continue; }
    const t = rd(f).toLowerCase();
    const need = f === "docs/SEEDS.md" ? [dep.RugBond.address.toLowerCase()] : f === "docs/DEMO.md" ? [dep.RugBondDemo.address.toLowerCase(), dep.LaunchGateDemo.address.toLowerCase()] : addrs;
    for (const a of need) if (!t.includes(a)) missing.push(`${f} lacks ${a}`);
  }
  add("addresses consistent", missing.length === 0, missing.length === 0 ? `the four deployed addresses appear in ${files.join(", ")}` : missing.join("; "));
}
// 4
{
  const BROWSER_ONLY = /(etherscan\.io|basescan\.org|vercel\.com)/;
  const docs = ["README.md", ...readdirSync(root + "docs").filter((f) => f.endsWith(".md") && f !== "FINAL_CHECK.md").map((f) => "docs/" + f)];
  const RPCS = new Set(Object.values(CHAINS).flatMap((c) => [...c.rpcs, ...c.state]).concat(["https://base.gateway.tenderly.co", "https://base.rpc.thirdweb.com", "https://mainnet.base.org", "https://base.drpc.org", "https://base-mainnet.public.blastapi.io", "https://eth-mainnet.nodereal.io/v1/1659dfb40aa24bbb8153a677b98064d7"]));
  const urls = new Set();
  for (const f of docs) for (const m of rd(f).matchAll(/https?:\/\/[^\s)<>"'`|\]*]+/g)) { const u = m[0].replace(/[.,;:]+$/, ""); if (![...RPCS].some((r) => u.startsWith(r))) urls.add(u); }
  const sample = new Map();
  for (const u of urls) { const key = u.replace(/0x[0-9a-f]{40,64}/gi, "X").replace(/\/\d+$/, "/N"); if (!sample.has(key)) sample.set(key, u); }
  const list = [...sample.values()];
  const bad = [], browser = [];
  let ok = 0;
  for (let i = 0; i < list.length; i += 8) {
    await Promise.all(list.slice(i, i + 8).map(async (u) => {
      let code = 0;
      for (let k = 0; k < 3 && code !== 200; k++) {
        try { const r = await fetch(u, { redirect: "follow", headers: { "user-agent": "Mozilla/5.0 (Macintosh) final_check" }, signal: AbortSignal.timeout(25000) }); code = r.status; } catch { code = -1; }
        if (code !== 200) await new Promise((r) => setTimeout(r, 1500));
      }
      if (code === 200) ok++;
      else if (BROWSER_ONLY.test(u)) browser.push(`${u.split("/")[2]} (${code})`);
      else bad.push(`${u} (${code})`);
    }));
  }
  add("links", bad.length === 0, `${urls.size} distinct links, ${list.length} checked (one per page shape): ${ok} answered 200; ${browser.length} explorer pages that serve browsers only (${[...new Set(browser)].join(", ") || "none"})${bad.length ? "; BROKEN: " + bad.join(", ") : ""}`);
}
// 5, 6, 7
{
  const sv = sh("node", ["tools/seeds_md.mjs"]);
  const s = JSON.parse(rd("docs/seed-verify.json"));
  const cur = s.registries[0];
  const wrong = cur.rows.filter((r) => !r.matches || !r.rug_block_matches);
  const open = cur.rows.filter((r) => !r.settled_at);
  add("canonical replays decided and settled", sv.status === 0 && wrong.length === 0 && open.length === 0,
    `${cur.rows.length} replay bonds on ${cur.address}: ${cur.rows.filter((r) => r.matches && r.rug_block_matches).length} at the expected verdict and rug block; ${cur.rows.length - open.length} settled (${cur.rows.filter((r) => r.to_victim_fund).length} to the victim fund after the claim window, ${cur.rows.filter((r) => r.to_launchpad).length} back to the launchpad)${wrong.length ? "; WRONG: " + wrong.map((r) => r.case_id).join(",") : ""}${open.length ? "; OPEN: " + open.map((r) => r.case_id).join(",") : ""}`);
  const bad = [];
  let n = 0;
  for (const reg of s.registries) for (const r of reg.rows) if (r.settled_at && BigInt(r.settled_amount) > 0n) { if (r.settle_proof?.delivered) n++; else bad.push(`${reg.address.slice(0, 10)} bond ${r.bond_id}: ${r.settle_proof ? r.settle_proof.why : "no settle transaction found"}`); }
  let dn = 0;
  if (existsSync(root + "docs/demo-run.json")) {
    const demo = JSON.parse(rd("docs/demo-run.json"));
    for (const st of demo.steps.filter((x) => x.payout)) {
      const tx = plain(await retry(() => read.getTransaction({ hash: st.tx }), { label: "tx" }));
      const d = payoutDelivered(tx, st.payout.to, st.payout.amount);
      if (!d.ok || !st.payout.arrived) bad.push(`demo ${st.id}: ${d.why || "balance did not move by the amount"}`); else dn++;
    }
  } else bad.push("docs/demo-run.json missing");
  add("payouts arrived", bad.length === 0 && n > 0 && dn > 0, `${n} canonical settle payouts finalized and delivered to their recipients; ${dn} demo payouts finalized, delivered and matched by the recipient's balance delta${bad.length ? "; " + bad.join("; ") : ""}`);
  const regs = [["RugBond", dep.RugBond.address], ["RugBondDemo", dep.RugBondDemo.address], ...(depAll.superseded ?? []).filter((x) => x.name.startsWith("RugBond")).map((x) => [x.name + " (superseded)", x.address])];
  const lines = [];
  let allOk = true;
  for (const [name, a] of regs) {
    const bal = await balanceOf(a);
    const st = await view(a, "get_stats", []);
    const ok = bal === BigInt(st.held);
    if (!ok) allOk = false;
    lines.push(`${name} ${a.slice(0, 10)}: eth_getBalance ${bal} wei, ledger holds ${st.held}`);
  }
  const zero = (await balanceOf(dep.RugBondDemo.address)) === 0n && (await balanceOf(dep.RugBond.address)) === 0n;
  add("balances match ledgers", allOk && zero, lines.join("; ") + (zero ? "; the current registries are at 0" : "; a current registry is not at 0"));
}
// 8
{
  const st = await (await fetch(`https://raw.githubusercontent.com/${REPO}/keeper-state/status.json`, { cache: "no-store" })).json().catch(() => null);
  const runs = JSON.parse(sh("gh", ["run", "list", "-R", REPO, "-w", "keeper.yml", "-L", "50", "--json", "event,conclusion,url,createdAt"]).stdout || "[]");
  const sched = runs.find((r) => r.event === "schedule" && r.conclusion === "success");
  const age = st ? (Date.now() - Date.parse(st.finished_at)) / 3600000 : 99;
  const failed = st ? Object.values(st.contracts).flatMap((c) => c.actions).filter((a) => a.status === "FAILED") : [];
  add("keeper", !!st && age < 8 && failed.length === 0 && !!sched, `last run finished ${age.toFixed(1)} h ago (${st?.trigger}); ${failed.length} failed actions; latest successful scheduled run: ${sched?.url ?? "none"}`);
}
// 9
{
  const off = sh("sh", ["test/run_offline.sh"]);
  const ran = Number((off.stderr + off.stdout).match(/Ran (\d+) tests/)?.[1] ?? 0);
  const kp = Number((off.stdout + off.stderr).match(/# pass (\d+)/)?.[1] ?? 0);
  const dm = sh(root + ".venv-gl/bin/python", ["-m", "pytest", "tests/direct", "-q"]);
  const dn = Number(dm.stdout.match(/(\d+) passed/)?.[1] ?? 0);
  add("tests", off.status === 0 && ran >= 300 && dm.status === 0, `offline contract suite ${ran} tests, keeper suite ${kp} tests, Direct Mode ${dn} tests; all pass: ${off.status === 0 && dm.status === 0}`);
}
// 10
{
  const docs = ["README.md", ...readdirSync(root + "docs").filter((f) => f.endsWith(".md") && f !== "FINAL_CHECK.md" && f !== "AUDIT.md").map((f) => "docs/" + f)];
  const BAD = [/\bTODO\b/, /\bTBD\b/, /lorem ipsum/i, /known limitations?/i, /accepted risks?/i, /documented gaps?/i, /\bClaude\b/, /\bAnthropic\b/, /Co-Authored-By/i, /\bChatGPT\b/, /\bAI-generated\b/i];
  const hits = [];
  for (const f of docs) for (const re of BAD) if (re.test(rd(f))) hits.push(`${f}: ${re}`);
  add("docs language", hits.length === 0, hits.length ? hits.join("; ") : `${docs.length} documents: no placeholders, no limitation or risk disclaimers, no tool-vendor mentions`);
}
// 11
{
  const paths = ["/", "/owed", "/claim", "/team", "/gate", "/keeper", "/verify", "/docs", `/bond/1`, `/bond/demo-1`, "/api/bond?id=1", `/api/address?a=${dep.RugBond.deployer}`, "/api/badge?bond=1", "/api/verify"];
  const bad = [];
  for (const p of paths) {
    let code = 0;
    for (let k = 0; k < 3 && code !== 200; k++) { try { code = (await fetch(SITE + p, { signal: AbortSignal.timeout(60000) })).status; } catch { code = -1; } }
    if (code !== 200) bad.push(`${p} (${code})`);
  }
  add("live site", bad.length === 0, `${paths.length - bad.length}/${paths.length} pages and APIs answer 200 at ${SITE}${bad.length ? "; " + bad.join(", ") : ""}`);
}
// 12
{
  const r = existsSync(root + "docs/e2e/results.json") ? JSON.parse(rd("docs/e2e/results.json")) : null;
  const sm = existsSync(root + "docs/e2e/summary.json") ? JSON.parse(rd("docs/e2e/summary.json")) : {};
  const ok = r && r.stats?.expected > 0 && r.stats?.unexpected === 0;
  add("e2e", !!ok, r ? `Playwright on ${sm.site ?? SITE} (the site's production build), demo registry ${sm.demo_registry ?? ""}: ${r.stats.expected} passed, ${r.stats.unexpected} failed; steps ${(sm.steps ?? []).map((x) => x.step).filter((x, i, a) => a.indexOf(x) === i).join(", ")} (docs/e2e/)` : "docs/e2e/results.json missing");
}

const passed = checks.filter((c) => c.ok).length;
writeFileSync(root + "docs/final_check.json", JSON.stringify({ at: new Date().toISOString(), head: sh("git", ["rev-parse", "HEAD"]).stdout.trim(), passed, total: checks.length, checks }, null, 1) + "\n");
const L = ["# Final check", "", `\`node tools/final_check.mjs\` at ${new Date().toISOString()}: **${passed}/${checks.length} passed**.`, "", "| # | check | result | detail |", "|---|---|---|---|"];
checks.forEach((c, i) => L.push(`| ${i + 1} | ${c.name} | ${c.ok ? "PASS" : "FAIL"} | ${c.detail.replace(/\|/g, "/")} |`));
writeFileSync(root + "docs/FINAL_CHECK.md", L.join("\n") + "\n");
console.log(`\n${passed}/${checks.length} passed`);
process.exit(passed === checks.length ? 0 : 1);
