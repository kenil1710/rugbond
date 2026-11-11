/**
 * The keeper bot (GitHub Actions, hourly and 6-hourly; runnable by hand).
 * For both registries in deployments.json (canonical and demo): files the next
 * rug check for every active bond, settles every bond that is due, walks every
 * page of bonds and claims. Logic: tools/lib/keeper_core.mjs.
 *
 *   node tools/keeper.mjs --state=<dir> [--push] [--contracts=RugBond,RugBondDemo] [--max=25] [--wait=300] [--settle=900]
 *
 * State lives in <dir>/keeper-state-<Contract>.json: in CI <dir> is a worktree
 * of the `keeper-state` branch and every checkpoint is committed there (and
 * pushed with --push), so a run that dies resumes from its stored transaction
 * hashes and page offsets. <dir>/status.json is what the site's /keeper page
 * shows. The signer is RUGBOND_KEEPER_KEY (CI secret) or the keeper role in
 * test/.accounts.json.
 */
import { readFileSync, writeFileSync, existsSync, mkdirSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { createRequire } from "node:module";
import { CHAINS as STUDIO, accounts, fundOnStudio, outcomeOf, retry, argOf, sleep } from "../test/harness.mjs";
import { manualPayoutFees } from "./lib/rb.mjs";
import { runKeeper, emptyState, totals } from "./lib/keeper_core.mjs";
import { CHAINS } from "./lib/chains.mjs";
import { readHead } from "./lib/rug.mjs";

const { createClient, createAccount } = createRequire(new URL("../test/package.json", import.meta.url))("genlayer-js");
const root = new URL("..", import.meta.url).pathname;
const dir = argOf("state", root + "state").replace(/\/$/, "");
const push = process.argv.includes("--push");
mkdirSync(dir, { recursive: true });
const depAll = JSON.parse(readFileSync(root + "deployments.json", "utf8"));
const dep = depAll.contracts;
const only = argOf("contracts", "");
// the current registries, and every superseded registry (its bonds still get checked and settled until every GEN is out)
const targets = ["RugBond", "RugBondDemo"].filter((n) => dep[n]).map((n) => ({ name: n, address: dep[n].address }))
  .concat((depAll.superseded ?? []).filter((x) => x.name.startsWith("RugBond")).map((x) => ({ name: `${x.name}@${x.address.slice(0, 10)}`, address: x.address })))
  .filter((x) => !only || only.split(",").includes(x.name.split("@")[0]));

const key = accounts().keeper?.key;
if (!key) { console.error("no keeper key (RUGBOND_KEEPER_KEY or test/.accounts.json)"); process.exit(1); }
const account = createAccount(key);
const wallet = createClient({ chain: STUDIO.studiodev, account });
const read = createClient({ chain: STUDIO.studiodev });
await fundOnStudio(STUDIO.studiodev, account.address, 50n * 10n ** 18n);
const plain = (v) => JSON.parse(JSON.stringify(v, (k, x) => (typeof x === "bigint" ? x.toString() : x instanceof Map ? Object.fromEntries(x) : x)));
const asObj = (v) => plain(typeof v === "string" ? JSON.parse(v) : v);

const git = (...a) => execFileSync("git", ["-C", dir, ...a], { stdio: ["ignore", "pipe", "pipe"] }).toString();
const isRepo = existsSync(dir + "/.git");
let lastPush = 0;
function commit(files, why, force = false) {
  if (!isRepo) return;
  try {
    git("add", ...files);
    if (git("status", "--porcelain").trim() === "") return;
    git("-c", "user.name=rugbond-keeper", "-c", "user.email=keeper@users.noreply.github.com", "commit", "-qm", "keeper: " + why);
    if (push && (force || why.startsWith("submitted") || Date.now() - lastPush > 30_000)) { git("push", "-q", "origin", "HEAD:keeper-state"); lastPush = Date.now(); }
  } catch (e) { console.log("  state commit/push failed: " + String(e.message).slice(0, 160)); }
}

const chain = { endpoints: (ch) => CHAINS[ch]?.rpcs ?? [], head: (u, ch) => readHead(u, ch) };

function regFor(address) {
  const view = async (fn, args) => asObj(await retry(() => read.readContract({ address, functionName: fn, args }), { label: fn }));
  async function getTx(hash) {
    const tx = await retry(() => read.getTransaction({ hash }), { attempts: 4, label: "poll" }).catch(() => null);
    if (!tx) return null;
    const o = outcomeOf(tx);
    return { statusName: o.status, ok: o.ok, reason: o.revertReason };
  }
  const now = () => Math.floor(Date.now() / 1000);
  return {
    now,
    listBonds: (off, lim) => view("list_bonds", [off, lim, now()]),
    listClaims: (bid, off, lim) => view("list_claims", [bid, off, lim]),
    getBond: (bid) => view("get_bond", [bid, now()]),
    async check(bid) {
      const fees = await retry(() => wallet.estimateTransactionFees(), { label: "fees" }).then((e) => ({ distribution: e.distribution, feeValue: e.feeValue })).catch(() => null);
      return retry(() => wallet.writeContract({ address, functionName: "check", args: [bid], value: 0n, ...(fees ? { fees } : {}) }), { label: "check" });
    },
    async settle(bid, payee) {
      const fees = await manualPayoutFees(wallet, payee);
      return retry(() => wallet.writeContract({ address, functionName: "settle", args: [bid], value: 0n, fees }), { label: "settle" });
    },
    getTx,
    sleep,
    async wait(hash, ms) {
      const t0 = Date.now();
      for (;;) {
        const tx = await getTx(hash);
        if (tx && ["ACCEPTED", "FINALIZED", "UNDETERMINED", "CANCELED", "LEADER_TIMEOUT", "VALIDATORS_TIMEOUT"].includes(tx.statusName)) return tx;
        if (Date.now() - t0 > ms) return tx;
        await sleep(15_000);
      }
    },
  };
}

let prev = {};
try { prev = JSON.parse(readFileSync(`${dir}/status.json`, "utf8")).contracts ?? {}; } catch { /* first run */ }
const status = { keeper: account.address, started_at: new Date().toISOString(), contracts: { ...prev } };
for (const { name, address } of targets) {
  const file = `${dir}/keeper-state-${name}.json`;
  const store = {
    async load() { return existsSync(file) ? JSON.parse(readFileSync(file, "utf8")) : emptyState(); },
    async save(state, why) {
      state.contract = name; state.address = address; state.keeper = account.address; state.saved_at = new Date().toISOString();
      writeFileSync(file, JSON.stringify(state, null, 1) + "\n");
      commit([file.slice(dir.length + 1)], `${name} ${why}`, why === "run finished");
    },
  };
  console.log(`keeper ${account.address}  ${name} ${address}  state ${file}${isRepo ? " (git)" : ""}`);
  const { run, state } = await runKeeper({ chain, reg: regFor(address), store, log: (l) => console.log("  " + l),
    maxActions: Number(argOf("max", "25")), waitMs: Number(argOf("wait", "300")) * 1000, settleMs: Number(argOf("settle", "900")) * 1000 });
  console.log(`  run: resumed ${run.resumed}, bonds ${run.bonds}, pages ${run.pages} (failed ${run.pages_failed}), heads failed ${run.heads_failed}, queued ${run.queued}, submitted ${run.submitted}, done ${run.done}, already ${run.already}, pending ${run.pending}, retry ${run.retry}, failed ${run.failed}`);
  for (const u of state.unprocessed) console.log(`  unprocessed ${u.key}: ${u.why}`);
  status.contracts[name] = { address, last_run: run, totals: totals(state), bonds: state.bonds, unprocessed: state.unprocessed,
    actions: Object.values(state.actions).map((a) => ({ key: a.key, kind: a.kind, bond_id: a.bond_id, status: a.status, result: a.result ?? "",
      tx: a.tx ?? a.tx_history?.at(-1) ?? "", attempts: a.attempts, last_error: a.last_error ?? "" })) };
}
status.finished_at = new Date().toISOString();
status.trigger = process.env.GITHUB_EVENT_NAME ?? "manual";
status.run_url = process.env.GITHUB_RUN_ID ? `https://github.com/${process.env.GITHUB_REPOSITORY}/actions/runs/${process.env.GITHUB_RUN_ID}` : "";
let hist = [];
try { hist = JSON.parse(readFileSync(`${dir}/status.json`, "utf8")).history ?? []; } catch { /* first run */ }
status.history = [...hist, { started_at: status.started_at, finished_at: status.finished_at, trigger: status.trigger, run_url: status.run_url,
  runs: Object.fromEntries(Object.entries(status.contracts).map(([n, c]) => [n, { submitted: c.last_run.submitted, done: c.last_run.done, pages: c.last_run.pages, pages_failed: c.last_run.pages_failed }])) }].slice(-100);
writeFileSync(`${dir}/status.json`, JSON.stringify(status, null, 1) + "\n");
commit(["status.json"], "status", true);
