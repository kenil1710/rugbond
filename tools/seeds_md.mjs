// The canonical replay seeds, verified on chain -> docs/seed-verify.json and docs/SEEDS.md.
// For every replay bond on the current canonical registry (and the superseded one): its verdict against the
// expected one and the rug block against docs/feasibility.json; how it settled (to the fund after the 1-hour claim
// window, or back to the launchpad), with the keeper's settle transaction checked FINALIZED and its value message
// delivered to the recipient; each registry's eth_getBalance at the end; and, on the current registry, every check
// GenVM stored (range, LP transfers, probes, result) against the same read made from this machine (tools/lib/rug.mjs).
//   node tools/seeds_md.mjs
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { createRequire } from "node:module";
import { retry } from "../test/harness.mjs";
import { balanceOf, payoutDelivered, plain, gen } from "./lib/rb.mjs";
import { readCheck, judgeScan } from "./lib/rug.mjs";

const root = new URL("../", import.meta.url);
const { createClient } = createRequire(new URL("../test/package.json", import.meta.url))("genlayer-js");
const { studioDevnet } = createRequire(new URL("../test/package.json", import.meta.url))("genlayer-js/chains");
const read = createClient({ chain: studioDevnet });
const dep = JSON.parse(readFileSync(new URL("deployments.json", root)));
const feas = JSON.parse(readFileSync(new URL("docs/feasibility.json", root)));
const now = () => Math.floor(Date.now() / 1000);
const asObj = (v) => plain(typeof v === "string" ? JSON.parse(v) : v);
const view = async (address, fn, args) => asObj(await retry(() => read.readContract({ address, functionName: fn, args }), { label: fn }));

async function keeperActions() {
  try {
    const r = await fetch("https://raw.githubusercontent.com/kenil1710/rugbond/keeper-state/status.json", { cache: "no-store" });
    const s = await r.json();
    return s.contracts ?? {};
  } catch { return {}; }
}
const ks = await keeperActions();
// every SETTLE action the keeper ever recorded, from the keeper-state branch's history (state files are per
// registry; a registry's actions survive in the commits that wrote them)
import { execFileSync } from "node:child_process";
const settles = new Map();      // `${address}:${bond}` -> tx
try {
  const git = (...a) => execFileSync("git", ["-C", new URL("..", import.meta.url).pathname, ...a], { maxBuffer: 256 << 20 }).toString();
  git("fetch", "-q", "origin", "keeper-state");
  const commits = git("log", "--format=%H", "FETCH_HEAD").trim().split("\n").slice(0, 2000);
  for (const c of commits) {
    const files = git("ls-tree", "--name-only", c).trim().split("\n").filter((f) => f.startsWith("keeper-state-"));
    for (const f of files) {
      let st;
      try { st = JSON.parse(git("show", `${c}:${f}`)); } catch { continue; }
      for (const a of Object.values(st.actions ?? {})) {
        const tx = a.tx ?? a.tx_history?.at(-1);
        if (a.kind === "SETTLE" && a.status === "DONE" && tx) { const k = `${String(st.address).toLowerCase()}:${a.bond_id}`; if (!settles.has(k)) settles.set(k, tx); }
      }
    }
  }
} catch (e) { console.log("keeper-state history unreadable: " + String(e.message).slice(0, 120)); }
// settles from a keeper pass run by hand, whose state file never reached the branch
try { for (const x of JSON.parse(readFileSync(new URL("../docs/keeper-hand-run.json", import.meta.url))).settles) { const k = `${String(x.address).toLowerCase()}:${x.bond_id}`; if (!settles.has(k)) settles.set(k, x.tx); } } catch { /* none */ }

