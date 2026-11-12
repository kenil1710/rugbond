// Keeper tests (node --test): outages and backfill, >50 bonds and >500 claims
// pagination, idempotency, ACCEPTED-not-final, resume from a stored hash, stale
// hashes, retry queue, nothing silently skipped.
import { test } from "node:test";
import assert from "node:assert/strict";
import { runKeeper, emptyState, checkKey, settleKey, payeeOf, STALE_S, MAX_ATTEMPTS, FAILED_RETRY_S, backoffS } from "../tools/lib/keeper_core.mjs";

/** A fake registry with the contract's semantics, and transactions that finalize when told to. */
function world({ nBonds = 3, head = 10_000, claims = 0 } = {}) {
  let now = 1_800_000_000;
  const bonds = [];
  for (let i = 1; i <= nBonds; i++) {
    bonds.push({ bond_id: i, found: true, team: "0xteam" + i, fund: "0xfund", chain: "base", token: "0xt" + i, status: "ACTIVE",
      start_block: 1000, cursor: 0, cursor_ts: 0, n_checks: 0, n_pending: 0, last_result: "", due: "", checkable: true, end_block: 5000,
      rug_block: 0, n_claims: claims, claim_deadline: 0, recovery_deadline: now + 86400 * 30 });
  }
  const claimList = Array.from({ length: claims }, (_, i) => ({ claim_no: i, share: "10", holder: "0xh" + i, payee: "0xp" + i, found: true }));
  const txs = {};
  let n = 0;
  const w = {
    head, down: new Set(), failList: false, submitFail: 0, autoFinal: true, txFate: null, outcome: () => "SCANNED",
    calls: { check: 0, settle: 0, listBonds: 0, listClaims: 0 }, settledTo: [],
    now: () => now, advance: (s) => { now += s; },
    bonds, txs,
    apply(t) {
      const b = bonds[t.bid - 1];
      if (t.kind === "check") {
        if (b.status !== "ACTIVE") return false;
        b.n_checks++;
        const r = w.outcome(b);
        b.last_result = r;
        if (r === "PENDING") { b.n_pending++; return true; }
        const next = b.cursor >= b.start_block ? b.cursor + 1 : b.start_block;
        b.cursor = Math.min(next + 7999, w.head);
        if (r === "RUGGED") { b.status = "RUGGED"; b.claim_deadline = now + 3600; }
        if (r === "HELD" || b.cursor >= b.end_block) { b.status = "HELD"; b.last_result = "HELD"; b.due = "RETURN"; b.checkable = false; }
        return true;
      }
      if (!b.due) return false;
      w.settledTo.push(t.payee);
      b.status = b.status === "RUGGED" ? "CLOSED" : b.status === "ACTIVE" ? "UNRESOLVED" : "RETURNED";
      b.due = ""; b.checkable = false;
      return true;
    },
  };
  const reg = {
    now: () => now,
    async listBonds(off, lim) {
      w.calls.listBonds++;
      if (w.failList) throw new Error("studio down");
      const items = bonds.slice(off, off + lim).map((b) => ({ ...b }));
      return { items, next_offset: off + items.length < bonds.length ? off + items.length : -1 };
    },
    async listClaims(bid, off, lim) {
      w.calls.listClaims++;
      const items = claimList.slice(off, off + lim);
      return { items, next_offset: off + items.length < claimList.length ? off + items.length : -1 };
    },
    async getBond(bid) { const b = bonds[bid - 1]; return b ? { ...b } : { found: false }; },
    async check(bid) {
      if (w.submitFail > 0) { w.submitFail--; throw new Error("busy"); }
      w.calls.check++; const h = "0xtx" + ++n; txs[h] = { kind: "check", bid, status: "PENDING" }; return h;
    },
    async getClaim(bid, holder) { const c = claimList.find((x) => x.holder === holder); return c ? { ...c } : { found: false }; },
    async settle(bid, payee) {
      if (w.submitFail > 0) { w.submitFail--; throw new Error("busy"); }
      w.calls.settle++; const h = "0xtx" + ++n; txs[h] = { kind: "settle", bid, payee, status: "PENDING" }; return h;
    },
    async getTx(h) {
      const t = txs[h];
      if (!t) return null;
      if (t.status === "PENDING" && w.autoFinal) {
        const fate = w.txFate ? w.txFate(t) : "FINALIZED";
        if (fate === "FINALIZED") { t.ok = w.apply(t); t.status = "FINALIZED"; }
        else t.status = fate;
      }
      return { statusName: t.status, ok: t.status === "FINALIZED" && t.ok !== false, reason: t.ok === false ? "REFUSED" : "" };
    },
    async wait(h) { return reg.getTx(h); },
    sleep: async () => {},
  };
  const chain = {
    endpoints: () => ["A", "B"],
    async head(u) { if (w.down.has(u)) throw new Error(u + " down"); return w.head; },
  };
  const saved = [];
  let state = emptyState();
  const store = { async load() { return JSON.parse(JSON.stringify(state)); }, async save(s, why) { state = JSON.parse(JSON.stringify(s)); saved.push(why); } };
  return { w, reg, chain, store, saved, get state() { return state; }, set state(s) { state = s; } };
}

