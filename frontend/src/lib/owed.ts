import "server-only";
import { ADDR, type Reg } from "./deployments";
import { allBonds, holderClaims } from "./server";
import { holderAt } from "./evm";
import type { Bond, Claim } from "./types";

export type OwedRow = { reg: Reg; bond: Pick<Bond, "bond_id" | "name" | "chain" | "token" | "status" | "rug_block" | "claim_deadline" | "denominator" | "amount" | "replay">;
  state: "CLAIMED" | "CLAIMABLE" | "EXCLUDED" | "CONTRACT" | "NO_BALANCE" | "BELOW_DUST" | "WINDOW_OVER" | "UNREADABLE";
  balance: string; share: string; claim: Claim | null };

/** Every RUGGED or CLOSED bond on both registries, and what `a` held at its R-1 and is owed (an estimate until claimed). */
export async function owed(a: string): Promise<{ address: string; rows: OwedRow[]; scanned: number }> {
  const address = a.toLowerCase();
  const rows: OwedRow[] = [];
  let scanned = 0;
  for (const reg of ["canonical", "demo"] as Reg[]) {
    const addr = reg === "demo" ? ADDR.registryDemo : ADDR.registry;
    if (!addr) continue;
    const [bonds, claims] = await Promise.all([allBonds(addr), holderClaims(addr, address)]);
    for (const b of bonds) {
      if (!["RUGGED", "CLOSED"].includes(b.status)) continue;
      scanned++;
      const claim = claims.find((c) => c.bond_id === b.bond_id) ?? null;
      const base = { reg, bond: { bond_id: b.bond_id, name: b.name, chain: b.chain, token: b.token, status: b.status, rug_block: b.rug_block,
        claim_deadline: b.claim_deadline, denominator: b.denominator, amount: b.amount, replay: b.replay }, claim };
      if (claim) { rows.push({ ...base, state: "CLAIMED", balance: claim.balance, share: claim.share }); continue; }
      if (b.excluded_all.includes(address)) { rows.push({ ...base, state: "EXCLUDED", balance: "0", share: "0" }); continue; }
      const h = await holderAt(b.chain, b.token, address, b.rug_block);
      if (!h) { rows.push({ ...base, state: "UNREADABLE", balance: "0", share: "0" }); continue; }
      if (BigInt(h.balance) === 0n) continue;
      const denom = BigInt(b.denominator || "0");
      let share = denom > 0n ? (BigInt(b.amount) * BigInt(h.balance)) / denom : 0n;
      if (share > BigInt(b.remaining)) share = BigInt(b.remaining);
      const state = h.contract ? "CONTRACT" : b.status !== "RUGGED" || Date.now() / 1000 > b.claim_deadline ? "WINDOW_OVER"
        : share === 0n || share < BigInt(b.dust_floor) ? "BELOW_DUST" : "CLAIMABLE";
      rows.push({ ...base, state, balance: h.balance, share: share.toString() });
    }
  }
  return { address, rows, scanned };
}
