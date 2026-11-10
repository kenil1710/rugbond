// data/picks.json (chosen from discovery) -> data/cases.json: the frozen terms
// each replay bond uses. min_lp = the LP holders' summed LP balance at the end
// of the start block (the whole position they held), end_time = the start
// block's timestamp + the promised period (Ethereum 7 days, Base 12 hours: Base
// public RPCs serve logs over 1000 blocks at a time, so a Base check reads 8000
// blocks), excluded = the routers on that chain besides the automatic
// team / pair / token / LP holders / zero / dead.
//   node tools/make_cases.mjs
import { readFileSync, writeFileSync } from "node:fs";
import { CHAINS } from "./lib/chains.mjs";
import { rpcSend } from "./lib/rug.mjs";
const root = new URL("../", import.meta.url);
const picks = JSON.parse(readFileSync(new URL("data/picks.json", root)));
export const PERIOD = { ethereum: 7 * 86400, base: 12 * 3600 };
export const ROUTERS = {
  ethereum: ["0x7a250d5630b4cf539739df2c5dacb4c659f2488d", "0x66a9893cc07d91d95644aedd05d03f95e1dba8af", "0x3fc91a3afd70395cd496c647d5a6cc9d4b2b7fad",
    "0xd9e1ce17f2641f24ae83637ab66a2cca9c378b9f"],
  base: ["0x4752ba5dbc23f44d87826276bf6fd6b1c372ad24", "0x6ff5693b99212da76ad316178a184ab56d299b43", "0xcf77a3ba9a5ca399b7c97c74d54e5b1beb874e43",
    "0x6bded42c6da8fbf0d2ba55b2fa120c5e0c8d7891"],
};
const out = [];
let i = 0;
for (const p of picks) {
  i++;
  const url = CHAINS[p.chain].rpcs[0];
  const calls = [["eth_getBlockByNumber", ["0x" + p.start_block.toString(16), false]],
    ...p.lp_holders.map((h) => ["eth_call", [{ to: p.pair, data: "0x70a08231" + "0".repeat(24) + h.slice(2) }, "0x" + p.start_block.toString(16)]])];
  const r = await rpcSend(url, calls, 1);
  const ts = parseInt(r[0].timestamp, 16);
  const minLp = r.slice(1).reduce((s, x) => s + BigInt(x), 0n);
  const c = { id: `${p.chain === "ethereum" ? "eth" : "base"}-${String(i).padStart(2, "0")}`, ...p, min_lp: minLp.toString(), start_ts: ts,
    end_time: ts + PERIOD[p.chain], excluded: ROUTERS[p.chain].filter((x) => !p.lp_holders.includes(x)) };
  out.push(c);
  console.log(c.id, c.chain, c.pair, c.expect, "min_lp", c.min_lp, "start", c.start_block, new Date(ts * 1000).toISOString());
}
writeFileSync(new URL("data/cases.json", root), JSON.stringify({ generated_at: new Date().toISOString(), cases: out }, null, 1) + "\n");