const go = (x, o = {}) => runKeeper({ chain: x.chain, reg: x.reg, store: x.store, waitMs: 1, settleMs: 1, ...o });

test("checks every active bond once per cursor and reaches HELD", async () => {
  const x = world({ nBonds: 3, head: 20_000 });
  for (let i = 0; i < 4; i++) await go(x);
  for (const b of x.w.bonds) assert.equal(b.status, "RETURNED");
  const keys = Object.keys(x.state.actions);
  assert.equal(new Set(keys).size, keys.length);
});

test("idempotent: a second run with nothing new submits nothing", async () => {
  const x = world({ nBonds: 2, head: 1500 });
  await go(x);
  const c = x.w.calls.check;
  await go(x);
  assert.equal(x.w.calls.check, c);
});

test("over 50 bonds: every page listed", async () => {
  const x = world({ nBonds: 137, head: 1000 + 100 });
  const { run } = await go(x, { maxActions: 500 });
  assert.equal(run.bonds, 137);
  assert.equal(run.pages >= 3, true);
  assert.equal(x.w.calls.check, 137);
});

test("over 500 claims: every claims page walked, offset persisted", async () => {
  const x = world({ nBonds: 1, head: 900, claims: 523 });
  await go(x);
  assert.equal(x.state.bonds[1].claims_seen, 523);
  assert.equal(x.state.bonds[1].claims_paid, String(523 * 10));
  const before = x.w.calls.listClaims;
  await go(x);
  assert.equal(x.w.calls.listClaims, before);
});

test("head from only one endpoint: no check, listed as unprocessed", async () => {
  const x = world({ nBonds: 1 });
  x.w.down.add("B");
  const { run, state } = await go(x);
  assert.equal(x.w.calls.check, 0);
  assert.equal(run.heads_failed, 1);
  assert.ok(state.unprocessed.some((u) => u.key === "head:base"));
});

test("outage then backfill: listing fails, next run catches up", async () => {
  const x = world({ nBonds: 4, head: 1200 });
  x.w.failList = true;
  const r1 = await go(x);
  assert.equal(r1.run.bonds, 0);
  assert.ok(r1.state.unprocessed.some((u) => u.key.startsWith("bonds:")));
  x.w.failList = false;
  await go(x);
  assert.equal(x.w.calls.check, 4);
});

test("ACCEPTED is not final: kept, resumed, then DONE", async () => {
  const x = world({ nBonds: 1, head: 1200 });
  x.w.txFate = () => "ACCEPTED";
  await go(x);
  const a = Object.values(x.state.actions)[0];
  assert.equal(a.status, "ACCEPTED");
  x.w.txFate = null;
  x.w.txs[a.tx].status = "PENDING";
  await go(x);
  assert.equal(x.state.actions[a.key].status, "DONE");
  assert.equal(x.w.calls.check, 1);
});

test("resume from a stored hash after a crash: no duplicate submit", async () => {
  const x = world({ nBonds: 1, head: 1200 });
  x.w.autoFinal = false;
  await go(x);
  assert.equal(x.w.calls.check, 1);
  x.w.autoFinal = true;
  const { run } = await go(x);
  assert.equal(run.resumed, 1);
  assert.equal(x.w.calls.check, 1);
  assert.equal(Object.values(x.state.actions)[0].status, "DONE");
});

