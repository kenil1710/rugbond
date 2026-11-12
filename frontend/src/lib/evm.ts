/**
 * Server-side EVM reads for display: the LP line on a bond page and the
 * "Am I owed?" estimate. The contract's verdicts and payouts never depend on
 * these; they are previews read from the chain's first RPC, cached.
 */
import "server-only";
import type { Bond } from "./types";

export const RPCS: Record<string, string[]> = {
  ethereum: ["https://gateway.tenderly.co/public/mainnet", "https://rpc.mevblocker.io"],
  "base-sepolia": ["https://base-sepolia.gateway.tenderly.co", "https://base-sepolia-rpc.publicnode.com"],
};
const hex = (n: number) => "0x" + n.toString(16);
const memo = new Map<string, { at: number; v: unknown }>();

async function rpc(chain: string, calls: [string, unknown[]][], ttl = 600_000): Promise<unknown[]> {
  const key = chain + JSON.stringify(calls);
  const hit = memo.get(key);
  if (hit && Date.now() - hit.at < ttl) return hit.v as unknown[];
  let last = "";
  for (const url of RPCS[chain] ?? []) {
    for (let i = 0; i < 3; i++) {
      try {
        const out: unknown[] = [];
        for (let k = 0; k < calls.length; k += 4) {
          const chunk = calls.slice(k, k + 4);
          const r = await fetch(url, { method: "POST", headers: { "content-type": "application/json" }, cache: "no-store", signal: AbortSignal.timeout(15000),
            body: JSON.stringify(chunk.map((c, j) => ({ jsonrpc: "2.0", id: j, method: c[0], params: c[1] }))) });
          const j = (await r.json()) as { id: number; result?: unknown; error?: unknown }[];
          if (!Array.isArray(j)) throw new Error("not a batch");
          for (let n = 0; n < chunk.length; n++) {
            const it = j.find((x) => x.id === n);
            if (!it || it.error !== undefined) throw new Error("rpc error");
            out.push(it.result);
          }
        }
        if (memo.size > 500) memo.delete(memo.keys().next().value as string);
        memo.set(key, { at: Date.now(), v: out });
        return out;
      } catch (e) { last = String((e as Error).message); await new Promise((r) => setTimeout(r, 600 * 2 ** i)); }
    }
  }
  throw new Error("chain unreadable: " + last);
}

const bal = (token: string, who: string, blk: number): [string, unknown[]] =>
  ["eth_call", [{ to: token, data: "0x70a08231" + "0".repeat(24) + who.slice(2).toLowerCase() }, hex(blk)]];

export type Point = { block: number; ts: number; lp: string };

/** The LP holders' summed balance at ~28 blocks from the start to the rug (or the last block read) and a little after. */
export async function lpSeries(b: Bond): Promise<{ points: Point[]; to: number } | null> {
  if (!RPCS[b.chain] || !b.cursor) return null;
  const end = b.rug_block ? b.rug_block : b.cursor;
  const from = b.start_block;
  const span = Math.max(end - from, 1);
  const after = b.rug_block ? Math.min(Math.ceil(span * 0.15) + 2, Math.max(b.cursor - b.rug_block, 0) + 2000) : 0;
  const blocks = new Set<number>([from, end]);
  for (let i = 1; i < 24; i++) blocks.add(from + Math.floor((span * i) / 24));
  if (b.rug_block) { blocks.add(b.rug_block - 1); for (let i = 1; i <= 3; i++) blocks.add(b.rug_block + Math.floor((after * i) / 3)); }
  const list = [...blocks].filter((x) => x > 0).sort((x, y) => x - y);
  const calls: [string, unknown[]][] = [];
  for (const blk of list) {
    calls.push(["eth_getBlockByNumber", [hex(blk), false]]);
    for (const h of b.lp_holders) calls.push(bal(b.pair, h, blk));
  }
  try {
    const r = await rpc(b.chain, calls);
    const points: Point[] = [];
    let k = 0;
    for (const blk of list) {
      const head = r[k++] as { timestamp?: string } | null;
      let s = 0n;
      for (let i = 0; i < b.lp_holders.length; i++) s += BigInt((r[k++] as string) || "0x0");
      if (head?.timestamp) points.push({ block: blk, ts: Number(BigInt(head.timestamp)), lp: s.toString() });
    }
    return { points, to: list[list.length - 1] };
  } catch {
    return null;
  }
}

const ROUTERS: Record<string, string[]> = {
  ethereum: ["0x7a250d5630b4cf539739df2c5dacb4c659f2488d", "0xd9e1ce17f2641f24ae83637ab66a2cca9c378b9f", "0x3fc91a3afd70395cd496c647d5a6cc9d4b2b7fad", "0x66a9893cc07d91d95644aedd05d03f95e1dba8af"],
  "base-sepolia": ["0x1689e7b1f10000ae47ebfe339a4f69decd19f602", "0x492e6456d9528771018deb9e87ef7750ef184104"],
};
const SPAN: Record<string, number> = { ethereum: 80000, "base-sepolia": 40000 };
const pad = (a: string) => "0x" + "0".repeat(24) + a.slice(2).toLowerCase();
const TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef";

/** What the contract reads for a claim, previewed from one RPC: balances at the start block and R-1, code,
 *  and the summed amount of direct transfers from a team sender after the start block up to R.
 *  balance = max(0, min(start, R-1) - fromTeam). */
export async function claimPreview(b: Bond, holder: string): Promise<{ start: string; atR: string; balance: string; contract: boolean; fromTeam: string } | null> {
  const h = holder.toLowerCase();
  const senders = b.excluded_all.filter((a) => a !== b.pair && a !== "0x0000000000000000000000000000000000000000" && a !== "0x000000000000000000000000000000000000dead" && !(ROUTERS[b.chain] ?? []).includes(a));
  try {
    const calls: [string, unknown[]][] = [bal(b.token, h, b.start_block), bal(b.token, h, b.rug_block - 1), ["eth_getCode", [h, "latest"]]];
    for (let w = b.start_block + 1; w <= b.rug_block && senders.length;) { const z = Math.min(w + SPAN[b.chain] - 1, b.rug_block);
      calls.push(["eth_getLogs", [{ address: b.token, topics: [TRANSFER, senders.map(pad), pad(h)], fromBlock: hex(w), toBlock: hex(z) }]]); w = z + 1; }
    const r = await rpc(b.chain, calls, 60_000);
    const start = BigInt((r[0] as string) || "0x0"), atR = BigInt((r[1] as string) || "0x0");
    const c = String(r[2] ?? "0x").toLowerCase();
    const delegated = c.length === 48 && c.startsWith("0xef0100");
    let fromTeam = 0n;
    for (const part of r.slice(3)) for (const lg of (Array.isArray(part) ? part : []) as { data?: string }[]) fromTeam += BigInt(lg.data && lg.data !== "0x" ? lg.data : "0x0");
    const m = (start < atR ? start : atR) - fromTeam;
    return { start: start.toString(), atR: atR.toString(), balance: (m > 0n ? m : 0n).toString(), contract: c.length > 2 && !delegated, fromTeam: fromTeam.toString() };
  } catch {
    return null;
  }
}
