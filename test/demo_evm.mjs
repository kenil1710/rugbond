/**
 * The demo's Base Sepolia side (real chain, the official Uniswap V2 factory and
 * router). Idempotent: every step records its transaction in docs/demo-evm.json
 * and is skipped when already done.
 *
 *   node demo_evm.mjs setup     fund the teams, deploy RUGDEMO (team) and HOLDDEMO (team2),
 *                               add liquidity on Uniswap V2 (LP to the team), send tokens to holders
 *   node demo_evm.mjs after_start  after the bond's start block: the team sends tokens to a fresh wallet, a zero-value
 *                               transfer to holder2 and 1 wei to holder3 (a dusting attempt), 4,000 tokens to holder1;
 *                               the deployer buys on the pool
 *   node demo_evm.mjs flood     team2 sends 1,100 LP transfers of 1 wei out of its HOLDDEMO position (5 transactions)
 *   node demo_evm.mjs rug       the team pulls RUGDEMO's liquidity (removeLiquidityETH)
 *   node demo_evm.mjs head      the latest block number
 *   node demo_evm.mjs status    balances and LP
 *
 * Keys come from test/.accounts.json (throwaway); only addresses are printed.
 */
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { createPublicClient, createWalletClient, http, parseEther, formatEther, parseAbi, getContractAddress } from "viem";
import { privateKeyToAccount } from "viem/accounts";
import { baseSepolia } from "viem/chains";
import { accounts } from "./harness.mjs";

const RPC = "https://base-sepolia-rpc.publicnode.com";
const ROUTER = "0x1689E7B1F10000AE47eBfE339a4f69dECd19F602";
const FACTORY = "0x7Ae58f10f7849cA6F5fB71b7f45CB416c9204b1e";
const WETH = "0x4200000000000000000000000000000000000006";
const out = new URL("../docs/demo-evm.json", import.meta.url);
const st = existsSync(out) ? JSON.parse(readFileSync(out, "utf8")) : { chain: "base-sepolia", router: ROUTER, factory: FACTORY, steps: {} };
const save = () => writeFileSync(out, JSON.stringify(st, (k, v) => (typeof v === "bigint" ? v.toString() : v), 1) + "\n");
const acc = accounts();
const A = (role) => privateKeyToAccount(acc[role].key);
const pub = createPublicClient({ chain: baseSepolia, transport: http(RPC) });
const wal = (role) => createWalletClient({ chain: baseSepolia, account: A(role), transport: http(RPC) });
const art = JSON.parse(readFileSync(new URL("../demo/out/DemoToken.sol/DemoToken.json", import.meta.url), "utf8"));
const erc20 = parseAbi(["function balanceOf(address) view returns (uint256)", "function transfer(address,uint256) returns (bool)",
  "function approve(address,uint256) returns (bool)", "function totalSupply() view returns (uint256)"]);
const router = parseAbi(["function addLiquidityETH(address,uint256,uint256,uint256,address,uint256) payable returns (uint256,uint256,uint256)",
  "function removeLiquidityETH(address,uint256,uint256,uint256,address,uint256) returns (uint256,uint256)"]);
const factory = parseAbi(["function getPair(address,address) view returns (address)"]);

async function step(name, fn) {
  if (st.steps[name]?.status === "success") { console.log(`  ${name}: done (${st.steps[name].tx ?? ""})`); return st.steps[name]; }
  const r = await fn();
  st.steps[name] = r;
  save();
  console.log(`  ${name}: ${r.status} ${r.tx ?? ""} ${r.block ? "block " + r.block : ""}`);
  if (r.status !== "success") throw new Error(name + " failed");
  return r;
}
async function sent(hash) {
  const rc = await pub.waitForTransactionReceipt({ hash, timeout: 180_000 });
  return { tx: hash, status: rc.status, block: Number(rc.blockNumber) };
}

