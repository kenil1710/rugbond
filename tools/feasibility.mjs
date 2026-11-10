// Step 0b from this machine: every case in data/cases.json scanned to a verdict
// with the contract's reads (tools/lib/rug.mjs), each read made on BOTH RPCs of
// its chain and compared; for RUGGED cases the token holders at R-1 (recipients
// of the token since the start block, minus excluded addresses and contracts)
// with their balances and shares of a 1-GEN bond. -> docs/feasibility.json
//   node tools/feasibility.mjs [--only=id,id]
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { scanToVerdict, readHolder, shareOf, rpcSend, rpcStats, canon } from "./lib/rug.mjs";
import { CHAINS, TRANSFER } from "./lib/chains.mjs";
import { termsOf } from "./lib/terms.mjs";
const root = new URL("../", import.meta.url);
const only = process.argv.find((a) => a.startsWith("--only="))?.slice(7).split(",");
const cases = JSON.parse(readFileSync(new URL("data/cases.json", root))).cases;
const outPath = new URL("docs/feasibility.json", root);
const prev = existsSync(outPath) ? JSON.parse(readFileSync(outPath)) : { cases: [] };
const out = { generated_at: new Date().toISOString(), rpcs: Object.fromEntries(Object.entries(CHAINS).map(([k, v]) => [k, v.rpcs])), cases: [] };
const word = (w) => "0x" + String(w).slice(-40).toLowerCase();

async function holdersAt(c, t, R) {
  // recipients of the token in [start_block - 50000 (Ethereum) or start, R-1]; their balance at R-1 on both RPCs
  const ch = CHAINS[c.chain];
  const from = c.start_block, to = R - 1, span = c.chain === "ethereum" ? 10000 : 1000;
  const calls = [];
  for (let a = from; a <= to; a += span) calls.push(["eth_getLogs", [{ address: c.token, topics: [TRANSFER], fromBlock: "0x" + a.toString(16), toBlock: "0x" + Math.min(to, a + span - 1).toString(16) }]]);
  const parts = await rpcSend(ch.rpcs[0], calls, 1);
  const rec = new Set();
  for (const p of parts) for (const l of p) rec.add(word(l.topics[2]));
  const cand = [...rec].filter((a) => !t.excluded_all.includes(a)).sort();
  const rows = [];
  for (const h of cand) {
    const r = await readHolder(c.chain, c.token, h, R);
    rows.push({ holder: h, ...r });
  }
  return rows;
}

for (const c of cases) {
  if (only && !only.includes(c.id)) { const p = prev.cases.find((x) => x.id === c.id); if (p) out.cases.push(p); continue; }
  const t = termsOf(c);
  const t0 = Date.now();
  const r = await scanToVerdict(t);
  const row = { id: c.id, chain: c.chain, kind: c.kind, token: c.token, pair: c.pair, team: c.team, lp_holders: c.lp_holders, min_lp: c.min_lp,
    start_block: c.start_block, start_ts: c.start_ts, end_time: c.end_time, expect: c.expect, verdict: r.verdict, reason: r.reason ?? "",
    checks: r.checks, pair_check: r.checks.length ? undefined : r.pair, seconds: (Date.now() - t0) / 1000 };
  if (r.facts) {
    row.pair_check = r.checks.length === 1 ? r.facts.pair : undefined;
    const w = r.facts.window;
    if (r.verdict === "RUGGED") {
      row.rug = w.rug;
      // liquidity (WETH reserve) before / after
      const weth = CHAINS[c.chain].weth;
      const res = await rpcSend(CHAINS[c.chain].rpcs[0], [["eth_call", [{ to: c.pair, data: "0x0dfe1681" }, "latest"]],
        ["eth_call", [{ to: c.pair, data: "0x0902f1ac" }, "0x" + (w.rug.block - 1).toString(16)]], ["eth_call", [{ to: c.pair, data: "0x0902f1ac" }, "0x" + w.rug.block.toString(16)]]], 1);
      const w0 = word(res[0]) === weth;
      const pick = (x) => BigInt("0x" + x.slice(w0 ? 2 : 66, w0 ? 66 : 130)).toString();
      row.weth_before = pick(res[1]); row.weth_after = pick(res[2]);
      const hs = await holdersAt(c, t, w.rug.block);
      const ok = hs.filter((h) => h.balance !== undefined);
      const eoas = ok.filter((h) => !h.code && BigInt(h.balance) > 0n);
      row.holders = { candidates: hs.length, readable: ok.length, unreadable: hs.length - ok.length, eoa_with_balance: eoas.length,
        contracts: ok.filter((h) => h.code).length,
        sum_eoa_balance: eoas.reduce((s, h) => s + BigInt(h.balance), 0n).toString(),
        top: eoas.sort((a, b) => (BigInt(b.balance) > BigInt(a.balance) ? 1 : -1)).slice(0, 8)
          .map((h) => ({ holder: h.holder, balance: h.balance, share_of_1_gen: shareOf(10n ** 18n, h.balance, w.rug.denom).toString() })) };
    } else {
      row.end_block = w.b; row.end_ts = w.end_ts;
    }
  }
  out.cases.push(row);
  console.log(c.id.padEnd(8), c.expect.padEnd(7), r.verdict.padEnd(8), (r.reason ?? "").padEnd(14), "checks", r.checks.length,
    row.rug ? `R ${row.rug.block} holders ${row.holders.eoa_with_balance}/${row.holders.candidates}` : "", `${row.seconds}s`, JSON.stringify(rpcStats()));
  writeFileSync(outPath, JSON.stringify(out, (k, v) => (typeof v === "bigint" ? v.toString() : v), 1) + "\n");
}
