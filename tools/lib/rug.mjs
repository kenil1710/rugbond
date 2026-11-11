// The contract's reads and rule, in JavaScript, for this machine: the
// feasibility study, the keeper's predictions, the real-world check and the
// site. Same calls, same field order, same canonical JSON as
// contracts/shared/{common,rpc}.py, so a read here can be compared byte for
// byte with the one GenVM stored (tools/feasibility.mjs does).
import { ALL_CHAINS as CHAINS, ALL_LIMITS as LIMITS, TRANSFER } from "./chains.mjs";

export const MAX_PROBES = 6;
const FACTORIES = {
  ethereum: { "0x5c69bee701ef814a2b6a3edd4b1652cb9cc5aa6f": "getPair", "0xc0aee478e3658e2610c5f7a4a2e1777ce9e4f2ac": "getPair" },
  base: { "0x8909dc15e40173ff4699343b6eb8132c65e18ec6": "getPair", "0x71524b4f93c58fcbf659783284e38825f0622859": "getPair",
    "0x420dd381b31aef6683db6b902084cb0ffece40da": "getPool" },          // Mac-only (see chains.mjs)
  "base-sepolia": { "0x7ae58f10f7849ca6f5fb71b7f45cb416c9204b1e": "getPair" },
};
export { FACTORIES };

export class ReadFailed extends Error {}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const hex = (n) => "0x" + BigInt(n).toString(16);
const isHex = (s) => /^[0-9a-f]*$/.test(s);
export const addr = (v) => { const t = String(v ?? "").trim().toLowerCase(); return t.length === 42 && t.startsWith("0x") && isHex(t.slice(2)) ? t : ""; };
const hash32 = (v) => { const t = String(v ?? "").trim().toLowerCase(); return t.length === 66 && t.startsWith("0x") && isHex(t.slice(2)) ? t : ""; };
const hexInt = (v) => { if (typeof v !== "string") return -1; const t = v.trim().toLowerCase(); return t.startsWith("0x") && t.length >= 3 && t.length <= 66 && isHex(t.slice(2)) ? Number(BigInt(t)) : -1; };
const wordAddr = (v) => { const t = hash32(v); return t && t.slice(2, 26) === "0".repeat(24) ? "0x" + t.slice(26) : ""; };
const wordUint = (v) => { const t = hash32(v); return t ? BigInt(t) : -1n; };
const uint = (v) => { const n = wordUint(v); if (n < 0n) throw new ReadFailed("not a uint"); return n; };
const pad = (a) => "0x" + "0".repeat(24) + a.slice(2);
const balCall = (token, who, blk) => ["eth_call", [{ to: token, data: "0x70a08231" + "0".repeat(24) + who.slice(2) }, hex(blk)]];

/** Python's json.dumps(sort_keys=True, separators=(",", ":")) for the shapes used here. */
export function canon(v) {
  if (v === null || v === undefined) return "null";
  if (typeof v === "bigint") return v.toString();
  if (Array.isArray(v)) return "[" + v.map(canon).join(",") + "]";
  if (typeof v === "object") return "{" + Object.keys(v).sort().map((k) => JSON.stringify(k) + ":" + canon(v[k])).join(",") + "}";
  return JSON.stringify(v);
}

let stats = { requests: 0, retries: 0 };
export const rpcStats = () => ({ ...stats });

/** One endpoint, every call, in batches of `per`; retried like the contract does (4 tries), plus backoff. */
export async function rpcSend(url, calls, per, { tries = Number(process.env.RPC_TRIES ?? 4), soft = -1 } = {}) {
  const out = [];
  for (let i = 0; i < calls.length; i += per) {
    const chunk = calls.slice(i, i + per);
    const body = JSON.stringify(chunk.map((c, j) => ({ jsonrpc: "2.0", id: j, method: c[0], params: c[1] })));
    let got = null, why = "";
    for (let k = 0; k < tries && got === null; k++) {
      if (k) { stats.retries++; await sleep(2500 * k); }
      stats.requests++;
      try {
        const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body, signal: AbortSignal.timeout(30000) });
        if (r.status !== 200) { why = "http " + r.status; if (r.status !== 429 && r.status < 500) break; continue; }
        let doc = JSON.parse(await r.text());
        if (!Array.isArray(doc)) doc = [doc];
        const byId = new Map(doc.filter((x) => x && Number.isInteger(x.id)).map((x) => [x.id, x]));
        const res = [];
        for (let j = 0; j < chunk.length; j++) {
          const it = byId.get(j);
          if (!it) throw new ReadFailed("missing id");
          if (it.error) { if (i + j === soft) { res.push(null); continue; } throw new ReadFailed("rpc error: " + JSON.stringify(it.error).slice(0, 80)); }
          if (!("result" in it)) throw new ReadFailed("no result");
          res.push(it.result);
        }
        got = res;
      } catch (e) { why = String(e.message ?? e).slice(0, 100); }
    }
    if (got === null) throw new ReadFailed(new URL(url).host + " " + why);
    out.push(...got);
  }
  return out;
}