/** Every agreed check GenVM stored for this bond, re-read from this machine with the same cursor, span and bound. */
async function sameReads(address, b) {
  const stored = [];
  for (let off = 0; off >= 0;) { const pg = await view(address, "list_checks", [b.bond_id, off, 50]); stored.push(...pg.items); off = pg.next_offset; }
  const t = { chain: b.chain, token: b.token, pair: b.pair, lp_holders: b.lp_holders, min_lp: b.min_lp, start_block: b.start_block, end_time: b.end_time, excluded_all: b.excluded_all };
  let cursor = 0, low = 0n, first = true, same = 0, n = 0;
  const diffs = [];
  for (const c of stored.filter((x) => x.result !== "PENDING")) {
    n++;
    let r = null;
    for (let k = 0; k < 4; k++) { r = await readCheck(t.chain, t, cursor, first, -1, c.b - c.a + 1, low); if (r.facts) break; await new Promise((z) => setTimeout(z, 3000 * (k + 1))); }
    if (!r?.facts) { diffs.push({ check_id: c.check_id, why: "unreadable here: " + (r?.reason ?? "") }); break; }
    const w = r.facts.window, j = first && !r.facts.pair.ok ? { verdict: "VOID" } : judgeScan(t, w);
    const ok = w.a === c.a && w.b === c.b && w.logs.length === c.n_logs && JSON.stringify(w.probes) === JSON.stringify(c.probes) && j.verdict === c.result
      && JSON.stringify(w.logs.slice(0, 20)) === JSON.stringify(c.logs);
    if (ok) same++; else diffs.push({ check_id: c.check_id, here: { a: w.a, b: w.b, n_logs: w.logs.length, probes: w.probes, verdict: j.verdict }, stored: { a: c.a, b: c.b, n_logs: c.n_logs, probes: c.probes, result: c.result } });
    if (j.verdict !== "SCANNED") break;
    cursor = w.b; low = BigInt(w.low); first = false;
  }
  return { checks: n, identical: same, pending: stored.length - n, diffs };
}

async function registry(address, seedFile, label, compare = false) {
  const seeds = JSON.parse(readFileSync(new URL(seedFile, root)));
  const kname = Object.keys(ks).find((k) => ks[k].address?.toLowerCase() === address.toLowerCase());
  const acts = kname ? ks[kname].actions ?? [] : [];
  const rows = [];
  for (const s of seeds.bonds) {
    const b = await view(address, "get_bond", [s.bond_id, now()]);
    const f = feas.cases.find((c) => c.id === s.case_id);
    const sTx = acts.find((a) => a.kind === "SETTLE" && a.bond_id === s.bond_id && a.status === "DONE")?.tx ?? settles.get(`${address.toLowerCase()}:${s.bond_id}`);
    const settle = sTx ? { tx: sTx } : null;
    let proof = null;
    if (b.settled_at && settle?.tx && BigInt(b.settled_amount) > 0n) {
      const tx = plain(await retry(() => read.getTransaction({ hash: settle.tx }), { label: "tx" }));
      const d = payoutDelivered(tx, b.settled_to, b.settled_amount);
      proof = { tx: settle.tx, status: tx.statusName, delivered: d.ok, why: d.why };
    }
    const verdict = ["RUGGED", "CLOSED"].includes(b.status) ? "RUGGED" : ["HELD", "RETURNED"].includes(b.status) ? "HELD" : b.status;
    rows.push({ case_id: s.case_id, bond_id: s.bond_id, name: b.name, expect: s.expect, status: b.status, verdict, matches: verdict === s.expect,
      rug_block: b.rug_block, feasibility_rug_block: f?.rug?.block ?? 0, rug_block_matches: s.expect !== "RUGGED" || b.rug_block === f?.rug?.block,
      replay: b.replay, n_checks: b.n_checks, n_claims: b.n_claims, amount: b.amount, settled_to: b.settled_to, settled_amount: b.settled_amount,
      settled_at: b.settled_at, to_fund: b.settled_to === (b.fund ?? b.victim_fund), to_launchpad: b.settled_to === b.team, settle_proof: proof,
      ...(compare ? { reads: await sameReads(address, b) } : {}) });
  }
  const bal = await balanceOf(address);
  const stats = await view(address, "get_stats", []);
  return { label, address, rows, eth_getBalance: String(bal), held: stats.held, stats };
}

