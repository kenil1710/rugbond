// Discovery (Step 0a): new Uniswap V2-style pairs in a block range, their first
// LP recipient (the team), and what that address did with its LP afterwards.
//   node tools/discover.mjs --chain=ethereum --from=<block> --to=<block> [--follow=<blocks>]
// Prints one JSON line per pair to stdout: candidates for data/cases.json. The
// verdicts in the docs come from tools/feasibility.mjs, not from here.
import { rpc, logs, word, TRANSFER, PAIR_CREATED, AERO_POOL_CREATED, reserves, call, sleep } from "./lib/evm.mjs";
const arg = (k, d) => process.argv.find((a) => a.startsWith(`--${k}=`))?.split("=")[1] ?? d;
const CH = {
  ethereum: { url: "https://gateway.tenderly.co/public/mainnet", span: 50000, weth: "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
    factories: { "0x5c69bee701ef814a2b6a3edd4b1652cb9cc5aa6f": "uniswap-v2", "0xc0aee478e3658e2610c5f7a4a2e1777ce9e4f2ac": "sushiswap" } },
  base: { url: "https://base.drpc.org", span: 9000, weth: "0x4200000000000000000000000000000000000006",
    factories: { "0x8909dc15e40173ff4699343b6eb8132c65e18ec6": "uniswap-v2", "0x71524b4f93c58fcbf659783284e38825f0622859": "sushiswap",
      "0x420dd381b31aef6683db6b902084cb0ffece40da": "aerodrome" } },
};
const chain = arg("chain", "ethereum"), c = CH[chain];
const from = +arg("from"), to = +arg("to"), follow = +arg("follow", chain === "base" ? 43200 : 7200);
const minEth = BigInt(Math.round(+arg("mineth", "0.5") * 1e18));
const ZERO = "0x0000000000000000000000000000000000000000";
const created = [];
for (const [f, kind] of Object.entries(c.factories)) {
  const topic = kind === "aerodrome" ? AERO_POOL_CREATED : PAIR_CREATED;
  const ls = await logs(c.url, { address: f, topics: [topic] }, from, to, c.span, { pause: 300 });
  for (const l of ls) {
    const t0 = word(l.topics[1]), t1 = word(l.topics[2]);
    if (kind === "aerodrome" && l.topics[3] !== "0x" + "0".repeat(64)) continue;   // stable=false only (volatile)
    const pair = kind === "aerodrome" ? word("0x" + l.data.slice(2, 66)) : word("0x" + l.data.slice(2, 66));
    if (t0 !== c.weth && t1 !== c.weth) continue;
    created.push({ pair, kind, token: t0 === c.weth ? t1 : t0, wethIs0: t0 === c.weth, block: parseInt(l.blockNumber, 16) });
  }
}
console.error(`${chain}: ${created.length} WETH pairs created in ${from}-${to}`);
for (const p of created) {
  try {
    const lt = await logs(c.url, { address: p.pair, topics: [TRANSFER] }, p.block, p.block + follow, c.span, { pause: 200 });
    const mint = lt.find((l) => word(l.topics[1]) === ZERO && word(l.topics[2]) !== ZERO);
    if (!mint) continue;
    const team = word(mint.topics[2]);
    const lpMint = BigInt(mint.data);
    const out = lt.filter((l) => word(l.topics[1]) === team);
    const toPair = out.filter((l) => word(l.topics[2]) === p.pair);
    const startBlock = parseInt(mint.blockNumber, 16);
    const rec = { chain, kind: p.kind, pair: p.pair, token: p.token, team, start: startBlock, lp_minted: lpMint.toString(),
      out: out.map((l) => ({ block: parseInt(l.blockNumber, 16), to: word(l.topics[2]), amount: BigInt(l.data).toString(), tx: l.transactionHash })) };
    const [r0a, r1a] = await reserves(c.url, p.pair, startBlock);
    rec.weth_at_start = String(p.wethIs0 ? r0a : r1a);
    if ((p.wethIs0 ? r0a : r1a) < minEth) continue;
    if (toPair.length) {
      const R = parseInt(toPair[0].blockNumber, 16);
      const [b0, b1] = await reserves(c.url, p.pair, R - 1), [a0, a1] = await reserves(c.url, p.pair, R);
      rec.rug = { block: R, tx: toPair[0].transactionHash, weth_before: String(p.wethIs0 ? b0 : b1), weth_after: String(p.wethIs0 ? a0 : a1) };
    }
    console.log(JSON.stringify(rec));
  } catch (e) { console.error(p.pair, String(e.message).slice(0, 120)); }
  await sleep(150);
}
