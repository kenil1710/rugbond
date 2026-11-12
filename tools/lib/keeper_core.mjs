// The keeper's logic, with the chains, the registry and the state store
// injected so the offline tests (test/keeper.test.mjs) drive it through
// outages, crashes, half-final transactions and hundreds of bonds and claims.
//
// One run:
//   1. RESUME every action with a stored transaction hash that is not finished:
//      poll that hash. Never submit a second transaction for an action whose
//      last one is not terminal - unless it has had no final status for 6 h;
//      then the bond is re-read and, if the action is still needed, it is
//      submitted again.
//   2. BONDS: walk every page of list_bonds from the persisted offset (a page
//      counts only when it parsed and its items are the ids it says).
//   3. PLAN per bond:
//        ACTIVE and checkable: read the chain's finalized head from BOTH RPCs
//          (a head counts only when two endpoints answered); if it is past the
//          bond's cursor, queue CHECK (key: bond + cursor + checks so far, so a
//          check is filed once per cursor position and a PENDING one is
//          retried as a new action).
//        due (HELD, VOID, RUGGED past its claim window, ACTIVE past its
//          recovery deadline): queue SETTLE. A rugged bond with claims goes
//          to REDISTRIBUTING: queue one BONUS per claim not yet paid its part
//          of the unclaimed GEN (every claims page is walked), and, once all
//          are paid, a final SETTLE for the integer leftover.
//   4. ACT, oldest first, up to maxActions: re-read the bond (already done by
//      anyone -> DONE, no transaction), else submit and checkpoint the hash.
//   5. SETTLE: poll this run's transactions until FINALIZED, within settleMs.
// An action is DONE only when its transaction is FINALIZED, executed
// successfully, and a read of the bond shows the effect (more checks recorded,
// or the bond settled). Everything not finished this run is listed in
// state.unprocessed with the reason; nothing is skipped silently.
// FAILED is not the end: an action that used up its attempts (a long Studio
// outage or rate limit) is queued again FAILED_RETRY_S later, with its attempts
// reset, for as long as the bond still needs it.
export const VERSION = 1;
export const MAX_ATTEMPTS = 8;
export const BOND_PAGE = 50;
export const STALE_S = 6 * 3600;
export const FAILED_RETRY_S = 6 * 3600;
const TERMINAL_BAD = ["UNDETERMINED", "CANCELED", "LEADER_TIMEOUT", "VALIDATORS_TIMEOUT"];
const SETTLED = ["CLOSED", "RETURNED", "UNRESOLVED"];

export function emptyState() {
  return { version: VERSION, bonds_offset: 0, bonds: {}, actions: {}, runs: [], unprocessed: [], last_run: null };
}
export const checkKey = (bid, cursor, n) => `check:${bid}:${cursor}:${n}`;
export const settleKey = (bid, status = "") => (status === "REDISTRIBUTING" ? `settle:${bid}:final` : `settle:${bid}`);
export const bonusKey = (bid, holder) => `bonus:${bid}:${holder}`;
export const backoffS = (attempts) => Math.min(60 * 2 ** Math.max(attempts - 1, 0), 6 * 3600);
// who a settle pays: the team (RETURN), nobody (REDISTRIBUTE only sets the pool aside), else the registry's fund
// (a registry deployed before the fund was fixed at deployment names it per bond: victim_fund)
export const payeeOf = (b) => (b.due === "RETURN" ? b.team : b.due === "REDISTRIBUTE" ? null : (b.fund ?? b.victim_fund));
const resultOf = (a, b) => (a.kind === "SETTLE" ? b.status : a.kind === "BONUS" ? "BONUS_PAID" : (b.last_result || b.status));

/**
 * chain: { endpoints(chain) -> [url], head(url, chain) -> finalized block number }
 * reg:   { now(), listBonds(offset, limit) -> page, getBond(bid) -> bond,
 *          listClaims(bid, offset, limit) -> page, getClaim(bid, holder) -> claim,
 *          check(bid) -> hash, settle(bid, payee | null) -> hash, payBonus(bid, holder, payee) -> hash, getTx(hash) -> {statusName, ok, reason} | null,
 *          wait?(hash, ms), sleep?(ms) }
 * store: { load() -> state, save(state, why) }
 */
