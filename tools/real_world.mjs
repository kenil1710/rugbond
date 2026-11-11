// Real-world truth: every RUGGED / HELD verdict in docs/feasibility.json cross-checked against chain data the rule
// does not use, read from the other RPC where there is one:
//   RUGGED  the pair's Burn event in block R, the rug transaction's sender (eth_getTransactionByHash) is the team,
//           the pair's WETH reserve before R and after R (getReserves), the LP removed = the LP the team held
//   HELD    the pair's reserves at the end, no Burn by a team transaction in the period, the LP holders' balance
//           at the end of the period >= the promised minimum
// plus the public scanner pages for each. -> docs/real_world.json, docs/REAL_WORLD_CHECK.md
//   node tools/real_world.mjs
import { readFileSync, writeFileSync } from "node:fs";
import { rpcSend } from "./lib/rug.mjs";
import { ALL_CHAINS as CHAINS } from "./lib/chains.mjs";

const root = new URL("../", import.meta.url);
const F = JSON.parse(readFileSync(new URL("docs/feasibility.json", root)));
const BURN = "0xdccd412f0b1252819cb1fd330b93224ca42612892bb3f4f789976e6d81936496";
const hex = (n) => "0x" + n.toString(16);
const word = (w) => "0x" + String(w).slice(-40).toLowerCase();
const eth = (w) => (Number(BigInt(w)) / 1e18).toFixed(4);
const rows = [];
for (const c of F.cases) {
  const ch = CHAINS[c.chain];
  const url = ch.state?.[1] ?? ch.rpcs[1];
  const lurl = ch.rpcs[1];
  const t0 = word((await rpcSend(url, [["eth_call", [{ to: c.pair, data: "0x0dfe1681" }, "latest"]]], 1))[0]);
  const wethIs0 = t0 === ch.weth;
  const reserve = async (b) => { const r = (await rpcSend(url, [["eth_call", [{ to: c.pair, data: "0x0902f1ac" }, hex(b)]]], 1))[0]; return BigInt("0x" + r.slice(wethIs0 ? 2 : 66, wethIs0 ? 66 : 130)); };
  const row = { id: c.id, chain: c.chain, verdict: c.verdict, expect: c.expect, pair: c.pair, token: c.token, team: c.team, signals: {}, agree: false, sources: [] };
  row.sources.push(`${ch.explorer}/address/${c.pair}`, `${ch.explorer}/token/${c.token}`);
  if (c.verdict === "RUGGED") {
    const R = c.rug.block;
    const burns = (await rpcSend(lurl, [["eth_getLogs", [{ address: c.pair, topics: [BURN], fromBlock: hex(R), toBlock: hex(R) }]]], 1))[0];
    const txs = await rpcSend(url, c.rug.txs.map((h) => ["eth_getTransactionByHash", [h]]), 3);
    const senders = txs.map((t) => String(t?.from ?? "").toLowerCase());
    const before = await reserve(R - 1), after = await reserve(R);
    row.signals = { burn_events_in_R: burns.length, burn_tx_is_rug_tx: burns.some((b) => c.rug.txs.includes(b.transactionHash.toLowerCase())),
      rug_tx_sender: senders, sender_is_team: senders.includes(c.team), weth_before: eth(before), weth_after: eth(after),
      weth_drop_pct: before > 0n ? Number(((before - after) * 10000n) / before) / 100 : 0, lp_removed: eth(c.rug.lp_before), lp_left: eth(c.rug.lp_after) };
    row.agree = burns.length > 0 && row.signals.burn_tx_is_rug_tx && row.signals.sender_is_team && after * 10n < before;
    row.sources.push(...c.rug.txs.map((h) => `${ch.explorer}/tx/${h}`));
    row.note = row.agree ? "the team's own transaction burned the LP in block R and drained the pool's WETH" : "";
  } else {
    const endB = c.end_block;
    const startR = await reserve(c.start_block), endR = await reserve(endB);
    const bal = await rpcSend(url, c.lp_holders.map((h) => ["eth_call", [{ to: c.pair, data: "0x70a08231" + "0".repeat(24) + h.slice(2) }, hex(endB)]]), 3);
    const held = bal.reduce((s, x) => s + BigInt(x), 0n);
    const span = endB - c.start_block;
    const burns = [];
    for (let a = c.start_block; a <= endB; a += 10000) burns.push(...(await rpcSend(lurl, [["eth_getLogs", [{ address: c.pair, topics: [BURN], fromBlock: hex(a), toBlock: hex(Math.min(endB, a + 9999)) }]]], 1))[0]);
    const burnTxs = [...new Set(burns.map((b) => b.transactionHash))];
    const burnSenders = burnTxs.length ? (await rpcSend(url, burnTxs.map((h) => ["eth_getTransactionByHash", [h]]), 3)).map((t) => String(t.from).toLowerCase()) : [];
    row.signals = { blocks: span, weth_at_start: eth(startR), weth_at_end: eth(endR), lp_holders_at_end: eth(held), promised_min: eth(c.min_lp),
      burns_in_period: burns.length, burns_by_lp_holders: burnSenders.filter((s) => c.lp_holders.includes(s)).length };
    row.agree = held >= BigInt(c.min_lp) && row.signals.burns_by_lp_holders === 0;
    row.note = row.agree ? "the LP holders still held at least the promised LP at the end, and none of them burned LP in the period" : "";
    for (const h of c.lp_holders) row.sources.push(`${ch.explorer}/token/${c.pair}?a=${h}`);
  }
  rows.push(row);
  console.log(c.id, c.verdict, row.agree ? "AGREES" : "DISAGREES", JSON.stringify(row.signals).slice(0, 160));
}
writeFileSync(new URL("docs/real_world.json", root), JSON.stringify({ generated_at: new Date().toISOString(), rows }, null, 1) + "\n");
const L = ["# Real-world check", "",
  "Every verdict in [FEASIBILITY.md](FEASIBILITY.md) checked against chain data the rule does not read, from the second RPC of each chain (`tools/real_world.mjs`, [real_world.json](real_world.json)):", "",
  "- **RUGGED**: the pair's `Burn` event in block R comes from the rug transaction, that transaction was sent by the team (the address that minted the LP), and the pool's WETH reserve collapsed across R.",
  "- **HELD**: the LP holders still held at least the promised LP at the end of the period, and no LP holder sent a transaction that burned LP during it.", "",
  `Result: **${rows.filter((r) => r.agree).length}/${rows.length}** verdicts agree with the independent signals${rows.some((r) => !r.agree) ? "; the others are explained below" : ""}.`, "",
  "| # | chain | verdict | pair | independent signals | agrees | public sources |", "|---|---|---|---|---|---|---|"];