async function setup() {
  const dep = A("deployer").address;
  const bal = await pub.getBalance({ address: dep });
  console.log("deployer", dep, formatEther(bal), "ETH");
  // the teams are topped up from the deployer only when they hold less than the demo needs; nothing else funds anything
  for (const [role, need] of [["team", "0.007"], ["team2", "0.0045"]]) {
    const have = await pub.getBalance({ address: A(role).address });
    if (have >= parseEther(need)) { console.log(`  ${role} holds ${formatEther(have)} ETH: no funding`); continue; }
    const gap = parseEther(need) - have;
    if (bal < gap + parseEther("0.002")) throw new Error(`Please send Base Sepolia ETH to ${dep}`);
    await step(`fund_${role}`, async () => sent(await wal("deployer").sendTransaction({ to: A(role).address, value: gap })));
  }
  for (const [role, sym, nm] of [["team", "RUGDEMO", "RugBond Demo Rug"], ["team2", "HOLDDEMO", "RugBond Demo Hold"]]) {
    const d = await step(`deploy_${sym}`, async () => {
      const w = wal(role);
      const hash = await w.deployContract({ abi: art.abi, bytecode: art.bytecode.object, args: [nm, sym, parseEther("1000000")] });
      const r = await sent(hash);
      const rc = await pub.getTransactionReceipt({ hash });
      return { ...r, address: rc.contractAddress.toLowerCase(), team: A(role).address.toLowerCase(), symbol: sym };
    });
    const token = d.address;
    await step(`approve_${sym}`, async () => sent(await wal(role).writeContract({ address: token, abi: erc20, functionName: "approve", args: [ROUTER, 2n ** 256n - 1n] })));
    const liq = await step(`liquidity_${sym}`, async () => {
      const dl = BigInt(Math.floor(Date.now() / 1000) + 1800);
      const hash = await wal(role).writeContract({ address: ROUTER, abi: router, functionName: "addLiquidityETH",
        args: [token, parseEther("500000"), 0n, 0n, A(role).address, dl], value: parseEther("0.003") });
      const r = await sent(hash);
      const pair = (await pub.readContract({ address: FACTORY, abi: factory, functionName: "getPair", args: [token, WETH] })).toLowerCase();
      const lp = await pub.readContract({ address: pair, abi: erc20, functionName: "balanceOf", args: [A(role).address], blockNumber: BigInt(r.block) });
      return { ...r, pair, lp: lp.toString() };
    });
    st[sym] = { token, pair: liq.pair, team: A(role).address.toLowerCase(), lp_minted: liq.lp, liquidity_block: liq.block };
    save();
    let i = 0;
    for (const h of ["holder1", "holder2", "holder3", "holder4"]) {
      i++;
      await step(`send_${sym}_${h}`, async () => sent(await wal(role).writeContract({ address: token, abi: erc20, functionName: "transfer",
        args: [A(h).address, parseEther(String(10000 * i))] })));
    }
    // an excluded wallet (listed in the bond's excluded addresses) and a contract holder (the other demo token's contract)
    await step(`send_${sym}_stranger`, async () => sent(await wal(role).writeContract({ address: token, abi: erc20, functionName: "transfer", args: [A("stranger").address, parseEther("5000")] })));
  }
  await step("send_RUGDEMO_contract_holder", async () => sent(await wal("team").writeContract({ address: st.RUGDEMO.token, abi: erc20, functionName: "transfer", args: [st.HOLDDEMO.token, parseEther("7000")] })));
  console.log(JSON.stringify({ RUGDEMO: st.RUGDEMO, HOLDDEMO: st.HOLDDEMO }, null, 1));
}

async function rug() {
  const s = st.RUGDEMO;
  const lp = await pub.readContract({ address: s.pair, abi: erc20, functionName: "balanceOf", args: [s.team] });
  await step("approve_lp_RUGDEMO", async () => sent(await wal("team").writeContract({ address: s.pair, abi: erc20, functionName: "approve", args: [ROUTER, lp] })));
  const r = await step("rug_RUGDEMO", async () => {
    const dl = BigInt(Math.floor(Date.now() / 1000) + 1800);
    return sent(await wal("team").writeContract({ address: ROUTER, abi: router, functionName: "removeLiquidityETH", args: [s.token, lp, 0n, 0n, s.team, dl] }));
  });
  s.rug_block = r.block; s.rug_tx = r.tx;
  save();
}

