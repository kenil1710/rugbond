// The contract's reads and rule, in JavaScript, for this machine: the
// feasibility study, the keeper's predictions, the real-world check and the
// site. Same calls, same field order, same canonical JSON as
// contracts/shared/{common,rpc}.py, so a read here can be compared byte for
// byte with the one GenVM stored (tools/feasibility.mjs does).
import { CHAINS, TRANSFER } from "./chains.mjs";

export const MAX_PROBES = 6;
export const BATCH = { ethereum: 12, base: 3, "base-sepolia": 12 };
const FACTORIES = {
  ethereum: { "0x5c69bee701ef814a2b6a3edd4b1652cb9cc5aa6f": "getPair", "0xc0aee478e3658e2610c5f7a4a2e1777ce9e4f2ac": "getPair" },
  base: { "0x8909dc15e40173ff4699343b6eb8132c65e18ec6": "getPair", "0x71524b4f93c58fcbf659783284e38825f0622859": "getPair",
    "0x420dd381b31aef6683db6b902084cb0ffece40da": "getPool" },
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
export async function rpcSend(url, calls, per, { tries = 4 } = {}) {
  const out = [];
  for (let i = 0; i < calls.length; i += per) {
    const chunk = calls.slice(i, i + per);
    const body = JSON.stringify(chunk.map((c, j) => ({ jsonrpc: "2.0", id: j, method: c[0], params: c[1] })));
    let got = null, why = "";
    for (let k = 0; k < tries && got === null; k++) {
      if (k) { stats.retries++; await sleep(1500 * k); }
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
          if (it.error) throw new ReadFailed("rpc error: " + JSON.stringify(it.error).slice(0, 80));
          if (!("result" in it)) throw new ReadFailed("no result");
          res.push(it.result);
        }
        got = res;
      } catch (e) { why = String(e.message ?? e).slice(0, 100); }
    }
    if (got === null) throw new ReadFailed(why);
    out.push(...got);
  }
  return out;
}

export async function readHead(url, chain) {
  const ch = CHAINS[chain];
  const a = await rpcSend(url, [["eth_chainId", []], ["eth_getBlockByNumber", ["finalized", false]]], BATCH[chain]);
  if (hexInt(a[0]) !== ch.id) throw new ReadFailed("wrong chain id");
  const fin = a[1] && typeof a[1] === "object" ? hexInt(a[1].number) : -1;
  if (fin < 0) throw new ReadFailed("no finalized head");
  return fin;
}

function ts(h, n) {
  if (!h || typeof h !== "object" || hexInt(h.number) !== n) throw new ReadFailed("header");
  const t = hexInt(h.timestamp);
  if (t <= 0) throw new ReadFailed("timestamp");
  return t;
}

export async function readPair(url, chain, t) {
  const per = BATCH[chain], p = t.pair;
  const a = await rpcSend(url, [["eth_call", [{ to: p, data: "0x0dfe1681" }, "latest"]], ["eth_call", [{ to: p, data: "0xd21220a7" }, "latest"]],
    ["eth_call", [{ to: p, data: "0xc45a0155" }, "latest"]]], per);
  const t0 = wordAddr(a[0]), t1 = wordAddr(a[1]), fac = wordAddr(a[2]);
  const out = { token0: t0, token1: t1, factory: fac, ok: false, why: "" };
  if (!t0 || !t1 || !fac) { out.why = "NOT_A_PAIR"; return out; }
  if (t.token !== t0 && t.token !== t1) { out.why = "TOKEN_NOT_IN_PAIR"; return out; }
  const how = FACTORIES[chain]?.[fac] ?? "";
  if (!how) { out.why = "UNKNOWN_FACTORY"; return out; }
  let data = (how === "getPair" ? "0xe6a43905" : "0x79bc57d5") + "0".repeat(24) + t0.slice(2) + "0".repeat(24) + t1.slice(2);
  if (how === "getPool") data += "0".repeat(64);
  const b = await rpcSend(url, [["eth_call", [{ to: fac, data }, "latest"]]], per);
  if (wordAddr(b[0]) !== p) { out.why = "FACTORY_DOES_NOT_KNOW_PAIR"; return out; }
  out.ok = true;
  return out;
}

export function denominator(supply, excluded) {
  let d = BigInt(supply);
  for (const e of excluded) d -= BigInt(e[1]);
  return d > 0n ? d : 0n;
}

