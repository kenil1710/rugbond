/**
 * The demo on RugBondDemo + LaunchGateDemo with a real token and a real Uniswap V2
 * pair on Base Sepolia (test/demo_evm.mjs). Every path: a rug, claims (one through
 * a committed beneficiary), every refusal, unclaimed GEN to the victim fund, a held
 * bond returned to its team, a refused bond credited and withdrawn, LaunchGate
 * answers including a copycat bond. Each payout is proved by its arrival (the
 * transaction FINALIZED, its value message delivered, the balance delta at the
 * recipient) and the demo registry's balance ends at 0. Writes docs/demo-run.json;
 * resumable (finished steps are kept).
 *   node demo_run.mjs
 */
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { client, deployments, balanceOf, finalized, payoutDelivered, gen } from "../tools/lib/rb.mjs";
import { accounts } from "./harness.mjs";

const OUT = new URL("../docs/demo-run.json", import.meta.url);
const EVM = new URL("../docs/demo-evm.json", import.meta.url);
const dep = deployments().contracts;
const ADDR = dep.RugBondDemo.address, GATE = dep.LaunchGateDemo.address;
const doc = existsSync(OUT) ? JSON.parse(readFileSync(OUT)) : { contract: ADDR, gate: GATE, steps: [], bonds: {} };
if (doc.contract !== ADDR) throw new Error("docs/demo-run.json belongs to another demo registry; move it aside first");
const save = () => writeFileSync(OUT, JSON.stringify(doc, (k, v) => (typeof v === "bigint" ? v.toString() : v), 1) + "\n");
const acc = accounts();
const ad = (r) => acc[r].address.toLowerCase();
const cl = (role, address = ADDR) => client({ role, address });
const GEN = 10n ** 18n;
const evm = () => JSON.parse(readFileSync(EVM, "utf8"));
const runEvm = (cmd) => execFileSync("node", [new URL("./demo_evm.mjs", import.meta.url).pathname, cmd], { stdio: ["ignore", "pipe", "inherit"] }).toString();
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const done = (id) => doc.steps.find((s) => s.id === id && s.ok);

async function step(id, what, fn) {
  if (done(id)) { console.log("skip", id); return done(id); }
  console.log("\n==", id, what);
  const r = await fn();
  const rec = { id, what, ...r, at: new Date().toISOString() };
  doc.steps = doc.steps.filter((s) => s.id !== id);
  doc.steps.push(rec);
  save();
  console.log("  ->", rec.ok ? "ok" : "FAIL", JSON.stringify({ ...rec, what: undefined }).slice(0, 500));
  if (!rec.ok) throw new Error("step failed: " + id);
  return rec;
}

/** A write whose payout (if any) is verified: finalized, delivered, balance delta at the recipient and at the contract. */
async function paying(c, fn, args, payee, amountOf) {
  const before = await balanceOf(payee);
  const cbefore = await balanceOf(ADDR);
  const w = await c.write(fn, args, { payee, simulate: false });
  if (!w.ok) return { ok: false, tx: w.hash, status: w.status, reason: w.reason };
  const tx = await finalized(c.read, w.hash);
  const ret = w.returned && typeof w.returned === "object" ? w.returned : null;
  const amount = BigInt(amountOf(ret) ?? "0");
  const out = { ok: tx?.statusName === "FINALIZED", tx: w.hash, status: tx?.statusName, returned: ret };
  if (amount > 0n) {
    const d = payoutDelivered(tx, payee, amount);
    let after = await balanceOf(payee);
    for (let i = 0; i < 6 && after - before < amount; i++) { await sleep(10000); after = await balanceOf(payee); }
    const cafter = await balanceOf(ADDR);
    const sender = c.me.toLowerCase() === payee.toLowerCase();
    const fee = BigInt(d.netFee ?? 0);
    out.payout = { to: payee, amount: String(amount), delivered: d.ok, why: d.why, recipient_delta: String(after - before),
      contract_delta: String(cafter - cbefore), self_paid: sender, fee: String(fee),
      arrived: sender ? after - before >= amount - (fee > 0n ? fee : 0n) : after - before === amount };
    out.ok = out.ok && d.ok && out.payout.arrived && cafter - cbefore === -amount;
  }
  return out;
}

