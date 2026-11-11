// The canonical replay seeds, verified on chain -> docs/seed-verify.json and docs/SEEDS.md.
// For every replay bond on the current canonical registry (and the superseded one): its verdict against the
// expected one and the rug block against docs/feasibility.json; how it settled (to the victim fund after the
// 1-hour claim window, or back to the launchpad), with the keeper's settle transaction checked FINALIZED and its
// value message delivered to the recipient; and each registry's eth_getBalance at the end.
//   node tools/seeds_md.mjs
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { createRequire } from "node:module";
import { balanceOf, payoutDelivered, plain, gen } from "./lib/rb.mjs";

const root = new URL("../", import.meta.url);
const { createClient } = createRequire(new URL("../test/package.json", import.meta.url))("genlayer-js");
const { studioDevnet } = createRequire(new URL("../test/package.json", import.meta.url))("genlayer-js/chains");
const read = createClient({ chain: studioDevnet });
const dep = JSON.parse(readFileSync(new URL("deployments.json", root)));
const feas = JSON.parse(readFileSync(new URL("docs/feasibility.json", root)));
const now = () => Math.floor(Date.now() / 1000);
const asObj = (v) => plain(typeof v === "string" ? JSON.parse(v) : v);
const view = async (address, fn, args) => asObj(await read.readContract({ address, functionName: fn, args }));

async function keeperActions() {
  try {
    const r = await fetch("https://raw.githubusercontent.com/kenil1710/rugbond/keeper-state/status.json", { cache: "no-store" });
    const s = await r.json();
    return s.contracts ?? {};
  } catch { return {}; }
}
const ks = await keeperActions();

async function registry(address, seedFile, label) {
  const seeds = JSON.parse(readFileSync(new URL(seedFile, root)));
  const kname = Object.keys(ks).find((k) => ks[k].address?.toLowerCase() === address.toLowerCase());
  const acts = kname ? ks[kname].actions ?? [] : [];
  const rows = [];
  for (const s of seeds.bonds) {
    const b = await view(address, "get_bond", [s.bond_id, now()]);
    const f = feas.cases.find((c) => c.id === s.case_id);
    const settle = acts.find((a) => a.kind === "SETTLE" && a.bond_id === s.bond_id && a.status === "DONE");
    let proof = null;
    if (b.settled_at && settle?.tx && BigInt(b.settled_amount) > 0n) {
      const tx = plain(await read.getTransaction({ hash: settle.tx }));
      const d = payoutDelivered(tx, b.settled_to, b.settled_amount);
      proof = { tx: settle.tx, status: tx.statusName, delivered: d.ok, why: d.why };
    }
    const verdict = ["RUGGED", "CLOSED"].includes(b.status) ? "RUGGED" : ["HELD", "RETURNED"].includes(b.status) ? "HELD" : b.status;
    rows.push({ case_id: s.case_id, bond_id: s.bond_id, name: b.name, expect: s.expect, status: b.status, verdict, matches: verdict === s.expect,
      rug_block: b.rug_block, feasibility_rug_block: f?.rug?.block ?? 0, rug_block_matches: s.expect !== "RUGGED" || b.rug_block === f?.rug?.block,
      replay: b.replay, n_checks: b.n_checks, n_claims: b.n_claims, amount: b.amount, settled_to: b.settled_to, settled_amount: b.settled_amount,
      settled_at: b.settled_at, to_victim_fund: b.settled_to === b.victim_fund, to_launchpad: b.settled_to === b.team, settle_proof: proof });
  }
  const bal = await balanceOf(address);
  const stats = await view(address, "get_stats", []);
  return { label, address, rows, eth_getBalance: String(bal), held: stats.held, stats };
}

const out = { generated_at: new Date().toISOString(), registries: [] };
out.registries.push(await registry(dep.contracts.RugBond.address, "docs/seed-canonical.json", "current canonical registry"));
for (const [f, label] of [["docs/superseded/seed-canonical-0x24ff68A1.json", "superseded canonical registry (first deployment)"],
  ["docs/superseded/seed-canonical-0x07ED5695.json", "superseded canonical registry (second deployment)"]]) if (existsSync(new URL(f, root))) {
  const old = JSON.parse(readFileSync(new URL(f, root)));
  out.registries.push(await registry(old.registry, f, label));
}
writeFileSync(new URL("docs/seed-verify.json", root), JSON.stringify(out, null, 1) + "\n");

const L = ["# Canonical seeds", "",
  "**These bonds are historical replays.** Each was created on the canonical registry after the events it describes, by a throwaway `launchpad` account, with a small symbolic bond (0.01 GEN × the case number), over a real Ethereum token from [FEASIBILITY.md](FEASIBILITY.md): the real pair, the real LP holders, the LP they held at the start block as the promised minimum, a 7-day promise from that block. They are not promises the teams made. The contract marks each as a `replay` (its start block is older than the bond) and LaunchGate never answers favorably for one.", "",
  "The keeper (GitHub Actions) filed every rug check and settled every bond: RUGGED replays opened a 1-hour claim window and then sent what nobody claimed to the victim fund (the original holders do not hold keys here, and under the claim rule they bought after the start block, so no claim was possible); HELD replays returned the bond to the launchpad. Generated by `tools/seeds_md.mjs` from [seed-verify.json](seed-verify.json).", ""];
for (const r of out.registries) {
  const ok = r.rows.filter((x) => x.matches && x.rug_block_matches).length;
  L.push(`## ${r.label}: \`${r.address}\``, "",
    `Verdicts as expected: **${ok}/${r.rows.length}**. Settled: ${r.rows.filter((x) => x.settled_at).length}/${r.rows.length}. eth_getBalance of the registry now: **${gen(r.eth_getBalance)} GEN** (held by open bonds: ${gen(r.held)}).`, "",
    "| case | bond | expected | status | rug block (rule / feasibility) | checks | settled to | amount | settle tx | delivered |", "|---|---|---|---|---|---|---|---|---|---|");
  for (const x of r.rows) {
    L.push(`| ${x.case_id} | ${x.bond_id} | ${x.expect} | ${x.status} | ${x.rug_block ? `${x.rug_block} / ${x.feasibility_rug_block}` : "—"} | ${x.n_checks} | ${x.settled_at ? (x.to_victim_fund ? "victim fund" : x.to_launchpad ? "launchpad" : x.settled_to) : "—"} | ${x.settled_at ? gen(x.settled_amount) : "—"} | ${x.settle_proof ? "`" + x.settle_proof.tx.slice(0, 14) + "…`" : "—"} | ${x.settle_proof ? (x.settle_proof.delivered ? "yes" : "NO " + x.settle_proof.why) : "—"} |`);
  }
  L.push("");
}
writeFileSync(new URL("docs/SEEDS.md", root), L.join("\n"));
for (const r of out.registries) console.log(r.label, r.address, "rows", r.rows.length, "settled", r.rows.filter((x) => x.settled_at).length, "balance", r.eth_getBalance);
