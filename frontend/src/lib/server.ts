/**
 * Server-side reads from Studio Dev (pages and API routes). Every number on
 * the site comes from one of these views or from the keeper's status file on
 * the keeper-state branch; nothing is cached longer than the page's
 * revalidate window.
 */
import "server-only";
import { createClient } from "genlayer-js";
import { studioDevnet } from "genlayer-js/chains";
import type { Bond, Check, Claim, GateAnswer, Page, Stats } from "./types";
import { REPO } from "./deployments";

const client = createClient({ chain: studioDevnet });

export function plain(v: unknown): unknown {
  if (v instanceof Map) return Object.fromEntries([...v.entries()].map(([k, x]) => [String(k), plain(x)]));
  if (Array.isArray(v)) return v.map(plain);
  if (typeof v === "bigint") return Number(v) <= Number.MAX_SAFE_INTEGER ? Number(v) : v.toString();
  return v;
}

/** Studio meters reads per IP per minute: identical reads within 15 s are served once per instance, and a read
 *  already in flight is shared rather than sent twice. */
const memo = new Map<string, { at: number; value: unknown }>();
const inflight = new Map<string, Promise<unknown>>();
const MEMO_MS = 15_000;
const MEMO_MAX = 2000;
/** Lists are walked page by page up to this many pages (50 items each); beyond it a page says it was cut. */
export const MAX_PAGES = 40;
const ATTEMPTS = 5;

/** Exponential backoff with jitter; a per-minute rate limit waits for the minute to roll over. */
export function backoffMs(attempt: number, limited: boolean): number {
  const base = limited ? 12_000 : 800 * 2 ** attempt;
  return Math.min(base, 30_000) + Math.floor(Math.random() * 400);
}

export async function view<T>(address: string, fn: string, args: unknown[] = []): Promise<T> {
  const key = `${address.toLowerCase()}|${fn}|${JSON.stringify(args)}`;
  const hit = memo.get(key);
  if (hit && Date.now() - hit.at < MEMO_MS) return hit.value as T;
  const running = inflight.get(key);
  if (running) return running as Promise<T>;
  const work = (async () => {
    let last: unknown;
    for (let i = 0; i < ATTEMPTS; i++) {
      try {
        const r = await client.readContract({ address: address as `0x${string}`, functionName: fn, args: args as never });
        const value = (typeof r === "string" ? JSON.parse(r) : plain(r)) as T;
        if (memo.size >= MEMO_MAX) memo.delete(memo.keys().next().value as string);
        memo.set(key, { at: Date.now(), value });
        return value;
      } catch (e) {
        last = e;
        const limited = /rate limit|-32029|429/i.test(String((e as Error)?.message ?? e));
        if (i < ATTEMPTS - 1) await new Promise((res) => setTimeout(res, backoffMs(i, limited)));
      }
    }
    throw last;
  })();
  inflight.set(key, work);
  try { return await work; } finally { inflight.delete(key); }
}

/** Every page of a list view, at most MAX_PAGES of them; `truncated` says when there was more. */
async function walk<T>(address: string, fn: string, pre: unknown[], post: unknown[] = []): Promise<T[] & { truncated?: boolean }> {
  const out: T[] & { truncated?: boolean } = [];
  for (let off = 0, pages = 0; ; pages++) {
    if (pages >= MAX_PAGES) { out.truncated = true; return out; }
    const p = await view<Page<T>>(address, fn, [...pre, off, 50, ...post]);
    out.push(...(p.items ?? []));
    if (p.next_offset === -1 || p.next_offset === undefined || p.next_offset <= off) return out;
    off = p.next_offset;
  }
}

/** One page of a list view, for pages that show a window rather than everything. */
export const page = <T>(address: string, fn: string, args: unknown[], offset: number, limit = 50) =>
  view<Page<T>>(address, fn, [...args, Math.max(0, offset), Math.min(Math.max(1, limit), 50)]);

const now = () => Math.floor(Date.now() / 1000);
export const allBonds = (reg: string) => walk<Bond>(reg, "list_bonds", [], [now()]);
export const bond = (reg: string, id: number) => view<Bond>(reg, "get_bond", [id, now()]);
export const bondChecks = (reg: string, id: number) => walk<Check>(reg, "list_checks", [id]);
export const bondClaims = (reg: string, id: number) => walk<Claim>(reg, "list_claims", [id]);
export const holderClaims = (reg: string, a: string) => walk<Claim>(reg, "holder_claims", [a]);
export const teamBonds = (reg: string, a: string) => walk<Bond>(reg, "bonds_by_team", [a], [now()]);
export const claimOf = (reg: string, id: number, a: string) => view<Claim & { found: boolean; beneficiary: string }>(reg, "get_claim", [id, a]);
export const stats = (reg: string) => view<Stats>(reg, "get_stats", []);
export const config = (reg: string) => view<Record<string, unknown>>(reg, "get_config", []);
/** LaunchGate reads are bound: (token, bond id) or (token, team). */
export const gateCheck = (gate: string, token: string, id: number) => view<GateAnswer>(gate, "check_for", [token, id]);
export const gateTeam = (gate: string, token: string, team: string) => view<GateAnswer>(gate, "is_safe_for", [token, team]);

/** eth_getBalance on Studio Dev, wei. */
export async function balanceOf(address: string): Promise<bigint> {
  const r = await fetch(studioDevnet.rpcUrls.default.http[0], { method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "eth_getBalance", params: [address, "latest"] }), cache: "no-store" });
  const j = await r.json();
  return BigInt(j.result ?? "0x0");
}

export interface KeeperAction { key: string; kind: string; bond_id: number; status: string; result: string; tx: string; attempts: number; last_error: string }
export interface KeeperStatus {
  keeper: string; started_at: string; finished_at: string; trigger: string; run_url: string;
  contracts: Record<string, { address: string; last_run: Record<string, number>; totals: Record<string, unknown>;
    bonds: Record<string, { status: string; chain: string; cursor: number; cursor_ts: number; n_checks: number; n_pending: number; last_result: string;
      due: string; name: string; waiting?: string; claims_seen?: number; claims_paid?: string }>;
    unprocessed: { key: string; why: string }[]; actions: KeeperAction[] }>;
  history: { started_at: string; finished_at: string; trigger: string; run_url: string; runs: Record<string, Record<string, number>> }[];
}

/** The keeper's status.json on the keeper-state branch (raw GitHub, revalidated every minute). */
export async function keeperStatus(): Promise<KeeperStatus | null> {
  const raw = REPO.replace("https://github.com/", "https://raw.githubusercontent.com/") + "/keeper-state/status.json";
  try {
    const r = await fetch(raw, { next: { revalidate: 60 } });
    if (!r.ok) return null;
    return (await r.json()) as KeeperStatus;
  } catch {
    return null;
  }
}