function ts(h, n) {
  if (!h || typeof h !== "object" || hexInt(h.number) !== n) throw new ReadFailed("header");
  const t = hexInt(h.timestamp);
  if (t <= 0) throw new ReadFailed("timestamp");
  return t;
}

/** The finalized head on one endpoint (display / keeper use). */
export async function readHead(url, chain) {
  const a = await rpcSend(url, [["eth_chainId", []], ["eth_getBlockByNumber", ["finalized", false]]], LIMITS[url].batch);
  if (hexInt(a[0]) !== CHAINS[chain].id) throw new ReadFailed("wrong chain id");
  const fin = a[1] && typeof a[1] === "object" ? hexInt(a[1].number) : -1;
  if (fin < 0) throw new ReadFailed("no finalized head");
  return fin;
}

export function denominator(supply, excluded) {
  let d = BigInt(supply);
  for (const e of excluded) d -= BigInt(e[1]);
  return d > 0n ? d : 0n;
}

const logsCall = (t, w, z) => ["eth_getLogs", [{ address: t.pair, topics: [TRANSFER, t.lp_holders.map(pad)], fromBlock: hex(w), toBlock: typeof z === "string" ? z : hex(z) }]];

function parseLogs(parts, t, a, b) {
  const logs = [];
  for (const part of parts) {
    if (!Array.isArray(part)) throw new ReadFailed("logs");
    for (const lg of part) {
      if (!lg || typeof lg !== "object" || lg.removed === true) throw new ReadFailed("log");
      const tp = lg.topics ?? [];
      if (addr(lg.address) !== t.pair || !Array.isArray(tp) || tp.length !== 3 || String(tp[0]).toLowerCase() !== TRANSFER) continue;
      const frm = wordAddr(tp[1]), to = wordAddr(tp[2]), amt = wordUint(lg.data), blk = hexInt(lg.blockNumber), li = hexInt(lg.logIndex), txh = hash32(lg.transactionHash);
      if (!t.lp_holders.includes(frm) || !to || amt < 0n || blk < a || li < 0 || !txh) throw new ReadFailed("log fields");
      if (blk <= b) logs.push([blk, li, txh, frm, to, amt.toString()]);
    }
  }
  return logs.sort((x, y) => (x[0] * 1000000 + x[1]) - (y[0] * 1000000 + y[1]));
}

export async function readOpen(url, chain, t, a) {
  const lim = LIMITS[url];
  const top = a + CHAINS[chain].check_blocks - 1;
  const z = Math.min(a + lim.span - 1, top);
  const call = logsCall(t, a, lim.beyond_head ? z : "finalized");
  const r = await rpcSend(url, [["eth_chainId", []], ["eth_getBlockByNumber", ["finalized", false]], call], 3, { soft: 2 });
  if (hexInt(r[0]) !== CHAINS[chain].id) throw new ReadFailed("wrong chain id");
  const fin = r[1] && typeof r[1] === "object" ? hexInt(r[1].number) : -1;
  if (fin < 0) throw new ReadFailed("no finalized head");
  if (r[2] === null) return { fin, logs: [], to: a - 1 };
  return { fin, logs: r[2], to: lim.beyond_head ? z : Math.min(fin, top) };
}

