/**
 * The demo's Base Sepolia side (real chain, the official Uniswap V2 factory and
 * router). Idempotent: every step records its transaction in docs/demo-evm.json
 * and is skipped when already done.
 *
 *   node demo_evm.mjs setup     fund the teams, deploy RUGDEMO (team) and HOLDDEMO (team2),
 *                               add liquidity on Uniswap V2 (LP to the team), send tokens to holders
 *   node demo_evm.mjs rug       the team pulls RUGDEMO's liquidity (removeLiquidityETH)
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
  for (const role of ["team", "team2"]) {
    await step(`fund_${role}`, async () => sent(await wal("deployer").sendTransaction({ to: A(role).address, value: parseEther("0.008") })));
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
  // a holder that buys only in the rug block or after holds nothing at R-1: holder5 receives tokens now
  await step("send_RUGDEMO_holder5_after_rug", async () => sent(await wal("team").writeContract({ address: s.token, abi: erc20, functionName: "transfer", args: [A("holder5").address, parseEther("10000")] })));
}

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
else await status();