/** After the bond's start block: the team hands tokens to a fresh wallet (holder5), tries to dust holder2 (a zero-value
 *  transfer) and holder3 (1 wei), tops holder1 up with 4,000 tokens, and the deployer buys on the pool. */
async function afterStart() {
  const s = st.RUGDEMO;
  const send = (name, to, amount) => step(name, async () => sent(await wal("team").writeContract({ address: s.token, abi: erc20, functionName: "transfer", args: [A(to).address, amount] })));
  const r1 = await send("team_sends_holder5_after_start", "holder5", parseEther("15000"));
  const d0 = await send("team_dusts_holder2_zero_value", "holder2", 0n);
  const d1 = await send("team_dusts_holder3_one_wei", "holder3", 1n);
  const d2 = await send("team_sends_holder1_4000_after_start", "holder1", parseEther("4000"));
  const swap = parseAbi(["function swapExactETHForTokens(uint256,address[],address,uint256) payable returns (uint256[])"]);
  const r2 = await step("deployer_buys_after_start", async () => {
    const dl = BigInt(Math.floor(Date.now() / 1000) + 1800);
    return sent(await wal("deployer").writeContract({ address: ROUTER, abi: swap, functionName: "swapExactETHForTokens",
      args: [0n, [WETH, s.token], A("deployer").address, dl], value: parseEther("0.0002") }));
  });
  s.after_start = { holder5: r1.block, dust_zero_holder2: d0.block, dust_one_wei_holder3: d1.block, holder1_4000: d2.block, deployer_buy: r2.block,
    txs: { holder5: r1.tx, dust_zero_holder2: d0.tx, dust_one_wei_holder3: d1.tx, holder1_4000: d2.tx, deployer_buy: r2.tx } };
  save();
}

/** The flood: 1,100 LP Transfer logs out of team2 (the HOLDDEMO LP holder), 1 wei each, in 5 transactions of 220. */
async function flood() {
  const s = st.HOLDDEMO;
  const fa = JSON.parse(readFileSync(new URL("../demo/out/Flood.sol/Flood.json", import.meta.url), "utf8"));
  const fabi = parseAbi(["function run(address token, address to, uint256 value, uint256 n)"]);
  const d = await step("deploy_flood", async () => {
    const hash = await wal("team2").deployContract({ abi: fa.abi, bytecode: fa.bytecode.object, args: [] });
    const r = await sent(hash);
    return { ...r, address: (await pub.getTransactionReceipt({ hash })).contractAddress.toLowerCase() };
  });
  await step("approve_flood_lp", async () => sent(await wal("team2").writeContract({ address: s.pair, abi: erc20, functionName: "approve", args: [d.address, 1100n] })));
  const runs = [];
  for (let i = 0; i < 5; i++) {
    runs.push(await step(`flood_${i}`, async () => {
      const hash = await wal("team2").writeContract({ address: d.address, abi: fabi, functionName: "run", args: [s.pair, A("stranger").address, 1n, 220n] });
      const r = await sent(hash);
      const rc = await pub.getTransactionReceipt({ hash });
      return { ...r, transfer_logs: rc.logs.filter((l) => l.address.toLowerCase() === s.pair && l.topics[0] === "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef").length };
    }));
  }
  const lp = await pub.readContract({ address: s.pair, abi: erc20, functionName: "balanceOf", args: [s.team] });
  s.flood = { contract: d.address, to: A("stranger").address.toLowerCase(), value_each: "1", transfers: runs.reduce((n, r) => n + r.transfer_logs, 0),
    txs: runs.map((r) => r.tx), blocks: runs.map((r) => r.block), lp_after: lp.toString() };
  save();
  console.log(JSON.stringify(s.flood));
}