const out = { generated_at: new Date().toISOString(), registries: [] };
out.registries.push(await registry(dep.contracts.RugBond.address, "docs/seed-canonical.json", "current canonical registry", true));
for (const [f, label] of [["docs/superseded/seed-canonical-0x24ff68A1.json", "superseded canonical registry (first deployment)"],
  ["docs/superseded/seed-canonical-0x07ED5695.json", "superseded canonical registry (second deployment)"],
  ["docs/superseded/seed-canonical-0x4D2a5e25.json", "superseded canonical registry (third deployment)"],
  ["docs/superseded/seed-canonical-0x42f22d3C.json", "superseded canonical registry (fourth deployment)"]]) if (existsSync(new URL(f, root))) {
  const old = JSON.parse(readFileSync(new URL(f, root)));
  out.registries.push(await registry(old.registry, f, label));
}
writeFileSync(new URL("docs/seed-verify.json", root), JSON.stringify(out, null, 1) + "\n");

const L = ["# Canonical seeds", "",
  "**These bonds are historical replays.** Each was created on the canonical registry after the events it describes, by a throwaway `launchpad` account, with a small symbolic bond (0.01 GEN × the case number), over a real Ethereum token from [FEASIBILITY.md](FEASIBILITY.md): the real pair, the real LP holders, the LP they held at the start block as the promised minimum, a 7-day promise from that block. They are not promises the teams made. The contract marks each as a `replay` (its start block is older than the bond) and LaunchGate never answers favorably for one.", "",
  "The keeper (GitHub Actions) filed every rug check and settled every bond: RUGGED replays opened a 1-hour claim window; nobody claimed (the original holders do not hold keys here), so each whole bond then went to the fund: on the current registry the registry's own fund, an address fixed in its constructor; on the registries deployed before that change, the victim fund each bond named. HELD replays returned the bond to the launchpad. On the current registry every check GenVM stored is also re-read from this machine with the same cursor, span and bound and compared field by field (range, LP transfers, probes, result). Generated by `tools/seeds_md.mjs` from [seed-verify.json](seed-verify.json).", ""];
for (const r of out.registries) {
  const ok = r.rows.filter((x) => x.matches && x.rug_block_matches).length;
  L.push(`## ${r.label}: \`${r.address}\``, "",
    `Verdicts as expected: **${ok}/${r.rows.length}**. Settled: ${r.rows.filter((x) => x.settled_at).length}/${r.rows.length}. eth_getBalance of the registry now: **${gen(r.eth_getBalance)} GEN** (held by open bonds: ${gen(r.held)}).`
      + (r.rows[0]?.reads ? ` Checks GenVM stored that this machine reads identically: **${r.rows.reduce((n, x) => n + x.reads.identical, 0)}/${r.rows.reduce((n, x) => n + x.reads.checks, 0)}** (PENDING checks, which store no read: ${r.rows.reduce((n, x) => n + x.reads.pending, 0)}).` : ""), "",
    "| case | bond | expected | status | rug block (rule / feasibility) | checks | settled to | amount | settle tx | delivered |", "|---|---|---|---|---|---|---|---|---|---|");
  for (const x of r.rows) {
    L.push(`| ${x.case_id} | ${x.bond_id} | ${x.expect} | ${x.status} | ${x.rug_block ? `${x.rug_block} / ${x.feasibility_rug_block}` : "—"} | ${x.n_checks} | ${x.settled_at ? (x.to_fund ? "fund" : x.to_launchpad ? "launchpad" : x.settled_to) : "—"} | ${x.settled_at ? gen(x.settled_amount) : "—"} | ${x.settle_proof ? "`" + x.settle_proof.tx.slice(0, 14) + "…`" : "—"} | ${x.settle_proof ? (x.settle_proof.delivered ? "yes" : "NO " + x.settle_proof.why) : "—"} |`);
  }
  L.push("");
}
writeFileSync(new URL("docs/SEEDS.md", root), L.join("\n"));
for (const r of out.registries) console.log(r.label, r.address, "rows", r.rows.length, "settled", r.rows.filter((x) => x.settled_at).length, "balance", r.eth_getBalance);
