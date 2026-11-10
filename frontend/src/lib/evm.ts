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

/** A holder's token balance at R-1 and whether it has code (EIP-7702 delegations count as EOAs). */
export async function holderAt(chain: string, token: string, holder: string, rugBlock: number): Promise<{ balance: string; contract: boolean } | null> {
  try {
    const [b, code] = await rpc(chain, [bal(token, holder, rugBlock - 1), ["eth_getCode", [holder, "latest"]]], 60_000);
    const c = String(code ?? "0x").toLowerCase();
    const delegated = c.length === 48 && c.startsWith("0xef0100");
    return { balance: BigInt((b as string) || "0x0").toString(), contract: c.length > 2 && !delegated };
  } catch {
    return null;
  }
}