export async function readWindow(url, surl, chain, t, a, b, opened, first) {
  const span = LIMITS[url].span, per = LIMITS[surl].batch;
  const pair = t.pair, holders = t.lp_holders, start = Number(t.start_block), floor = BigInt(t.min_lp);
  let parts = [opened.logs];
  const more = [];
  for (let w = opened.to + 1; w <= b;) { const z = Math.min(w + span - 1, b); more.push(logsCall(t, w, z)); w = z + 1; }
  if (more.length) parts = parts.concat(await rpcSend(url, more, 1));
  let logs = parseLogs(parts, t, a, b);
  let pb = [];
  if (a === start) pb.push(start);
  for (const lg of logs) if (!pb.includes(lg[0])) pb.push(lg[0]);
  if (pb.length > MAX_PROBES) { b = pb[MAX_PROBES] - 1; pb = pb.slice(0, MAX_PROBES); logs = logs.filter((lg) => lg[0] <= b); }
  const sc = [["eth_getBlockByNumber", [hex(b), false]]];
  if (a === start) sc.push(["eth_getBlockByNumber", [hex(start), false]]);
  if (first) for (const d of ["0x0dfe1681", "0xd21220a7", "0xc45a0155"]) sc.push(["eth_call", [{ to: pair, data: d }, "latest"]]);
  const k0 = sc.length;
  for (const blk of pb) for (const h of holders) sc.push(balCall(pair, h, blk));
  const vals = await rpcSend(surl, sc, per);
  const endTs = ts(vals[0], b);
  const startTs = a === start ? ts(vals[1], start) : 0;
  let pr = null;
  if (first) { const j = a === start ? 2 : 1; pr = { token0: wordAddr(vals[j]), token1: wordAddr(vals[j + 1]), factory: wordAddr(vals[j + 2]), ok: false, why: "" }; }
  const probes = [];
  let rugAt = -1, k = k0;
  for (const blk of pb) {
    let tot = 0n;
    for (const _ of holders) tot += uint(vals[k++]);
    probes.push([blk, tot.toString()]);
    if (tot < floor) { rugAt = blk; break; }
  }
  const third = [];
  let how = "";
  if (pr) {
    if (!pr.token0 || !pr.token1 || !pr.factory) pr.why = "NOT_A_PAIR";
    else if (t.token !== pr.token0 && t.token !== pr.token1) pr.why = "TOKEN_NOT_IN_PAIR";
    else {
      how = FACTORIES[chain]?.[pr.factory] ?? "";
      if (!how) pr.why = "UNKNOWN_FACTORY";
      else {
        let data = (how === "getPair" ? "0xe6a43905" : "0x79bc57d5") + "0".repeat(24) + pr.token0.slice(2) + "0".repeat(24) + pr.token1.slice(2);
        if (how === "getPool") data += "0".repeat(64);
        third.push(["eth_call", [{ to: pr.factory, data }, "latest"]]);
      }
    }
  }
  const out = { a, b, logs, probes, rug: null, end_ts: endTs, start_ts: startTs };
  const snap = rugAt >= 0;
  if (snap) {
    third.push(["eth_getBlockByNumber", [hex(rugAt), false]]);
    third.push(["eth_call", [{ to: t.token, data: "0x18160ddd" }, hex(rugAt - 1)]]);
    for (const h of holders) third.push(balCall(pair, h, rugAt - 1));
    for (const e of t.excluded_all) third.push(balCall(t.token, e, rugAt - 1));
  }
  const got = third.length ? await rpcSend(surl, third, per) : [];
  let i = 0;
  if (how) { pr.ok = wordAddr(got[0]) === pair; if (!pr.ok) pr.why = "FACTORY_DOES_NOT_KNOW_PAIR"; i = 1; }
  if (snap) {
    out.b = rugAt;
    const keep = logs.filter((lg) => lg[0] <= rugAt);
    out.logs = keep;
    const t2 = ts(got[i], rugAt);
    out.end_ts = t2;
    const txs = [...new Set(keep.filter((lg) => lg[0] === rugAt).map((lg) => lg[2]))].sort();
    const rug = { block: rugAt, ts: t2, txs, lp_after: probes[probes.length - 1][1] };
    if (t2 <= Number(t.end_time)) {
      const supply = uint(got[i + 1]);
      let lpb = 0n;
      holders.forEach((_, n) => { lpb += uint(got[i + 2 + n]); });
      const ex = t.excluded_all.map((e, n) => [e, uint(got[i + 2 + holders.length + n]).toString()]);
      Object.assign(rug, { supply: supply.toString(), lp_before: lpb.toString(), excluded: ex, denom: denominator(supply, ex).toString() });
    }
    out.rug = rug;
  }
  const view = { window: out };
  if (pr) view.pair = pr;
  return view;
}

export function scanRange(t, cursor, fin) {
  const ch = CHAINS[t.chain];
  const a = cursor >= Number(t.start_block) ? cursor + 1 : Number(t.start_block);
  return [a, Math.min(a + ch.check_blocks - 1, fin)];
}

