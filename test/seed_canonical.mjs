/**
 * Canonical seeds: one replay bond per Ethereum case in data/cases.json on the
 * canonical RugBond, posted by the `launchpad` role with a small symbolic bond.
 * These are replays: created after the events they describe (the bond records
 * it: `replay` is true once its first check reads the start block's time).
 * The keeper files every rug check and settles every bond; this script only
 * creates the bonds and records them in docs/seed-canonical.json. Idempotent.
 *   node seed_canonical.mjs
 */
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { client, deployments, gen } from "../tools/lib/rb.mjs";
import { accounts } from "./harness.mjs";

const root = new URL("../", import.meta.url);
const dep = deployments().contracts;
const cases = JSON.parse(readFileSync(new URL("data/cases.json", root))).cases.filter((c) => c.chain === "ethereum");
const out = new URL("docs/seed-canonical.json", root);
const st = existsSync(out) ? JSON.parse(readFileSync(out, "utf8")) : { registry: dep.RugBond.address, bonds: [] };
const save = () => writeFileSync(out, JSON.stringify(st, null, 1) + "\n");
const acc = accounts();
const victim = acc.victimfund.address.toLowerCase();
const c = client({ role: "launchpad", address: dep.RugBond.address });
console.log("launchpad", c.me, "registry", dep.RugBond.address);
let i = 0;
for (const k of cases) {
  i++;
  if (st.bonds.some((b) => b.case_id === k.id && b.bond_id)) continue;
  const value = 10n ** 16n * BigInt(i);                 // 0.01 GEN x case number: symbolic
  const name = `${k.expect === "RUGGED" ? "Replay" : "Replay"} ${k.id} ${k.token.slice(0, 8)}`;
  const args = [name, "ethereum", k.token, k.pair, JSON.stringify(k.lp_holders), String(k.min_lp), k.start_block, k.end_time, 3600, victim,
    JSON.stringify(k.excluded), "0"];
  const r = await c.write("create_bond", args, { value });
  const ok = r.ok && r.returned?.ok === true;
  let bondId = r.returned?.bond_id ?? null;
  if (r.ok && !bondId) {
    const pg = await c.view("bonds_by_team", [c.me, 0, 50, Math.floor(Date.now() / 1000)]);
    bondId = pg.items.find((b) => b.name === name)?.bond_id ?? null;
  }
  st.bonds.push({ case_id: k.id, expect: k.expect, bond_id: bondId, tx: r.hash, status: r.status, ok: ok || !!bondId, value: value.toString(), name });
  save();
  console.log(k.id, k.expect, "bond", bondId, r.status, r.hash, gen(value), "GEN", r.reason ?? "");
}