/** A call that must be refused with `why` and change nothing. */
async function refused(c, fn, args, why, payee = null) {
  const before = await c.view("get_stats", []);
  const w = await c.write(fn, args, payee ? { payee, simulate: false } : {});
  const after = await c.view("get_stats", []);
  const reason = String(w.reason ?? "");
  return { ok: !w.ok && reason.includes(why) && JSON.stringify(before.counts) === JSON.stringify(after.counts), tx: w.hash, status: w.status, reason };
}

async function checkUntil(bid, want, maxMin = 420) {
  const k = cl("keeper");
  const t0 = Date.now();
  const checks = [];
  for (;;) {
    const b = await k.view("get_bond", [bid, Math.floor(Date.now() / 1000)]);
    if (b.status !== "ACTIVE") return { ok: want.includes(b.status), status: b.status, checks, rug_block: b.rug_block, cursor: b.cursor };
    const w = await k.write("check", [bid]);
    checks.push({ tx: w.hash, ok: w.ok, reason: (w.reason ?? "").slice(0, 80), result: w.returned?.result ?? "" });
    console.log("   check", bid, w.ok ? w.returned?.result ?? "ok" : "refused " + (w.reason ?? "").slice(0, 60));
    if (Date.now() - t0 > maxMin * 60000) return { ok: false, status: b.status, checks };
    if (!w.ok || w.returned?.result === "SCANNED" || w.returned?.result === "PENDING") await sleep(w.ok ? 60000 : 180000);
  }
}

const e0 = evm();
const RUG = e0.RUGDEMO, HOLD = e0.HOLDDEMO;
const ROUTER_BSEP = "0x1689e7b1f10000ae47ebfe339a4f69decd19f602";
const team = cl("team"), team2 = cl("team2");
const now = () => Math.floor(Date.now() / 1000);

// 0. a refused bond (victim fund = the team): credited, then withdrawn
await step("refused_create", "create_bond naming the team as victim fund is refused and credited", async () => {
  const w = await team.write("create_bond", ["bad", "base-sepolia", RUG.token, RUG.pair, JSON.stringify([RUG.team]), RUG.lp_minted, 1, now() + 3600, 600,
    ad("team"), JSON.stringify([]), "0"], { value: GEN / 100n });
  const credit = await team.view("get_credit", [team.me]);
  return { ok: w.ok && w.returned?.ok === false && w.returned?.reason === "VICTIM_FUND_IS_TEAM" && BigInt(credit.credit) === GEN / 100n, tx: w.hash, returned: w.returned, credit: credit.credit };
});
await step("withdraw_credit", "withdraw_credit pays the credited GEN back to the team", () => paying(team, "withdraw_credit", [], team.me, (r) => r?.withdrawn));

// 1. two bonds open at the same start block, after the tokens were distributed
const start = doc.start_block ?? Number(runEvm("head").trim());
doc.start_block = start; save();
async function open(key, c, name, t, endIn, value, extra) {
  return step("open_" + key, "open bond " + name, async () => {
    const w = await c.write("create_bond", [name, "base-sepolia", t.token, t.pair, JSON.stringify([t.team]), t.lp_minted, start, now() + endIn, 600,
      ad("victimfund"), JSON.stringify(extra), "0"], { value });
    const tx = w.hash ? await finalized(c.read, w.hash) : null;
    const pg = await c.view("bonds_by_team", [c.me, 0, 50, now()]);
    const b = pg.items.find((x) => x.name === name);
    doc.bonds[key] = b?.bond_id; save();
    return { ok: w.ok && tx?.statusName === "FINALIZED" && !!b, tx: w.hash, bond_id: b?.bond_id, start_block: start, end_time: b?.end_time, amount: b?.amount };
  });
}
await open("A", team, "RUGDEMO liquidity bond", RUG, 10 * 3600, 2n * GEN, [ad("stranger"), ROUTER_BSEP]);
await open("B", team2, "HOLDDEMO liquidity bond", HOLD, 20 * 60, GEN, [ad("stranger"), ROUTER_BSEP]);
const A = doc.bonds.A, B = doc.bonds.B;