export async function runKeeper({ chain, reg, store, log = () => {}, maxActions = 25, waitMs = 0, settleMs = 0, maxChecksPerBond = 3 }) {
  const state = (await store.load()) ?? emptyState();
  const run = { started_at: reg.now(), finished_at: null, resumed: 0, bonds: 0, pages: 0, pages_failed: 0, heads_failed: 0,
    queued: 0, requeued: 0, submitted: 0, done: 0, already: 0, pending: 0, failed: 0, retry: 0, errors: [] };
  const unprocessed = new Map();
  const note = (key, why) => unprocessed.set(key, { key, why });
  const save = async (why) => { await store.save(state, why); };

  async function verify(a) {
    const b = await reg.getBond(a.bond_id);
    if (!b?.found) return { b: null, done: false };
    if (a.kind === "SETTLE") return { b, done: SETTLED.includes(b.status) || (!a.final && b.status === "REDISTRIBUTING") };
    if (a.kind === "BONUS") {
      if (b.status === "CLOSED") return { b, done: true };
      const c = await reg.getClaim(a.bond_id, a.holder);
      return { b, done: c?.found === true && c.bonus_paid === true };
    }
    return { b, done: b.n_checks > a.n_checks_before || b.status !== "ACTIVE" };
  }

  async function conclude(a, tx) {
    const now = reg.now();
    let v;
    try { v = await verify(a); } catch (e) {
      a.last_error = "verifying read failed: " + String(e.message).slice(0, 120);
      run.pending++; note(a.key, `${a.tx} ${tx?.statusName ?? "?"}; verifying read failed, checked next run`);
      return;
    }
    const final = tx?.statusName === "FINALIZED" && tx.ok;
    if (v.done && final) {
      a.status = "DONE"; a.verified_at = now; a.result = resultOf(a, v.b);
      run.done++; log(`DONE ${a.key} ${a.tx} -> ${a.result}`);
      return;
    }
    if (v.done) {
      if (tx && tx.statusName !== "FINALIZED" && !TERMINAL_BAD.includes(tx.statusName) && !String(tx.statusName).startsWith("STALE")) {
        a.status = "ACCEPTED"; run.pending++; note(a.key, `effect visible but ${a.tx} is ${tx.statusName}; waiting for FINALIZED`);
        return;
      }
      a.status = "DONE"; a.verified_at = now; a.result = resultOf(a, v.b); a.done_by_other = true;
      run.done++; log(`DONE ${a.key} (the bond shows it done; our tx ${a.tx ?? "none"} ${tx?.statusName ?? ""})`);
      return;
    }
    if (final) { a.status = "FINAL_UNVERIFIED"; run.pending++; note(a.key, "finalized, waiting for the read to show it"); return; }
    a.attempts++; a.last_error = `tx ${a.tx} ${tx?.statusName ?? "not found"}${tx && !tx.ok ? " (reverted: " + (tx.reason ?? "") + ")" : ""}`;
    a.tx = null;
    if (a.attempts >= MAX_ATTEMPTS) { a.status = "FAILED"; a.failed_at = now; run.failed++; note(a.key, `gave up after ${a.attempts} attempts: ${a.last_error}`); }
    else { a.status = "RETRY"; a.next_try_at = now + backoffS(a.attempts); run.retry++; note(a.key, `retry ${a.attempts} after ${a.next_try_at}: ${a.last_error}`); }
    log(`RETRY ${a.key}: ${a.last_error}`);
  }

  // 0. FAILED actions come back after the cool-down (the act step re-reads the bond first)
  for (const a of Object.values(state.actions)) {
    if (a.status !== "FAILED" || a.last_error === "no such bond") continue;
    if (reg.now() - (a.failed_at ?? a.first_seen_at ?? 0) < FAILED_RETRY_S) continue;
    a.status = "RETRY"; a.attempts = 0; a.next_try_at = reg.now(); a.requeued = (a.requeued ?? 0) + 1;
    run.requeued++; log(`REQUEUE ${a.key} (failed before: ${a.last_error ?? ""})`);
  }

  // 1. resume
  for (const a of Object.values(state.actions)) {
    if (!["SUBMITTED", "ACCEPTED", "FINAL_UNVERIFIED"].includes(a.status)) continue;
    run.resumed++;
    if (a.status === "FINAL_UNVERIFIED") { await conclude(a, { statusName: "FINALIZED", ok: true }); await save("verify " + a.key); continue; }
    let tx = null;
    try { tx = await reg.getTx(a.tx); } catch (e) { a.last_error = "poll failed: " + e.message; run.pending++; note(a.key, "could not poll " + a.tx); continue; }
    if (tx && (tx.statusName === "FINALIZED" || TERMINAL_BAD.includes(tx.statusName))) { await conclude(a, tx); await save("resolved " + a.key); continue; }
    if (reg.now() - a.submitted_at > STALE_S) {
      log(`STALE ${a.key} ${a.tx} (${tx?.statusName ?? "not visible"} for ${reg.now() - a.submitted_at}s)`);
      await conclude(a, { statusName: "STALE_" + (tx?.statusName ?? "MISSING"), ok: false });
      await save("stale " + a.key);
      continue;
    }
    a.status = tx?.statusName === "ACCEPTED" ? "ACCEPTED" : "SUBMITTED";
    run.pending++; note(a.key, `waiting for ${a.tx} (${tx?.statusName ?? "not visible yet"})`);
  }

  // 2. bonds: every page, offset persisted
  const bonds = [];
  let off = 0;
  let listed = true;
  for (;;) {
    let pg;
    try { pg = await reg.listBonds(off, BOND_PAGE); } catch (e) {
      run.errors.push("list_bonds " + off + ": " + e.message); run.pages_failed++; listed = false;
      note("bonds:" + off, "bond listing failed at offset " + off + "; the rest is listed next run"); break;
    }
    const items = pg?.items;
    if (!Array.isArray(items) || items.some((b, i) => b.bond_id !== off + i + 1)) {
      run.pages_failed++; listed = false; note("bonds:" + off, "bond page at offset " + off + " malformed"); break;
    }
    run.pages++;
    bonds.push(...items);
    state.bonds_offset = off;
    if (pg.next_offset === undefined || pg.next_offset < 0 || pg.next_offset <= off) break;
    off = pg.next_offset;
  }
  state.bonds_listed_complete = listed;
  state.bonds_total = bonds.length;
  run.bonds = bonds.length;
  await save("bonds listed");

  // 3. plan
  const heads = {};
  async function headOf(ch) {
    if (heads[ch] !== undefined) return heads[ch];
    const hs = [];
    const why = [];
    for (const u of chain.endpoints(ch)) {
      try { hs.push(await chain.head(u, ch)); } catch (e) { why.push(String(e.message).slice(0, 60)); }
    }
    heads[ch] = hs.length === 2 ? Math.min(...hs) : null;
    if (heads[ch] === null) { run.heads_failed++; note("head:" + ch, "finalized head: fewer than two endpoints answered (" + why.join("; ") + ")"); }
    return heads[ch];
  }
  for (const b of bonds) {
    const bs = (state.bonds[b.bond_id] ??= {});
    Object.assign(bs, { status: b.status, chain: b.chain, token: b.token, cursor: b.cursor, cursor_ts: b.cursor_ts, n_checks: b.n_checks,
      n_pending: b.n_pending, last_result: b.last_result, due: b.due, name: b.name });
    const sk = settleKey(b.bond_id, b.status);
    if (b.due && !state.actions[sk]) {
      state.actions[sk] = { key: sk, kind: "SETTLE", bond_id: b.bond_id, payee: payeeOf(b), final: b.status === "REDISTRIBUTING", status: "QUEUED",
        attempts: 0, first_seen_at: reg.now(), tx: null };
      run.queued++;
    }
    // the bonus round: one BONUS per claim that has not been paid its part of the unclaimed GEN; every claims page
    if (b.status === "REDISTRIBUTING" && b.bonuses_due > 0 && reg.listClaims) {
      let co = 0;
      for (;;) {
        let pg;
        try { pg = await reg.listClaims(b.bond_id, co, BOND_PAGE); } catch (e) { run.pages_failed++; note(`bonus:${b.bond_id}:${co}`, "claims page failed: " + String(e.message).slice(0, 80)); break; }
        if (!Array.isArray(pg?.items) || pg.items.some((c, i) => c.claim_no !== co + i)) { run.pages_failed++; note(`bonus:${b.bond_id}:${co}`, "claims page malformed"); break; }
        run.pages++;
        for (const c of pg.items) {
          const k = bonusKey(b.bond_id, c.holder);
          if (c.bonus_paid || state.actions[k]) continue;
          state.actions[k] = { key: k, kind: "BONUS", bond_id: b.bond_id, holder: c.holder, payee: c.payee, status: "QUEUED", attempts: 0,
            first_seen_at: reg.now(), tx: null };
          run.queued++;
        }
        co += pg.items.length;
        if (pg.next_offset === undefined || pg.next_offset < 0 || pg.next_offset < co || pg.items.length === 0) break;
      }
      await save("bonuses " + b.bond_id);
    }
    // claims: every page from the persisted offset (the site and /keeper show them)
    if (b.n_claims > (bs.claims_seen ?? 0) && reg.listClaims) {
      let co = bs.claims_offset ?? 0;
      for (;;) {
        let pg;
        try { pg = await reg.listClaims(b.bond_id, co, BOND_PAGE); } catch (e) { run.pages_failed++; note(`claims:${b.bond_id}:${co}`, "claims page failed: " + String(e.message).slice(0, 80)); break; }
        if (!Array.isArray(pg?.items) || pg.items.some((c, i) => c.claim_no !== co + i)) { run.pages_failed++; note(`claims:${b.bond_id}:${co}`, "claims page malformed"); break; }
        run.pages++;
        bs.claims_paid = (BigInt(bs.claims_paid ?? "0") + pg.items.reduce((x, c) => x + BigInt(c.share), 0n)).toString();
        co += pg.items.length;
        bs.claims_offset = co; bs.claims_seen = co;
        if (pg.next_offset === undefined || pg.next_offset < 0 || pg.next_offset < co || pg.items.length === 0) break;
      }
      await save("claims " + b.bond_id);
    }
    if (b.status === "ACTIVE" && b.checkable) {
      const k = checkKey(b.bond_id, b.cursor, b.n_checks);
      if (state.actions[k]) continue;
      const open = Object.values(state.actions).some((a) => a.kind === "CHECK" && a.bond_id === b.bond_id && !["DONE", "FAILED"].includes(a.status));
      if (open) continue;
      const h = await headOf(b.chain);
      if (h === null) { note("bond:" + b.bond_id, "head unreadable; check deferred"); continue; }
      const next = b.cursor >= b.start_block ? b.cursor + 1 : b.start_block;
      if (h < next) { bs.waiting = `finalized head ${h} below block ${next}`; continue; }
      state.actions[k] = { key: k, kind: "CHECK", bond_id: b.bond_id, cursor: b.cursor, n_checks_before: b.n_checks, status: "QUEUED", attempts: 0,
        first_seen_at: reg.now(), tx: null };
      run.queued++;
    }
  }
  await save("planned");

  // 4. act, oldest first
  const queue = Object.values(state.actions).filter((a) => a.status === "QUEUED" || (a.status === "RETRY" && reg.now() >= a.next_try_at))
    .sort((x, y) => x.first_seen_at - y.first_seen_at || (x.key < y.key ? -1 : 1));
  let acted = 0;
  for (const a of queue) {
    if (acted >= maxActions) { note(a.key, "queued; this run reached its action limit"); continue; }
    let v;
    try { v = await verify(a); } catch (e) { note(a.key, "pre-read failed: " + e.message); continue; }
    if (v.done) { a.status = "DONE"; a.result = resultOf(a, v.b); a.done_by_other = !(a.tx_history?.length); a.verified_at = reg.now(); run.already++; run.done++; await save("already " + a.key); continue; }
    if (!v.b) { a.status = "FAILED"; a.failed_at = reg.now(); a.last_error = "no such bond"; run.failed++; note(a.key, a.last_error); continue; }
    if (a.kind === "CHECK" && (!v.b.checkable || v.b.cursor !== a.cursor)) {
      a.status = "DONE"; a.result = "SUPERSEDED"; a.verified_at = reg.now(); run.already++; run.done++; await save("superseded " + a.key); continue;
    }
    if (a.kind === "SETTLE" && !v.b.due) { note(a.key, "not due yet"); a.status = "RETRY"; a.next_try_at = reg.now() + 300; continue; }
    if (a.kind === "BONUS" && v.b.status !== "REDISTRIBUTING") { note(a.key, "bond is " + v.b.status + ", not redistributing"); a.status = "RETRY"; a.next_try_at = reg.now() + 300; continue; }
    acted++;
    try {
      a.tx = a.kind === "CHECK" ? await reg.check(a.bond_id) : a.kind === "BONUS" ? await reg.payBonus(a.bond_id, a.holder, a.payee)
        : await reg.settle(a.bond_id, payeeOf(v.b));
    } catch (e) {
      a.attempts++; a.last_error = "submit failed: " + String(e.message).slice(0, 160);
      a.status = a.attempts >= MAX_ATTEMPTS ? "FAILED" : "RETRY"; a.next_try_at = reg.now() + backoffS(a.attempts);
      if (a.status === "FAILED") { a.failed_at = reg.now(); run.failed++; } else run.retry++;
      note(a.key, a.last_error); await save("submit failed " + a.key); continue;
    }
    a.status = "SUBMITTED"; a.submitted_at = reg.now(); (a.tx_history ??= []).push(a.tx);
    run.submitted++;
    await save("submitted " + a.key);
    if (waitMs > 0 && reg.wait) {
      const tx = await reg.wait(a.tx, waitMs);
      if (tx && (tx.statusName === "FINALIZED" || TERMINAL_BAD.includes(tx.statusName))) await conclude(a, tx);
      else { a.status = tx?.statusName === "ACCEPTED" ? "ACCEPTED" : "SUBMITTED"; run.pending++; note(a.key, `waiting for ${a.tx} (${tx?.statusName ?? "not visible"})`); }
      await save("waited " + a.key);
    } else { run.pending++; note(a.key, `submitted ${a.tx}; checked next run`); }
  }

  // 5. settle in-flight transactions within the budget
  const t0 = Date.now();
  while (settleMs > 0 && reg.sleep) {
    const open = Object.values(state.actions).filter((a) => ["SUBMITTED", "ACCEPTED", "FINAL_UNVERIFIED"].includes(a.status) && a.tx);
    if (!open.length || Date.now() - t0 > settleMs) break;
    await reg.sleep(15_000);
    for (const a of open) {
      let tx = null;
      try { tx = await reg.getTx(a.tx); } catch { continue; }
      if (tx && (tx.statusName === "FINALIZED" || TERMINAL_BAD.includes(tx.statusName))) {
        unprocessed.delete(a.key); run.pending = Math.max(0, run.pending - 1);
        await conclude(a, tx); await save("settled " + a.key);
      }
    }
  }

  for (const a of Object.values(state.actions)) if (a.status === "FAILED") note(a.key, "FAILED: " + (a.last_error ?? "") + (a.last_error === "no such bond" ? "" : `; queued again after ${(a.failed_at ?? 0) + FAILED_RETRY_S}`));
  run.finished_at = reg.now();
  state.unprocessed = [...unprocessed.values()];
  state.last_run = run;
  state.runs = [...(state.runs ?? []), { ...run, errors: run.errors.slice(0, 5) }].slice(-48);
  state.totals = totals(state);
  await save("run finished");
  return { run, state };
}

export function totals(state) {
  const t = { actions: 0, done: 0, queued: 0, pending: 0, retry: 0, failed: 0, by_result: {} };
  for (const a of Object.values(state.actions)) {
    t.actions++;
    if (a.status === "DONE") { t.done++; t.by_result[a.result] = (t.by_result[a.result] ?? 0) + 1; }
    else if (a.status === "QUEUED") t.queued++;
    else if (a.status === "RETRY") t.retry++;
    else if (a.status === "FAILED") t.failed++;
    else t.pending++;
  }
  return t;
}
