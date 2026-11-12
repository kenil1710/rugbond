/**
 * The demo on RugBondDemo + LaunchGateDemo with a real token and a real Uniswap V2
 * pair on Base Sepolia (test/demo_evm.mjs). Every path: a rug, claims (one through
 * a committed beneficiary), a dusting attempt by the team (a zero-value and a 1 wei
 * transfer change nothing; a real team transfer is subtracted), every refusal,
 * no bonus for the claimants (the unclaimed part of a bond goes to the registry's
 * fund in one settle), a bond nobody claimed sent to the registry's fund, a flood of 1,100 LP transfers out scanned
 * across checks to HELD, a held bond returned to its team, a refused bond credited
 * and withdrawn, LaunchGate answers including a copycat bond. Each payout is proved by its arrival (the
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
// the first pass checked the balance before the e2e run's bonds were settled; the final check is balance_zero_end
doc.steps = doc.steps.filter((s) => s.id !== "balance_zero");
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
const FUND = (await team.view("get_config", [])).fund;
const E18 = 10n ** 18n;
const HOLD_FLOOR = ((BigInt(HOLD.lp_minted) * 9n) / 10n).toString();      // HOLDDEMO promises 90% of its LP

/** A write that pays nobody (or must not): finalized, and the registry's balance unchanged. */
async function plain(c, fn, args) {
  const cbefore = await balanceOf(ADDR);
  const w = await c.write(fn, args);
  if (!w.ok) return { ok: false, tx: w.hash, status: w.status, reason: w.reason };
  const tx = await finalized(c.read, w.hash);
  const cafter = await balanceOf(ADDR);
  return { ok: tx?.statusName === "FINALIZED" && cafter === cbefore, tx: w.hash, status: tx?.statusName, returned: w.returned, contract_delta: String(cafter - cbefore) };
}

/** What a bond needs after its verdict and window: one settle, its payout verified. */
async function closeOut(bid) {
  const k = cl("keeper");
  const out = [];
  for (let i = 0; i < 6; i++) {
    const b = await k.view("get_bond", [bid, now()]);
    if (["CLOSED", "RETURNED", "UNRESOLVED"].includes(b.status)) return { ok: out.every((x) => x.ok), status: b.status, actions: out };
    if (b.due) { const to = b.due === "RETURN" ? b.team : b.fund; out.push({ action: "settle -> " + (b.due === "RETURN" ? "team" : "registry fund"), ...(await paying(k, "settle", [bid], to, (r) => r?.amount)) }); continue; }
    return { ok: false, status: b.status, actions: out, why: "nothing due" };
  }
  return { ok: false, actions: out, why: "did not close" };
}

// 0. a refused bond (a claim window below the registry's minimum): credited, then withdrawn
await step("refused_create", "create_bond with a 10 s claim window is refused and its value credited", async () => {
  const w = await team.write("create_bond", ["bad", "base-sepolia", RUG.token, RUG.pair, JSON.stringify([RUG.team]), RUG.lp_minted, 1, now() + 3600, 10,
    JSON.stringify([]), "0"], { value: GEN / 100n });
  const credit = await team.view("get_credit", [team.me]);
  return { ok: w.ok && w.returned?.ok === false && w.returned?.reason === "CLAIM_WINDOW_INVALID" && BigInt(credit.credit) === GEN / 100n, tx: w.hash, returned: w.returned, credit: credit.credit };
});
await step("withdraw_credit", "withdraw_credit pays the credited GEN back to the team", () => paying(team, "withdraw_credit", [], team.me, (r) => r?.withdrawn));
await step("fund_is_the_registrys", "the fund is the registry's (its constructor argument), not a bond term: get_config.fund", async () => {
  const cfg = await team.view("get_config", []);
  return { ok: cfg.fund === ad("fund") && dep.RugBondDemo.constructor_args[1] === cfg.fund && cfg.fund !== ad("team") && cfg.fund !== ad("team2"),
    fund: cfg.fund, constructor_args: dep.RugBondDemo.constructor_args };
});