// 2. a copycat bond on RUGDEMO by a stranger (its own bond, its own victim fund): never read for the real team
await step("open_copycat", "a stranger bonds RUGDEMO too (copycat)", async () => {
  const s = cl("stranger");
  const w = await s.write("create_bond", ["RUGDEMO copycat", "base-sepolia", RUG.token, RUG.pair, JSON.stringify([RUG.team]), "1", start, now() + 1800, 600,
    ad("victimfund"), JSON.stringify([]), "0"], { value: GEN / 100n });
  const pg = await s.view("bonds_by_team", [s.me, 0, 50, now()]);
  doc.bonds.C = pg.items.find((x) => x.name === "RUGDEMO copycat")?.bond_id; save();
  return { ok: w.ok && !!doc.bonds.C, tx: w.hash, bond_id: doc.bonds.C };
});

// 4. on Base Sepolia: after the start, the team hands tokens to a fresh wallet and the deployer buys; then the rug
await step("evm_after_start", "Base Sepolia: team -> holder5 transfer and a buy by the deployer, after the start block", async () => {
  runEvm("after_start");
  return { ok: true, ...evm().RUGDEMO.after_start };
});
await step("beneficiary", "holder1 commits a beneficiary (once)", async () => {
  const w = await cl("holder1").write("commit_beneficiary", [A, ad("e2e")]);
  return { ok: w.ok && w.returned?.beneficiary === ad("e2e"), tx: w.hash, returned: w.returned };
});
await step("evm_rug", "Base Sepolia: the team removes RUGDEMO's liquidity (removeLiquidityETH)", async () => {
  runEvm("rug");
  const r = evm().RUGDEMO;
  return { ok: !!r.rug_block, rug_block: r.rug_block, rug_tx: r.rug_tx };
});

// 5a. the first check of A: the start block read, the pair checked. Base Sepolia's finalized head trails its tip
// by about 4.4 hours, so this waits; the rug (minutes after the start) is usually still past the finalized head,
// and LaunchGate then answers ACTIVE_HELD_SO_FAR from that read
await step("first_check_A", "the first rug check of bond A reads the start block", async () => {
  const k = cl("keeper");
  for (let i = 0; i < 400; i++) {                 // Base Sepolia's finalized head trails the tip by about 4.4 hours
    const cur = await k.view("get_bond", [A, now()]);
    if (cur.n_checks > 0) {
      const c1 = await k.view("get_check", [1]);
      return { ok: ["SCANNED", "HELD", "RUGGED"].includes(c1.result), check: c1, status: cur.status };
    }
    const w = await k.write("check", [A]);
    if (w.ok) return { ok: ["SCANNED", "HELD", "RUGGED"].includes(w.returned?.result), tx: w.hash, returned: w.returned };
    console.log("   ", (w.reason ?? "").slice(0, 60), "- waiting for finality");
    await sleep(90000);
  }
  return { ok: false };
});
// 5. rug checks until RUGGED
await step("rugged_A", "rug checks on bond A until RUGGED at the rug block", async () => {
  const r = await checkUntil(A, ["RUGGED"]);
  const b = await team.view("get_bond", [A, now()]);
  return { ...r, ok: r.ok && b.rug_block === evm().RUGDEMO.rug_block, rug_block: b.rug_block, rug_txs: b.rug?.txs, denominator: b.denominator, claim_deadline: b.claim_deadline };
});
const g = cl("stranger", GATE);
await step("gate_rugged", "LaunchGate: RUGGED_PAYING", async () => {
  const a = await g.view("check_for", [RUG.token, A]);
  return { ok: a.state === "RUGGED_PAYING" && a.safe === false, check_for: a };
});

