// The e2e run's rugged bond: the team opens a bond on E2EDEMO on the demo registry, starting at the latest block
// (after the e2e wallet got its tokens). Prints {"bond_id", "start_block"}.
import { readFileSync, writeFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { client, deployments, finalized } from "../tools/lib/rb.mjs";
import { accounts } from "./harness.mjs";
const evmPath = new URL("../docs/demo-evm.json", import.meta.url);
const e = JSON.parse(readFileSync(evmPath, "utf8")).E2EDEMO;
if (e.bond_id) { console.log(JSON.stringify({ bond_id: e.bond_id, start_block: e.start_block })); process.exit(0); }
const acc = accounts();
const c = client({ role: "team", address: deployments().contracts.RugBondDemo.address });
const start = Number(execFileSync("node", [new URL("./demo_evm.mjs", import.meta.url).pathname, "head"]).toString().trim());
const name = "E2EDEMO liquidity bond " + start;
const w = await c.write("create_bond", [name, "base-sepolia", e.token, e.pair, JSON.stringify([e.team]), e.lp_minted, start, Math.floor(Date.now() / 1000) + 3 * 3600, 600,
  acc.victimfund.address.toLowerCase(), JSON.stringify(["0x1689e7b1f10000ae47ebfe339a4f69decd19f602"]), "0"], { value: 10n ** 18n });
await finalized(c.read, w.hash);
const pg = await c.view("bonds_by_team", [c.me, 0, 50, Math.floor(Date.now() / 1000)]);
const b = pg.items.find((x) => x.name === name);
const all = JSON.parse(readFileSync(evmPath, "utf8"));
Object.assign(all.E2EDEMO, { bond_id: b.bond_id, start_block: start, bond_tx: w.hash });
writeFileSync(evmPath, JSON.stringify(all, null, 1) + "\n");
console.log(JSON.stringify({ bond_id: b.bond_id, start_block: start }));