export async function readWindow(url, chain, t, a, b) {
  const ch = CHAINS[chain], per = BATCH[chain], pair = t.pair, holders = t.lp_holders, start = Number(t.start_block), floor = BigInt(t.min_lp);
  const topics = [TRANSFER, holders.map(pad)];
  const calls = [];
  for (let w = a; w <= b;) { const z = Math.min(w + ch.span - 1, b); calls.push(["eth_getLogs", [{ address: pair, topics, fromBlock: hex(w), toBlock: hex(z) }]]); w = z + 1; }
  const got = await rpcSend(url, calls, 1);
  let logs = [];
  for (const part of got) {
    if (!Array.isArray(part)) throw new ReadFailed("logs");
    for (const lg of part) {
      if (!lg || typeof lg !== "object" || lg.removed === true) throw new ReadFailed("log");
      const tp = lg.topics ?? [];
      if (addr(lg.address) !== pair || !Array.isArray(tp) || tp.length !== 3 || String(tp[0]).toLowerCase() !== TRANSFER) continue;
      const frm = wordAddr(tp[1]), to = wordAddr(tp[2]), amt = wordUint(lg.data), blk = hexInt(lg.blockNumber), li = hexInt(lg.logIndex), txh = hash32(lg.transactionHash);
      if (!holders.includes(frm) || !to || amt < 0n || blk < a || blk > b || li < 0 || !txh) throw new ReadFailed("log fields");
      logs.push([blk, li, txh, frm, to, amt.toString()]);
    }
  }
  logs.sort((x, y) => (x[0] * 1000000 + x[1]) - (y[0] * 1000000 + y[1]));
  let pb = [];
  if (a === start) pb.push(start);
  for (const lg of logs) if (!pb.includes(lg[0])) pb.push(lg[0]);
  if (pb.length > MAX_PROBES) { b = pb[MAX_PROBES] - 1; pb = pb.slice(0, MAX_PROBES); logs = logs.filter((lg) => lg[0] <= b); }
  const probes = [];
  let rugAt = -1;
  if (pb.length) {
    const sc = [];
    for (const blk of pb) for (const h of holders) sc.push(balCall(pair, h, blk));
    const vals = await rpcSend(url, sc, per);
    let k = 0;
    for (const blk of pb) {
      let s = 0n;
      for (const _ of holders) s += uint(vals[k++]);
      probes.push([blk, s.toString()]);
      if (s < floor) { rugAt = blk; break; }
    }
  }
  const out = { a, b, logs, probes, rug: null, end_ts: 0 };
  if (rugAt < 0) {
    const hb = await rpcSend(url, [["eth_getBlockByNumber", [hex(b), false]]], per);
    out.end_ts = ts(hb[0], b);
    return out;
  }
  out.b = rugAt;
  const keep = logs.filter((lg) => lg[0] <= rugAt);
  out.logs = keep;
  const hr = await rpcSend(url, [["eth_getBlockByNumber", [hex(rugAt), false]]], per);
  const t2 = ts(hr[0], rugAt);
  out.end_ts = t2;
  const txs = [...new Set(keep.filter((lg) => lg[0] === rugAt).map((lg) => lg[2]))].sort();
  const rug = { block: rugAt, ts: t2, txs, lp_after: probes[probes.length - 1][1] };
  if (t2 <= Number(t.end_time)) {
    const sc = [["eth_call", [{ to: t.token, data: "0x18160ddd" }, hex(rugAt - 1)]]];
    for (const h of holders) sc.push(balCall(pair, h, rugAt - 1));
    for (const e of t.excluded_all) sc.push(balCall(t.token, e, rugAt - 1));
    const vals = await rpcSend(url, sc, per);
    const supply = uint(vals[0]);
    let lpb = 0n;
    holders.forEach((_, i) => { lpb += uint(vals[1 + i]); });
    const ex = t.excluded_all.map((e, i) => [e, uint(vals[1 + holders.length + i]).toString()]);
    Object.assign(rug, { supply: supply.toString(), lp_before: lpb.toString(), excluded: ex, denom: denominator(supply, ex).toString() });
  }
  out.rug = rug;
  return out;
}

export function scanRange(t, cursor, fin) {
  const ch = CHAINS[t.chain];
  const a = cursor >= Number(t.start_block) ? cursor + 1 : Number(t.start_block);
  return [a, Math.min(a + ch.span * ch.windows - 1, fin)];
}

/** read_check: both RPCs, compared. -> {facts, range} | {reason, detail, range?} */
export async function readCheck(chain, t, cursor, first, bFixed = -1) {
  const views = [];
  let rng;
  try {
    const heads = [];
    for (const url of CHAINS[chain].rpcs) heads.push(await readHead(url, chain));
    const fin = Math.min(...heads);
    rng = scanRange(t, cursor, fin);
    if (bFixed >= 0) {
      const top = rng[0] + CHAINS[chain].span * CHAINS[chain].windows - 1;
      if (bFixed > fin || bFixed > top) return { reason: "RPC_DISAGREE", detail: "range not finalized here", range: rng };
      rng[1] = bFixed;
    }
    if (rng[0] > rng[1]) return { reason: "NOTHING_NEW", detail: "no new finalized block", range: rng };
    for (const url of CHAINS[chain].rpcs) {
      const v = { window: await readWindow(url, chain, t, rng[0], rng[1]) };
      if (first) v.pair = await readPair(url, chain, t);
      views.push(v);
    }
  } catch (e) {
    return { reason: "RPC_UNREADABLE", detail: String(e.message ?? e).slice(0, 60), ...(rng ? { range: rng } : {}) };
  }
  if (canon(views[0]) !== canon(views[1])) return { reason: "RPC_DISAGREE", detail: "the two RPCs answer differently", range: rng, views };
  return { facts: views[0], range: rng };
}

export async function readHolder(chain, token, holder, rugBlock) {
  const ch = CHAINS[chain];
  const views = [];
  try {
    for (const url of ch.rpcs) {
      const a = await rpcSend(url, [["eth_chainId", []], balCall(token, holder, rugBlock - 1), ["eth_getCode", [holder, "latest"]]], BATCH[chain]);
      if (hexInt(a[0]) !== ch.id) throw new ReadFailed("wrong chain id");
      const code = String(a[2]).trim().toLowerCase();
      if (!code.startsWith("0x")) throw new ReadFailed("code");
      views.push({ balance: uint(a[1]).toString(), code: code.length > 2 });
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