// 6. claims and refusals
await step("claim_holder1", "holder1 claims; paid to its committed beneficiary", () => paying(cl("holder1"), "claim", [A], ad("e2e"), (r) => r?.share));
await step("claim_holder2", "holder2 claims", () => paying(cl("holder2"), "claim", [A], ad("holder2"), (r) => r?.share));
await step("claim_holder3", "holder3 claims", () => paying(cl("holder3"), "claim", [A], ad("holder3"), (r) => r?.share));
await step("refuse_double", "holder2 claims again: ALREADY_CLAIMED", () => refused(cl("holder2"), "claim", [A], "ALREADY_CLAIMED", ad("holder2")));
await step("refuse_excluded", "the excluded stranger: EXCLUDED_ADDRESS", () => refused(cl("stranger"), "claim", [A], "EXCLUDED_ADDRESS", ad("stranger")));
await step("refuse_team_funded", "holder5 got tokens from the team after the start: RECEIVED_FROM_EXCLUDED_ADDRESS", () =>
  refused(cl("holder5"), "claim", [A], "RECEIVED_FROM_EXCLUDED_ADDRESS", ad("holder5")));
await step("refuse_bought_after_start", "the deployer bought after the start: NO_BALANCE_AT_START_AND_R_MINUS_1", () =>
  refused(cl("deployer"), "claim", [A], "NO_BALANCE_AT_START_AND_R_MINUS_1", ad("deployer")));
await step("refuse_team", "the team: EXCLUDED_ADDRESS", () => refused(team, "claim", [A], "EXCLUDED_ADDRESS", ad("team")));
await step("refuse_wrong_bond", "holder1 claims on bond B (not rugged): BOND_IS_ACTIVE", () => refused(cl("holder1"), "claim", [B], "BOND_IS_", ad("holder1")));
await step("refuse_beneficiary_twice", "holder1 commits a second beneficiary: refused", () => refused(cl("holder1"), "commit_beneficiary", [A, ad("holder1")], "REFUSED"));

await step("gate_active", "LaunchGate before the rug is read: ACTIVE_HELD_SO_FAR (or RUGGED_PAYING if the first read already reached the rug)", async () => {
  const a = await g.view("check_for", [RUG.token, A]);
  if (a.state === "RUGGED_PAYING") return { ok: true, check_for: a, note: "the first read already reached the rug block" };
  const t = await g.view("is_safe_for", [RUG.token, ad("team")]);
  const wrong = await g.view("check_for", [HOLD.token, A]);
  const cop = await g.view("is_safe_for", [RUG.token, ad("stranger")]);
  return { ok: a.state === "ACTIVE_HELD_SO_FAR" && a.safe === true && t.safe === true && wrong.state === "NO_BOND" && cop.safe === false,
    check_for: a, is_safe_for: t, wrong_token: wrong, copycat_team: cop };
});
await step("gate_attest", "LaunchGate: attest(RUGDEMO, A) stored on chain", async () => {
  const w = await g.write("attest", [RUG.token, A]);
  return { ok: w.ok && ["ACTIVE_HELD_SO_FAR", "RUGGED_PAYING"].includes(w.returned?.state), tx: w.hash, returned: w.returned };
});

// 7. bond B holds: checks until HELD, settle returns the bond to team2
await step("held_B", "rug checks on bond B until HELD", () => checkUntil(B, ["HELD"]));
await step("gate_held", "LaunchGate: HELD_FINAL", async () => {
  const a = await g.view("check_for", [HOLD.token, B]);
  return { ok: a.state === "HELD_FINAL", check_for: a };
});
await step("settle_B", "settle B: the bond back to team2", () => paying(cl("keeper"), "settle", [B], ad("team2"), (r) => r?.amount));

// 8. after A's claim window: a late claim is refused; settle sends the unclaimed GEN to the victim fund
await step("wait_window_A", "wait for bond A's claim window to end", async () => {
  const b = await team.view("get_bond", [A, now()]);
  while (now() <= b.claim_deadline + 30) await sleep(20000);
  return { ok: true, claim_deadline: b.claim_deadline };
});
await step("refuse_late", "holder4 claims after the window: CLAIM_WINDOW_OVER", () => refused(cl("holder4"), "claim", [A], "CLAIM_WINDOW_OVER", ad("holder4")));
await step("settle_A", "settle A: what holders did not claim to the victim fund", () => paying(cl("keeper"), "settle", [A], ad("victimfund"), (r) => r?.amount));
await step("gate_closed", "LaunchGate: RUGGED_CLOSED", async () => {
  const a = await g.view("check_for", [RUG.token, A]);
  return { ok: a.state === "RUGGED_CLOSED", check_for: a };
});