// 1. two bonds open at the same start block, after the tokens were distributed
const start = doc.start_block ?? Number(runEvm("head").trim());
doc.start_block = start; save();
async function open(key, c, name, t, minLp, endIn, value, extra, window = 600) {
  return step("open_" + key, "open bond " + name, async () => {
    const w = await c.write("create_bond", [name, "base-sepolia", t.token, t.pair, JSON.stringify([t.team]), minLp, start, now() + endIn, window,
      JSON.stringify(extra), "0"], { value });
    const tx = w.hash ? await finalized(c.read, w.hash) : null;
    const pg = await c.view("bonds_by_team", [c.me, 0, 50, now()]);
    const b = pg.items.find((x) => x.name === name);
    doc.bonds[key] = b?.bond_id; save();
    return { ok: w.ok && tx?.statusName === "FINALIZED" && !!b && !("victim_fund" in b) && b.fund === FUND, tx: w.hash, bond_id: b?.bond_id, start_block: start,
      end_time: b?.end_time, amount: b?.amount, min_lp: b?.min_lp, fund: b?.fund };
  });
}
await open("A", team, "RUGDEMO liquidity bond", RUG, RUG.lp_minted, 10 * 3600, 2n * GEN, [ad("stranger"), ROUTER_BSEP], 1200);
await open("B", team2, "HOLDDEMO liquidity bond", HOLD, HOLD_FLOOR, 45 * 60, GEN, [ad("stranger"), ROUTER_BSEP]);
const A = doc.bonds.A, B = doc.bonds.B;

// 2. a copycat bond on RUGDEMO by a stranger: never read for the real team; nobody will claim on it
await step("open_copycat", "a stranger bonds RUGDEMO too (copycat)", async () => {
  const s = cl("stranger");
  const w = await s.write("create_bond", ["RUGDEMO copycat", "base-sepolia", RUG.token, RUG.pair, JSON.stringify([RUG.team]), "1", start, now() + 1800, 600,
    JSON.stringify([]), "0"], { value: GEN / 100n });
  const pg = await s.view("bonds_by_team", [s.me, 0, 50, now()]);
  doc.bonds.C = pg.items.find((x) => x.name === "RUGDEMO copycat")?.bond_id; save();
  return { ok: w.ok && !!doc.bonds.C, tx: w.hash, bond_id: doc.bonds.C };
});