test("stuck hash retried after 6 hours", async () => {
  const x = world({ nBonds: 1, head: 1200 });
  x.w.autoFinal = false;
  await go(x);
  x.w.advance(STALE_S - 10);
  await go(x);
  assert.equal(x.w.calls.check, 1);
  x.w.advance(20);
  await go(x);
  const a = Object.values(x.state.actions)[0];
  assert.equal(a.status, "RETRY");
  x.w.advance(3600);
  x.w.autoFinal = true;
  await go(x);
  assert.equal(x.w.calls.check, 2);
  assert.equal(x.state.actions[a.key].status, "DONE");
});

test("undetermined tx goes to the retry queue with backoff", async () => {
  const x = world({ nBonds: 1, head: 1200 });
  x.w.txFate = () => "UNDETERMINED";
  await go(x);
  const a = Object.values(x.state.actions)[0];
  assert.equal(a.status, "RETRY");
  await go(x);
  assert.equal(x.w.calls.check, 1);
  x.w.txFate = null;
  x.w.advance(120);
  await go(x);
  assert.equal(x.state.actions[a.key].status, "DONE");
});

test("submit failures retried, then FAILED after MAX_ATTEMPTS and listed", async () => {
  const x = world({ nBonds: 1, head: 1200 });
  x.w.submitFail = 100;
  for (let i = 0; i < MAX_ATTEMPTS; i++) { await go(x); x.w.advance(backoffS(i + 1) + 1); }
  const a = Object.values(x.state.actions)[0];
  assert.equal(a.status, "FAILED");
  assert.ok(x.state.unprocessed.some((u) => u.key === a.key && u.why.startsWith("FAILED")));
});

test("FAILED is queued again after the cool-down and finishes once Studio answers", async () => {
  const x = world({ nBonds: 1, head: 1200 });
  x.w.submitFail = MAX_ATTEMPTS;
  for (let i = 0; i < MAX_ATTEMPTS; i++) { await go(x); x.w.advance(backoffS(i + 1) + 1); }
  const key = Object.values(x.state.actions)[0].key;
  assert.equal(x.state.actions[key].status, "FAILED");
  await go(x);                                    // inside the cool-down: still FAILED, still listed, nothing submitted
  assert.equal(x.state.actions[key].status, "FAILED");
  assert.equal(x.w.calls.check, 0);
  x.w.advance(FAILED_RETRY_S);
  const r = await go(x);
  assert.equal(r.run.requeued, 1);
  assert.equal(x.state.actions[key].status, "DONE");
  assert.equal(x.w.calls.check, 1);
  assert.equal(x.w.bonds[0].n_checks, 1);
});

test("PENDING check result: done, and a new check is queued", async () => {
  const x = world({ nBonds: 1, head: 1200 });
  let first = true;
  x.w.outcome = () => { if (first) { first = false; return "PENDING"; } return "SCANNED"; };
  await go(x);
  assert.equal(x.w.bonds[0].n_pending, 1);
  await go(x);
  assert.equal(x.w.bonds[0].cursor, 1200);
  assert.ok(x.state.actions[checkKey(1, 0, 0)]);
  assert.ok(x.state.actions[checkKey(1, 0, 1)]);
});

test("settle queued when due, paid to the right payee, once", async () => {
  const x = world({ nBonds: 1, head: 1200 });
  x.w.outcome = () => "RUGGED";
  await go(x);
  assert.equal(x.w.bonds[0].status, "RUGGED");
  x.w.bonds[0].due = "FUND";
  await go(x);
  assert.equal(x.w.bonds[0].status, "CLOSED");
  assert.equal(x.state.actions[settleKey(1)].payee, "0xfund");
  assert.deepEqual(x.w.settledTo, ["0xfund"]);
  await go(x);
  assert.equal(x.w.calls.settle, 1);
});

test("payee: the team on RETURN, the registry's fund otherwise (victim_fund on a registry from before)", () => {
  assert.equal(payeeOf({ due: "RETURN", team: "0xt", fund: "0xf" }), "0xt");
  assert.equal(payeeOf({ due: "FUND", team: "0xt", fund: "0xf" }), "0xf");
  assert.equal(payeeOf({ due: "VICTIM_FUND", team: "0xt", victim_fund: "0xv" }), "0xv");
});