// 9. the copycat: never read for the real team; it holds or is settled like any bond
await step("copycat_done", "the copycat bond is checked to a verdict and settled", async () => {
  const C = doc.bonds.C;
  const r = await checkUntil(C, ["HELD", "RUGGED"]);
  const b = await team.view("get_bond", [C, now()]);
  if (b.status === "RUGGED") while (now() <= b.claim_deadline + 30) await sleep(20000);
  const due = (await team.view("get_bond", [C, now()]));
  const payee = due.due === "RETURN" ? ad("stranger") : ad("victimfund");
  const p = await paying(cl("keeper"), "settle", [C], payee, (x) => x?.amount);
  return { ok: r.ok && p.ok, status: r.status, settle: p };
});

// 10. a live promise read recently: LaunchGate's ACTIVE_HELD_SO_FAR, then held and settled
await step("open_D", "team2 opens a second HOLDDEMO bond (ends in about an hour)", async () => {
  const head = Number(runEvm("head").trim());
  const name = "HOLDDEMO short bond " + head;
  const w = await team2.write("create_bond", [name, "base-sepolia", HOLD.token, HOLD.pair, JSON.stringify([HOLD.team]), HOLD.lp_minted, head, now() + 3600, 600,
    ad("victimfund"), JSON.stringify([ad("stranger"), ROUTER_BSEP]), "0"], { value: GEN / 2n });
  const pg = await team2.view("bonds_by_team", [team2.me, 0, 50, now()]);
  doc.bonds.D = pg.items.find((x) => x.name === name)?.bond_id; save();
  return { ok: w.ok && !!doc.bonds.D, tx: w.hash, bond_id: doc.bonds.D, start_block: head };
});
await step("check_D", "the first check of bond D (SCANNED while the promise runs)", async () => {
  const k = cl("keeper");
  for (let i = 0; i < 400; i++) {
    const w = await k.write("check", [doc.bonds.D]);
    if (w.ok) return { ok: w.returned?.result === "SCANNED", tx: w.hash, returned: w.returned };
    await sleep(90000);
  }
  return { ok: false };
});
await step("gate_active_D", "LaunchGate: check_for(HOLDDEMO, D) is ACTIVE_HELD_SO_FAR and safe; a copycat team and another token are not", async () => {
  const a = await g.view("check_for", [HOLD.token, doc.bonds.D]);
  const t = await g.view("is_safe_for", [HOLD.token, ad("team2")]);
  const wrong = await g.view("check_for", [RUG.token, doc.bonds.D]);
  const cop = await g.view("is_safe_for", [HOLD.token, ad("stranger")]);
  const w = await g.write("attest", [HOLD.token, doc.bonds.D]);
  return { ok: a.state === "ACTIVE_HELD_SO_FAR" && a.safe === true && t.safe === true && wrong.state === "NO_BOND" && cop.safe === false && w.returned?.state === "ACTIVE_HELD_SO_FAR",
    check_for: a, is_safe_for: t, wrong_token: wrong, copycat_team: cop, attest_tx: w.hash };
});
await step("held_D", "rug checks on bond D until HELD", () => checkUntil(doc.bonds.D, ["HELD"]));
await step("settle_D", "settle D: the bond back to team2", () => paying(cl("keeper"), "settle", [doc.bonds.D], ad("team2"), (r) => r?.amount));

await step("balance_zero_end", "the demo registry's balance is 0 at the end", async () => {
  const bal = await balanceOf(ADDR);
  const stats = await team.view("get_stats", []);
  return { ok: bal === 0n && stats.held === "0", eth_getBalance: String(bal), stats };
});
console.log("\ndemo done:", doc.steps.filter((s) => s.ok).length, "steps");