// 3. on Base Sepolia, after the start: the team hands tokens to a fresh wallet, dusts two holders, tops one up; the
//    deployer buys; team2 floods its LP position with 1,100 transfers out; then the team pulls RUGDEMO's liquidity
await step("evm_after_start", "Base Sepolia, after the start block: team -> holder5 15,000; team -> holder2 a zero-value transfer; team -> holder3 1 wei; team -> holder1 4,000; a buy by the deployer", async () => {
  runEvm("after_start");
  return { ok: true, ...evm().RUGDEMO.after_start };
});
await step("evm_flood", "Base Sepolia: team2 sends 1,100 LP transfers of 1 wei out of its HOLDDEMO position", async () => {
  runEvm("flood");
  const f = evm().HOLDDEMO.flood;
  return { ok: f.transfers === 1100, ...f };
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

// 4. the first check of A waits for Base Sepolia's finalized head to pass the start block
await step("first_check_A", "the first rug check of bond A reads the start block", async () => {
  const k = cl("keeper");
  for (let i = 0; i < 400; i++) {
    const cur = await k.view("get_bond", [A, now()]);
    if (cur.n_checks > 0) {
      const cs = await k.view("list_checks", [A, 0, 1]);
      return { ok: ["SCANNED", "HELD", "RUGGED", "PENDING"].includes(cs.items[0]?.result), check: cs.items[0], status: cur.status };
    }
    const w = await k.write("check", [A]);
    if (w.ok) return { ok: ["SCANNED", "HELD", "RUGGED", "PENDING"].includes(w.returned?.result), tx: w.hash, returned: w.returned };
    console.log("   ", (w.reason ?? "").slice(0, 60), "- waiting for finality");
    await sleep(90000);
  }
  return { ok: false };
});
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

// 5. claims: the team's transfers cost exactly what they carried
const claimStep = (id, what, role, payee, want) => step(id, what, async () => {
  const p = await paying(cl(role), "claim", [A], payee, (r) => r?.share);
  const r = p.returned ?? {};
  return { ...p, ok: p.ok && r.from_team === want.from_team && r.balance === want.balance, expected: want };
});
await claimStep("claim_holder1", "holder1 claims: held 10,000 at the start, the team sent it 4,000 after: paid on 6,000, to its committed beneficiary", "holder1", ad("e2e"),
  { from_team: (4000n * E18).toString(), balance: (6000n * E18).toString() });
await claimStep("claim_holder2", "holder2 claims: the team's zero-value transfer changed nothing (paid on all 20,000)", "holder2", ad("holder2"),
  { from_team: "0", balance: (20000n * E18).toString() });
await claimStep("claim_holder3", "holder3 claims: the team's 1 wei transfer cost 1 wei (paid on 30,000 minus 1 wei)", "holder3", ad("holder3"),
  { from_team: "1", balance: (30000n * E18 - 1n).toString() });
await step("refuse_double", "holder2 claims again: ALREADY_CLAIMED", () => refused(cl("holder2"), "claim", [A], "ALREADY_CLAIMED", ad("holder2")));
await step("refuse_excluded", "the excluded stranger: EXCLUDED_ADDRESS", () => refused(cl("stranger"), "claim", [A], "EXCLUDED_ADDRESS", ad("stranger")));
await step("refuse_team_funded", "holder5, a fresh wallet the team funded after the start: NO_BALANCE_AT_START_AND_R_MINUS_1", () =>
  refused(cl("holder5"), "claim", [A], "NO_BALANCE_AT_START_AND_R_MINUS_1", ad("holder5")));
await step("refuse_bought_after_start", "the deployer bought after the start: NO_BALANCE_AT_START_AND_R_MINUS_1", () =>
  refused(cl("deployer"), "claim", [A], "NO_BALANCE_AT_START_AND_R_MINUS_1", ad("deployer")));
await step("refuse_team", "the team: EXCLUDED_ADDRESS", () => refused(team, "claim", [A], "EXCLUDED_ADDRESS", ad("team")));
await step("refuse_wrong_bond", "holder1 claims on bond B (not rugged): BOND_IS_ACTIVE", () => refused(cl("holder1"), "claim", [B], "BOND_IS_", ad("holder1")));
await step("refuse_beneficiary_twice", "holder1 commits a second beneficiary: refused", () => refused(cl("holder1"), "commit_beneficiary", [A, ad("holder1")], "REFUSED"));


await step("gate_active", "LaunchGate on bond A: RUGGED_PAYING once the rug is read; the real team is not safe, a copycat team neither", async () => {
  const a = await g.view("check_for", [RUG.token, A]);
  const t = await g.view("is_safe_for", [RUG.token, ad("team")]);
  const wrong = await g.view("check_for", [HOLD.token, A]);
  return { ok: a.state === "RUGGED_PAYING" && t.safe === false && wrong.state === "NO_BOND", check_for: a, is_safe_for: t, wrong_token: wrong };
});
await step("gate_attest", "LaunchGate: attest(RUGDEMO, A) stored on chain", async () => {
  const w = await g.write("attest", [RUG.token, A]);
  return { ok: w.ok && ["RUGGED_PAYING", "RUGGED_CLOSED"].includes(w.returned?.state), tx: w.hash, returned: w.returned };
});

// 6. bond B: 1,100 LP transfers out of its holder; the scan works through them across checks and reaches HELD
await step("held_B", "rug checks on bond B (flooded with 1,100 LP transfers out) until HELD", async () => {
  const r = await checkUntil(B, ["HELD"]);
  const cs = [];
  for (let off = 0; off >= 0;) { const pg = await team.view("list_checks", [B, off, 50]); cs.push(...pg.items); off = pg.next_offset; }
  const logs = cs.reduce((n, c) => n + c.n_logs, 0);
  const b = await team.view("get_bond", [B, now()]);
  return { ...r, ok: r.ok && logs === 1100 && cs.filter((c) => c.n_logs > 0).length >= 3 && cs.every((c) => c.result !== "RUGGED"),
    lp_transfers_scanned: logs, checks_with_transfers: cs.filter((c) => c.n_logs > 0).map((c) => ({ check_id: c.check_id, a: c.a, b: c.b, n_logs: c.n_logs, probes: c.probes.length, result: c.result })),
    lp_low: b.lp_low, min_lp: b.min_lp, lp_minted: HOLD.lp_minted };
});
await step("gate_held", "LaunchGate: HELD_FINAL", async () => {
  const a = await g.view("check_for", [HOLD.token, B]);
  return { ok: a.state === "HELD_FINAL", check_for: a };
});
await step("settle_B", "settle B: the bond back to team2", () => paying(cl("keeper"), "settle", [B], ad("team2"), (r) => r?.amount));

// 7. after A's claim window: a late claim is refused; what nobody claimed goes to the registry's fund, no claimant gets more
await step("wait_window_A", "wait for bond A's claim window to end", async () => {
  const b = await team.view("get_bond", [A, now()]);
  while (now() <= b.claim_deadline + 30) await sleep(20000);
  return { ok: true, claim_deadline: b.claim_deadline };
});
await step("refuse_late", "holder4 claims after the window: CLAIM_WINDOW_OVER", () => refused(cl("holder4"), "claim", [A], "CLAIM_WINDOW_OVER", ad("holder4")));
await step("settle_A_unclaimed_to_fund", "settle A (called by the team itself): everything nobody claimed goes to the registry's fund; no claimant is paid again", async () => {
  const b0 = await team.view("get_bond", [A, now()]);
  const want = BigInt(b0.amount) - BigInt(b0.paid);
  const before = {};
  for (const who of ["holder2", "holder3"]) before[who] = await balanceOf(ad(who));
  const p = await paying(team, "settle", [A], FUND, (r) => r?.amount);          // the team calls it: it cannot direct anything
  const b = await team.view("get_bond", [A, now()]);
  const moved = {};
  for (const who of ["holder2", "holder3"]) moved[who] = String((await balanceOf(ad(who))) - before[who]);
  return { ...p, ok: p.ok && b.status === "CLOSED" && b0.due === "FUND" && p.returned?.to === FUND && p.returned?.amount === want.toString() && want > 0n
      && Object.values(moved).every((x) => x === "0") && b.paid === b0.paid,
    unclaimed: want.toString(), claimants_delta: moved, claims: b.n_claims };
});
await step("refuse_settle_twice", "settle A again: BOND_IS_CLOSED", () => refused(cl("keeper"), "settle", [A], "BOND_IS_CLOSED"));
await step("no_bonus_A", "bond A: every claimant holds exactly its own share (bond x eligible / claimable supply), although only 3 holders claimed", async () => {
  const b = await team.view("get_bond", [A, now()]);
  const rows = [];
  for (const who of ["holder1", "holder2", "holder3"]) {
    const c = await team.view("get_claim", [A, ad(who)]);
    const want = (BigInt(b.amount) * BigInt(c.balance)) / BigInt(b.denominator);
    rows.push({ holder: who, eligible: c.balance, share: c.share, expected: want.toString(), ok: c.share === want.toString() && !("bonus" in c) });
  }
  return { ok: rows.every((r) => r.ok) && rows.reduce((t, r) => t + BigInt(r.share), 0n) === BigInt(b.paid), claims: rows };
});
await step("conservation_A", "bond A: claims + the registry's fund = the bond; nothing went to the team", async () => {
  const b = await team.view("get_bond", [A, now()]);
  const total = BigInt(b.paid) + BigInt(b.settled_amount);
  return { ok: b.status === "CLOSED" && total === BigInt(b.amount) && b.remaining === "0" && b.settled_to === FUND,
    amount: b.amount, claims_paid: b.paid, to_fund: b.settled_amount, settled_to: b.settled_to };
});
await step("gate_closed", "LaunchGate: RUGGED_CLOSED", async () => {
  const a = await g.view("check_for", [RUG.token, A]);
  return { ok: a.state === "RUGGED_CLOSED", check_for: a };
});

// 8. the copycat: nobody filed a check on it within its recovery window (1 hour after its end on the demo registry),
//    so it is UNRESOLVED: the whole bond goes to the registry's fund, not to anyone its poster chose
await step("copycat_unresolved", "the copycat bond had no check for its whole recovery window: checks are refused, settle sends it to the registry's fund (UNRESOLVED)", async () => {
  const C = doc.bonds.C;
  const b = await team.view("get_bond", [C, now()]);
  if (b.status !== "ACTIVE" || b.due !== "FUND") return { ok: false, status: b.status, due: b.due };
  const chk = await refused(cl("keeper"), "check", [C], "RECOVERY_WINDOW_OVER_SETTLE_IT");
  const p = await paying(cl("stranger"), "settle", [C], FUND, (x) => x?.amount);        // its own poster settles it and still cannot redirect it
  return { ...p, ok: chk.ok && p.ok && p.returned?.status === "UNRESOLVED" && p.returned?.to === FUND && p.returned?.amount === b.amount, refused_check: chk, recovery_deadline: b.recovery_deadline };
});
// 8b. a rugged bond nobody claims on: the whole bond goes to the registry's fund
await step("open_E", "a stranger bonds RUGDEMO again (its liquidity is already gone); nobody will claim", async () => {
  const s = cl("stranger");
  const name = "RUGDEMO unclaimed " + start;
  const w = await s.write("create_bond", [name, "base-sepolia", RUG.token, RUG.pair, JSON.stringify([RUG.team]), "1", start, now() + 1800, 120,
    JSON.stringify([]), "0"], { value: GEN / 100n });
  const pg = await s.view("bonds_by_team", [s.me, 0, 50, now()]);
  doc.bonds.E = pg.items.find((x) => x.name === name)?.bond_id; save();
  return { ok: w.ok && !!doc.bonds.E, tx: w.hash, bond_id: doc.bonds.E };
});
await step("nobody_claimed_E", "bond E: RUGGED, nobody claims in its window, settle sends the whole bond to the registry's fund", async () => {
  const E = doc.bonds.E;
  const r = await checkUntil(E, ["RUGGED"], 60);
  let b = await team.view("get_bond", [E, now()]);
  if (b.status !== "RUGGED") return { ok: false, status: b.status };
  while (now() <= b.claim_deadline + 30) await sleep(20000);
  b = await team.view("get_bond", [E, now()]);
  const p = await paying(cl("stranger"), "settle", [E], FUND, (x) => x?.amount);
  return { ...p, ok: r.ok && b.due === "FUND" && b.n_claims === 0 && p.ok && p.returned?.status === "CLOSED" && p.returned?.to === FUND && p.returned?.amount === b.amount, rug_block: b.rug_block };
});

// 9. a live promise read recently: LaunchGate's ACTIVE_HELD_SO_FAR, then held and settled
await step("open_D", "team2 opens a second HOLDDEMO bond (ends in about an hour)", async () => {
  const head = Number(runEvm("head").trim());
  const name = "HOLDDEMO short bond " + head;
  const w = await team2.write("create_bond", [name, "base-sepolia", HOLD.token, HOLD.pair, JSON.stringify([HOLD.team]), HOLD_FLOOR, head, now() + 3600, 600,
    JSON.stringify([ad("stranger"), ROUTER_BSEP]), "0"], { value: GEN / 2n });
  const pg = await team2.view("bonds_by_team", [team2.me, 0, 50, now()]);
  doc.bonds.D = pg.items.find((x) => x.name === name)?.bond_id; save();
  return { ok: w.ok && !!doc.bonds.D, tx: w.hash, bond_id: doc.bonds.D, start_block: head };
});
await step("check_D", "the first check of bond D (SCANNED while the promise runs)", async () => {
  const k = cl("keeper");
  for (let i = 0; i < 400; i++) {
    const w = await k.write("check", [doc.bonds.D]);
    if (w.ok && w.returned?.result !== "PENDING") return { ok: w.returned?.result === "SCANNED", tx: w.hash, returned: w.returned };
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

await step("balance_zero_end", "the demo registry's balance is 0 at the end (after the e2e run's bonds close too)", async () => {
  const leftovers = [];
  for (let i = 0; i < 720; i++) {
    const st = await team.view("get_stats", []);
    if (st.held === "0") break;
    // the e2e run's rugged bonds (posted by `team`) are closed out here once due; the e2e settles its own held bond
    for (let off = 0; off >= 0;) {
      const pg = await team.view("bonds_by_team", [ad("team"), off, 50, now()]);
      for (const b of pg.items) if (b.due && !leftovers.find((x) => x.bond_id === b.bond_id)) {
        const p = await closeOut(b.bond_id);
        leftovers.push({ bond_id: b.bond_id, name: b.name, ...p });
        console.log("   closed out bond", b.bond_id, p.ok, p.status);
      }
      off = pg.next_offset;
    }
    if (i % 10 === 0) console.log("   waiting for open bonds to settle; held", st.held);
    await sleep(60000);
  }
  const bal = await balanceOf(ADDR);
  const stats = await team.view("get_stats", []);
  const all = [];
  for (let off = 0; off >= 0;) {
    const pg = await team.view("list_bonds", [off, 50, now()]);
    for (const b of pg.items) all.push({ bond_id: b.bond_id, name: b.name, team: b.team, status: b.status, amount: b.amount, paid: b.paid,
      settled_to: b.settled_to, settled_amount: b.settled_amount, rug_block: b.rug_block });
    off = pg.next_offset;
  }
  const out = BigInt(stats.claims_paid_total) + BigInt(stats.returned_total) + BigInt(stats.fund_total) + BigInt(stats.credit_paid_total) + BigInt(stats.stray_swept_total);
  return { ok: bal === 0n && stats.held === "0" && out === BigInt(stats.received_total) && leftovers.every((x) => x.ok) && all.every((b) => ["CLOSED", "RETURNED", "UNRESOLVED"].includes(b.status)),
    eth_getBalance: String(bal), fund: FUND, fund_balance: String(await balanceOf(FUND)), stats, leftovers, bonds: all };
});
console.log("\ndemo done:", doc.steps.filter((s) => s.ok).length, "steps");