/** read_check: both RPCs, compared. -> {facts, range} | {reason, detail, range?} */
/** read_check: both RPCs, compared. -> {facts, range} | {reason, detail, range} */
export async function readCheck(chain, t, cursor, first, bFixed = -1) {
  const views = [];
  let rng = [0, 0];
  try {
    const urls = CHAINS[chain].rpcs;
    const a = cursor >= Number(t.start_block) ? cursor + 1 : Number(t.start_block);
    const opened = [];
    for (const u of urls) opened.push(await readOpen(u, chain, t, a));
    const fin = Math.min(opened[0].fin, opened[1].fin);
    rng = scanRange(t, cursor, fin);
    if (bFixed >= 0) {
      const top = rng[0] + CHAINS[chain].check_blocks - 1;
      if (bFixed > fin || bFixed > top) return { reason: "RPC_DISAGREE", detail: "range not finalized here", range: rng };
      rng[1] = bFixed;
    }
    if (rng[0] > rng[1]) return { reason: "NOTHING_NEW", detail: "no new finalized block", range: rng };
    const surls = CHAINS[chain].state;
    for (let n = 0; n < urls.length; n++) views.push(await readWindow(urls[n], surls[n], chain, t, rng[0], rng[1], opened[n], first));
  } catch (e) {
    return { reason: "RPC_UNREADABLE", detail: String(e.message ?? e).slice(0, 60), range: rng };
  }
  if (canon(views[0]) !== canon(views[1])) return { reason: "RPC_DISAGREE", detail: "the two RPCs answer differently", range: rng, views };
  return { facts: views[0], range: rng };
}

export const ROUTERS = {
  ethereum: ["0x7a250d5630b4cf539739df2c5dacb4c659f2488d", "0xd9e1ce17f2641f24ae83637ab66a2cca9c378b9f", "0x3fc91a3afd70395cd496c647d5a6cc9d4b2b7fad", "0x66a9893cc07d91d95644aedd05d03f95e1dba8af"],
  "base-sepolia": ["0x1689e7b1f10000ae47ebfe339a4f69decd19f602", "0x492e6456d9528771018deb9e87ef7750ef184104"],
};
const ZERO = "0x0000000000000000000000000000000000000000", DEAD = "0x000000000000000000000000000000000000dead";
export const teamSenders = (t) => t.excluded_all.filter((a) => a !== t.pair && a !== ZERO && a !== DEAD && !(ROUTERS[t.chain] ?? []).includes(a)).sort();
export const claimBalance = (start, r) => (BigInt(start) < BigInt(r) ? BigInt(start) : BigInt(r));

/** read_claim: both views (log RPC n + state RPC n), compared. */
export async function readClaim(chain, t, holder, rugBlock) {
  const ch = CHAINS[chain], start = Number(t.start_block), senders = teamSenders(t);
  const views = [];
  try {
    for (let n = 0; n < 2; n++) {
      const url = ch.rpcs[n], surl = ch.state[n];
      const st = await rpcSend(surl, [["eth_chainId", []], balCall(t.token, holder, start), balCall(t.token, holder, rugBlock - 1), ["eth_getCode", [holder, "latest"]]], LIMITS[surl].batch);
      if (hexInt(st[0]) !== ch.id) throw new ReadFailed("wrong chain id");
      const code = String(st[3]).trim().toLowerCase();
      if (!code.startsWith("0x")) throw new ReadFailed("code");
      const delegated = code.length === 48 && code.startsWith("0xef0100");
      let hits = [];
      if (senders.length) {
        const calls = [];
        for (let w = start; w <= rugBlock;) { const z = Math.min(w + LIMITS[url].span - 1, rugBlock); calls.push(["eth_getLogs", [{ address: t.token, topics: [TRANSFER, senders.map(pad), pad(holder)], fromBlock: hex(w), toBlock: hex(z) }]]); w = z + 1; }
        for (const part of await rpcSend(url, calls, 1)) {
          if (!Array.isArray(part)) throw new ReadFailed("logs");
          for (const lg of part) {
            if (!lg || lg.removed === true) throw new ReadFailed("log");
            const tp = lg.topics ?? [];
            if (addr(lg.address) !== t.token || tp.length !== 3 || String(tp[0]).toLowerCase() !== TRANSFER) continue;
            const frm = wordAddr(tp[1]), blk = hexInt(lg.blockNumber), txh = hash32(lg.transactionHash);
            if (!senders.includes(frm) || wordAddr(tp[2]) !== holder || blk < start || blk > rugBlock || !txh) throw new ReadFailed("log fields");
            hits.push([blk, txh, frm]);
          }
        }
      }
      hits.sort((x, y) => x[0] - y[0] || (x[1] < y[1] ? -1 : x[1] > y[1] ? 1 : 0) || (x[2] < y[2] ? -1 : 1));
      views.push({ start_balance: uint(st[1]), balance: uint(st[2]), code: code.length > 2 && !delegated, delegated, from_team: hits.slice(0, 5) });
    }
  } catch (e) { return { reason: "RPC_UNREADABLE", detail: String(e.message ?? e).slice(0, 60) }; }
  if (canon(views[0]) !== canon(views[1])) return { reason: "RPC_DISAGREE", detail: "the two RPCs answer differently" };
  return views[0];
}

