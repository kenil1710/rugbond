// Discovery on Base (Step 0a), where public endpoints serve eth_getLogs over at
// most 1000 blocks: pairs created in a range (factory logs, 1000-block windows),
// then per pair the WETH reserve at the first mint and FOLLOW blocks later
// (archive eth_call). A collapse is bisected to the block where the reserve
// fell, and the LP Transfer logs of that block name who pulled it.
//   node tools/discover_base.mjs --from=<block> --to=<block> [--follow=43200]
import { rpc, logs, word, TRANSFER, PAIR_CREATED, AERO_POOL_CREATED, reserves, sleep, hex } from "./lib/evm.mjs";
const arg = (k, d) => process.argv.find((a) => a.startsWith(`--${k}=`))?.split("=")[1] ?? d;
const URL_ = arg("rpc", "https://base.gateway.tenderly.co");
const WETH = "0x4200000000000000000000000000000000000006";
const F = { "0x8909dc15e40173ff4699343b6eb8132c65e18ec6": "uniswap-v2", "0x71524b4f93c58fcbf659783284e38825f0622859": "sushiswap",
  "0x420dd381b31aef6683db6b902084cb0ffece40da": "aerodrome" };
const from = +arg("from"), to = +arg("to"), follow = +arg("follow", 43200), minEth = BigInt(Math.round(+arg("mineth", "0.3") * 1e18));
const ZERO = "0x0000000000000000000000000000000000000000";
const pairs = [];
for (const [f, kind] of Object.entries(F)) {
  const ls = await logs(URL_, { address: f, topics: [kind === "aerodrome" ? AERO_POOL_CREATED : PAIR_CREATED] }, from, to, 1000);
  for (const l of ls) {
    const t0 = word(l.topics[1]), t1 = word(l.topics[2]);
    if (kind === "aerodrome" && l.topics[3] !== "0x" + "0".repeat(64)) continue;
    if (t0 !== WETH && t1 !== WETH) continue;
    pairs.push({ pair: word("0x" + l.data.slice(2, 66)), kind, token: t0 === WETH ? t1 : t0, w0: t0 === WETH, block: parseInt(l.blockNumber, 16) });
  }
}
console.error(`base: ${pairs.length} WETH pairs in ${from}-${to}`);
const wethAt = async (p, b) => { const [a, c] = await reserves(URL_, p.pair, b); return p.w0 ? a : c; };
for (const p of pairs) {
  try {
    // first block with a WETH reserve (the first mint): bisect over 2000 blocks after creation
    let lo = p.block, hi = p.block + 20000;
    if ((await wethAt(p, hi)) === 0n) { console.error("noliq", p.pair, p.kind); continue; }
    while (hi - lo > 1) { const m = (lo + hi) >> 1; if ((await wethAt(p, m)) > 0n) hi = m; else lo = m; }
    const start = (await wethAt(p, p.block)) > 0n ? p.block : hi;
    const mint = (await rpc(URL_, "eth_getLogs", [{ address: p.pair, topics: [TRANSFER, "0x" + "0".repeat(64)], fromBlock: hex(start), toBlock: hex(start) }]))
      .find((l) => word(l.topics[2]) !== ZERO && word(l.topics[2]) !== "0x000000000000000000000000000000000000dead");
    if (!mint) { console.error("nomint", p.pair, start); continue; }
    const team = word(mint.topics[2]);
    const w0 = await wethAt(p, start);
    if (w0 < minEth) { console.error("small", p.pair, p.kind, Number(w0)/1e18); continue; }
    const end = start + follow;
    const w1 = await wethAt(p, end);
    const rec = { chain: "base", kind: p.kind, pair: p.pair, token: p.token, team, start, weth_at_start: String(w0), weth_at_end: String(w1), lp_minted: BigInt(mint.data).toString() };
    if (w1 * 20n < w0) {
      lo = start; hi = end;
      while (hi - lo > 1) { const m = (lo + hi) >> 1; if ((await wethAt(p, m)) * 20n < w0) hi = m; else lo = m; }
      const R = hi;
      const lt = await rpc(URL_, "eth_getLogs", [{ address: p.pair, topics: [TRANSFER], fromBlock: hex(R), toBlock: hex(R) }]);
      rec.rug = { block: R, weth_before: String(await wethAt(p, R - 1)), weth_after: String(await wethAt(p, R)),
        lp_moves: lt.map((l) => ({ from: word(l.topics[1]), to: word(l.topics[2]), amount: BigInt(l.data).toString(), tx: l.transactionHash })) };
    }
    console.log(JSON.stringify(rec));
  } catch (e) { console.error(p.pair, String(e.message).slice(0, 120)); }
  await sleep(100);
}