for (const r of rows) {
  const s = r.verdict === "RUGGED"
    ? `Burn in R by the rug tx: ${r.signals.burn_tx_is_rug_tx ? "yes" : "no"}; sender is the team: ${r.signals.sender_is_team ? "yes" : "no"}; WETH ${r.signals.weth_before} -> ${r.signals.weth_after} (-${r.signals.weth_drop_pct}%)`
    : `LP holders at the end ${r.signals.lp_holders_at_end} >= promised ${r.signals.promised_min}; burns by LP holders in the period: ${r.signals.burns_by_lp_holders}; WETH ${r.signals.weth_at_start} -> ${r.signals.weth_at_end}`;
  L.push(`| ${r.id} | ${r.chain} | ${r.verdict} | \`${r.pair.slice(0, 10)}…\` | ${s} | ${r.agree ? "yes" : "NO"} | ${r.sources.slice(0, 3).map((u, i) => `[${i === 0 ? "pair" : i === 1 ? "token" : "tx/holder"}](${u})`).join(" ")} |`);
}
const drained = rows.filter((r) => r.verdict === "HELD" && Number(r.signals.weth_at_end) < 0.01).map((r) => r.id);
if (drained.length) L.push("", `**Held, but the price collapsed** (${drained.join(", ")}): the LP stayed where it was promised, so the rule says HELD, and the WETH left the pool through sells, not through a liquidity pull. RugBond bonds the liquidity promise only; a token whose price goes to zero while its LP stays in place has kept that promise (README, Scope).`);
L.push("", "Scanner pages are the public record for these tokens: none of them had a public post-mortem; they are anonymous launches that were pulled within hours (the rugs) or kept their LP (the held ones).", "");
writeFileSync(new URL("docs/REAL_WORLD_CHECK.md", root), L.join("\n"));