/** Feasibility only: a holder's balance at R-1 and code (the study's holder table). */
export async function readHolder(chain, token, holder, rugBlock) {
  const ch = CHAINS[chain];
  const views = [];
  try {
    for (const url of ch.state) {
      const a = await rpcSend(url, [["eth_chainId", []], balCall(token, holder, rugBlock - 1), ["eth_getCode", [holder, "latest"]]], LIMITS[url].batch);
      if (hexInt(a[0]) !== ch.id) throw new ReadFailed("wrong chain id");
      const code = String(a[2]).trim().toLowerCase();
      if (!code.startsWith("0x")) throw new ReadFailed("code");
      const delegated = code.length === 48 && code.startsWith("0xef0100");
      views.push({ balance: uint(a[1]), code: code.length > 2 && !delegated, delegated });
    }
  } catch (e) { return { reason: "RPC_UNREADABLE", detail: String(e.message ?? e).slice(0, 60) }; }
  if (canon(views[0]) !== canon(views[1])) return { reason: "RPC_DISAGREE", detail: "the two RPCs answer differently" };
  return views[0];
}

// --- the rule (mirror of judge_scan / share_of) -------------------------------
export function judgeScan(t, facts) {
  const floor = BigInt(t.min_lp), end = Number(t.end_time), r = facts.rug;
  if (r) return r.ts <= end ? { verdict: "RUGGED", cursor: r.block, block: r.block } : { verdict: "HELD", cursor: r.block - 1, block: 0 };
  for (const p of facts.probes ?? []) if (BigInt(p[1]) < floor) return { verdict: "PENDING", cursor: -1, block: 0 };
  if (facts.end_ts >= end) return { verdict: "HELD", cursor: facts.b, block: 0 };
  return { verdict: "SCANNED", cursor: facts.b, block: 0 };
}
export function shareOf(amount, balance, denom) {
  amount = BigInt(amount); balance = BigInt(balance); denom = BigInt(denom);
  if (denom <= 0n || balance <= 0n || amount <= 0n) return 0n;
  const s = (amount * balance) / denom;
  return s < amount ? s : amount;
}

/** Every check a bond needs until a verdict, from this machine (the keeper's preview and the feasibility study). */
export async function scanToVerdict(t, { maxChecks = 500, onCheck = null } = {}) {
  let cursor = 0, first = true;
  const checks = [];
  for (let i = 0; i < maxChecks; i++) {
    let r = null;
    for (let k = 0; k < 4; k++) { r = await readCheck(t.chain, t, cursor, first); if (r.facts || r.reason === "NOTHING_NEW") break; await sleep(4000 * (k + 1)); }
    if (!r.facts) return { verdict: "PENDING", reason: r.reason, detail: r.detail, checks, cursor };
    const f = r.facts;
    if (first && !f.pair.ok) return { verdict: "VOID", reason: f.pair.why, checks, cursor, pair: f.pair };
    const j = judgeScan(t, f.window);
    checks.push({ range: r.range, verdict: j.verdict, b: f.window.b, logs: f.window.logs.length, probes: f.window.probes, end_ts: f.window.end_ts });
    if (onCheck) onCheck(checks[checks.length - 1], f);
    if (j.verdict === "RUGGED" || j.verdict === "HELD") return { verdict: j.verdict, checks, facts: f, cursor: j.cursor, pair: first ? f.pair : undefined };
    if (j.verdict === "PENDING") return { verdict: "PENDING", reason: "MALFORMED", checks, cursor };
    cursor = j.cursor;
    first = false;
  }
  return { verdict: "SCANNED", checks, cursor };
}
