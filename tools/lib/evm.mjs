// Plain JSON-RPC from Node (feasibility, discovery, keeper, real-world check).
// Every call is bounded (timeout) and retried with backoff on transport errors,
// 429/5xx and rate-limit answers; a JSON-RPC error that is not transient throws.
export const TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef";
export const PAIR_CREATED = "0x0d3648bd0f6ba80134a33ba9275ac585d9d315f0ad8355cddefde31afa28d0e9";
export const AERO_POOL_CREATED = "0x2128d88d14c80cb081c1252a5acff7a264671bf199ce226b53788fb26065005e";
export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const TRANSIENT = /rate|limit|429|5\d\d|timeout|temporar|unavailable|fetch failed|ECONN|busy|exceeded the|Too Many|aborted/i;

let nextId = 1;
export async function rpc(url, method, params, { tries = 6, timeoutMs = 30000 } = {}) {
  let last = "";
  for (let i = 0; i < tries; i++) {
    try {
      const r = await fetch(url, { method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ jsonrpc: "2.0", id: nextId++, method, params }), signal: AbortSignal.timeout(timeoutMs) });
      const txt = await r.text();
      let j;
      try { j = JSON.parse(txt); } catch { last = `http ${r.status}`; await sleep(1500 * (i + 1)); continue; }
      if (j.error) {
        last = JSON.stringify(j.error).slice(0, 160);
        if (TRANSIENT.test(last) && !/range|blocks/i.test(last)) { await sleep(2000 * (i + 1)); continue; }
        throw new Error(`${method}: ${last}`);
      }
      return j.result;
    } catch (e) {
      if (String(e.message).startsWith(method + ":")) throw e;
      last = String(e.message).slice(0, 100);
      await sleep(1500 * (i + 1));
    }
  }
  throw new Error(`${method} unanswered (${url}): ${last}`);
}
export const hex = (n) => "0x" + BigInt(n).toString(16);
export const pad = (a) => "0x" + "0".repeat(24) + a.toLowerCase().slice(2);
export const word = (w) => "0x" + String(w).slice(-40).toLowerCase();
export const callData = (sel, ...addrs) => sel + addrs.map((a) => "0".repeat(24) + a.toLowerCase().slice(2)).join("");
export async function call(url, to, data, block = "latest") {
  return rpc(url, "eth_call", [{ to, data }, typeof block === "number" || typeof block === "bigint" ? hex(block) : block]);
}
export const balanceOf = async (url, token, who, block) => BigInt(await call(url, token, callData("0x70a08231", who), block));
export const totalSupply = async (url, token, block) => BigInt(await call(url, token, "0x18160ddd", block));
export async function reserves(url, pair, block) {
  const r = await call(url, pair, "0x0902f1ac", block);
  return [BigInt("0x" + r.slice(2, 66)), BigInt("0x" + r.slice(66, 130))];
}
export async function block(url, n) { return rpc(url, "eth_getBlockByNumber", [typeof n === "string" ? n : hex(n), false]); }
/** getLogs over [from, to] in windows of `span` blocks. */
export async function logs(url, filter, from, to, span, { pause = 0 } = {}) {
  const out = [];
  for (let a = from; a <= to; a += span) {
    const b = Math.min(to, a + span - 1);
    out.push(...await rpc(url, "eth_getLogs", [{ ...filter, fromBlock: hex(a), toBlock: hex(b) }]));
    if (pause) await sleep(pause);
  }
  return out;
}