/** The e2e run's own token: deployed by the team, liquidity added, tokens sent to the e2e wallet (and holder1) before the bond. */
async function e2eSetup(wallet, key = "E2EDEMO") {
  const d = await step(`deploy_${key}`, async () => {
    const hash = await wal("team").deployContract({ abi: art.abi, bytecode: art.bytecode.object, args: ["RugBond " + key, key, parseEther("1000000")] });
    const r = await sent(hash);
    return { ...r, address: (await pub.getTransactionReceipt({ hash })).contractAddress.toLowerCase() };
  });
  await step(`approve_${key}`, async () => sent(await wal("team").writeContract({ address: d.address, abi: erc20, functionName: "approve", args: [ROUTER, 2n ** 256n - 1n] })));
  const liq = await step(`liquidity_${key}`, async () => {
    const dl = BigInt(Math.floor(Date.now() / 1000) + 1800);
    const r = await sent(await wal("team").writeContract({ address: ROUTER, abi: router, functionName: "addLiquidityETH",
      args: [d.address, parseEther("500000"), 0n, 0n, A("team").address, dl], value: parseEther("0.002") }));
    const pair = (await pub.readContract({ address: FACTORY, abi: factory, functionName: "getPair", args: [d.address, WETH] })).toLowerCase();
    const lp = await pub.readContract({ address: pair, abi: erc20, functionName: "balanceOf", args: [A("team").address], blockNumber: BigInt(r.block) });
    return { ...r, pair, lp: lp.toString() };
  });
  await step(`send_${key}_wallet`, async () => sent(await wal("team").writeContract({ address: d.address, abi: erc20, functionName: "transfer", args: [wallet, parseEther("20000")] })));
  await step(`send_${key}_holder1`, async () => sent(await wal("team").writeContract({ address: d.address, abi: erc20, functionName: "transfer", args: [A("holder1").address, parseEther("30000")] })));
  st[key] = { token: d.address, pair: liq.pair, team: A("team").address.toLowerCase(), lp_minted: liq.lp, wallet: wallet.toLowerCase() };
  save();
  console.log(JSON.stringify(st[key]));
}

async function e2eRug(key = "E2EDEMO") {
  const s = st[key];
  const lp = await pub.readContract({ address: s.pair, abi: erc20, functionName: "balanceOf", args: [s.team] });
  await step(`approve_lp_${key}`, async () => sent(await wal("team").writeContract({ address: s.pair, abi: erc20, functionName: "approve", args: [ROUTER, lp] })));
  const r = await step(`rug_${key}`, async () => {
    const dl = BigInt(Math.floor(Date.now() / 1000) + 1800);
    return sent(await wal("team").writeContract({ address: ROUTER, abi: router, functionName: "removeLiquidityETH", args: [s.token, lp, 0n, 0n, s.team, dl] }));
  });
  s.rug_block = r.block; s.rug_tx = r.tx;
  save();
  console.log(JSON.stringify(s));
}

async function head() { console.log(String(await pub.getBlockNumber())); }

async function status() {
  for (const sym of ["RUGDEMO", "HOLDDEMO"]) {
    const s = st[sym];
    if (!s) continue;
    const lp = await pub.readContract({ address: s.pair, abi: erc20, functionName: "balanceOf", args: [s.team] });
    console.log(sym, s.token, "pair", s.pair, "team LP", formatEther(lp));
  }
}

const cmd = process.argv[2] ?? "status";
if (cmd === "setup") await setup();
else if (cmd === "rug") await rug();
else if (cmd === "after_start") await afterStart();
else if (cmd === "flood") await flood();
else if (cmd === "head") await head();
else if (cmd === "e2e_setup") await e2eSetup(process.argv[3], process.argv[4]);
else if (cmd === "e2e_rug") await e2eRug(process.argv[3]);
else await status();