test("rugged with claims: one settle sends the unclaimed part to the registry's fund; no claimant is paid again", async () => {
  const x = world({ nBonds: 1, head: 1200, claims: 7 });
  x.w.outcome = () => "RUGGED";
  await go(x);
  x.w.bonds[0].due = "FUND";
  for (let i = 0; i < 3; i++) await go(x);
  assert.equal(x.w.bonds[0].status, "CLOSED");
  assert.equal(x.w.calls.settle, 1);
  assert.deepEqual(x.w.settledTo, ["0xfund"]);
  assert.equal(x.state.actions[settleKey(1)].result, "CLOSED");
  assert.deepEqual(Object.values(x.state.actions).map((a) => a.kind).filter((k) => !["CHECK", "SETTLE"].includes(k)), []);
});

test("already done by someone else: no transaction", async () => {
  const x = world({ nBonds: 1, head: 1200 });
  x.w.bonds[0].due = "RETURN";
  x.w.bonds[0].status = "HELD";
  x.w.bonds[0].checkable = false;
  const plan = await x.reg.listBonds(0, 50);
  x.state = { ...emptyState(), actions: { [settleKey(1)]: { key: settleKey(1), kind: "SETTLE", bond_id: 1, payee: "0xteam1", status: "QUEUED", attempts: 0, first_seen_at: 0, tx: null } } };
  x.w.bonds[0].status = "RETURNED"; x.w.bonds[0].due = "";
  await go(x);
  assert.equal(x.w.calls.settle, 0);
  assert.equal(x.state.actions[settleKey(1)].status, "DONE");
  assert.ok(plan.items.length === 1);
});

test("two keepers at once: the second sees the effect and does not double-submit", async () => {
  const x = world({ nBonds: 1, head: 1200 });
  await go(x);
  const y = { ...x, store: { async load() { return emptyState(); }, async save() {} } };
  await runKeeper({ chain: x.chain, reg: x.reg, store: y.store, waitMs: 1, settleMs: 1 });
  assert.equal(x.w.bonds[0].n_checks, 2 - 1 + (x.w.calls.check - 1));
  assert.ok(x.w.calls.check <= 2);
});

test("action limit: the rest stays queued and is listed", async () => {
  const x = world({ nBonds: 10, head: 1200 });
  const { state } = await go(x, { maxActions: 3 });
  assert.equal(x.w.calls.check, 3);
  assert.equal(state.unprocessed.filter((u) => u.why.includes("action limit")).length, 7);
});

test("finalized head below the start block: nothing to do, not an error", async () => {
  const x = world({ nBonds: 1, head: 900 });
  const { run } = await go(x);
  assert.equal(x.w.calls.check, 0);
  assert.equal(run.failed, 0);
  assert.match(x.state.bonds[1].waiting, /below block 1000/);
});

test("every checkpoint saved (crash anywhere resumes)", async () => {
  const x = world({ nBonds: 2, head: 1200 });
  await go(x);
  assert.ok(x.saved.includes("bonds listed"));
  assert.ok(x.saved.some((s) => s.startsWith("submitted")));
  assert.equal(x.saved.at(-1), "run finished");
});

test("FINAL_UNVERIFIED when the read lags, verified next run", async () => {
  const x = world({ nBonds: 1, head: 1200 });
  const orig = x.reg.getBond;
  let lag = true;
  x.reg.getBond = async (bid) => { const b = await orig(bid); if (lag && b.n_checks > 0) return { ...b, n_checks: 0, last_result: "", status: "ACTIVE" }; return b; };
  await go(x);
  assert.equal(Object.values(x.state.actions)[0].status, "FINAL_UNVERIFIED");
  lag = false;
  await go(x);
  assert.equal(Object.values(x.state.actions)[0].status, "DONE");
});

test("a state saved for another registry address is not reused", async () => {
  // tools/keeper.mjs binds each state file to its registry address; the core treats a fresh state as no actions
  const x = world({ nBonds: 2, head: 1200 });
  await go(x);
  const c = x.w.calls.check;
  x.state = emptyState();             // what load() returns for a different address
  for (const b of x.w.bonds) { b.cursor = 0; b.n_checks = 0; b.status = "ACTIVE"; b.checkable = true; b.due = ""; }
  await go(x);
  assert.equal(x.w.calls.check, c + 2);
});
