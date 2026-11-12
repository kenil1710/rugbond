"use client";
import { useState } from "react";
import { send, viewOf } from "@/lib/contract";
import { useWallet } from "./WalletProvider";
import { TxStatus } from "./TxStatus";
import type { Bond, TxProgress } from "@/lib/types";

/** Anyone may file the next rug check or settle a bond that is due. */
export function BondActions({ address, bond, unpaid = [] }: { address: string; bond: Pick<Bond, "bond_id" | "status" | "checkable" | "due" | "team" | "fund" | "n_checks">; unpaid?: { holder: string; payee: string }[] }) {
  const w = useWallet();
  const [p, setP] = useState<TxProgress | null>(null);
  const now = () => Math.floor(Date.now() / 1000);
  async function check() {
    if (!w.account) return;
    await send<{ result: string }>(w.account, address, "check", [bond.bond_id], 0n, { onProgress: setP,
      confirm: async () => (await viewOf<Bond>(address, "get_bond", [bond.bond_id, now()], true)).n_checks > bond.n_checks });
  }
  async function settle() {
    if (!w.account) return;
    // RETURN pays the team, REDISTRIBUTE pays nobody yet (it sets the unclaimed part aside), anything else the registry's fund
    const payee = bond.due === "RETURN" ? bond.team : bond.due === "REDISTRIBUTE" ? null : bond.fund;
    await send(w.account, address, "settle", [bond.bond_id], 0n, { payee, onProgress: setP,
      confirm: async () => (await viewOf<Bond>(address, "get_bond", [bond.bond_id, now()], true)).status !== bond.status });
  }
  async function bonus() {
    if (!w.account || !unpaid.length) return;
    const c = unpaid[0];
    await send(w.account, address, "pay_bonus", [bond.bond_id, c.holder], 0n, { payee: c.payee, onProgress: setP,
      confirm: async () => (await viewOf<{ bonus_paid?: boolean }>(address, "get_claim", [bond.bond_id, c.holder], true)).bonus_paid === true });
  }
  const settleText: Record<string, string> = { RETURN: "bond back to the team", REDISTRIBUTE: "share the unclaimed GEN among the claimants", FUND: "the rest to the registry's fund" };
  if (!bond.checkable && !bond.due && !unpaid.length) return null;
  return (
    <div className="sticker" style={{ marginTop: 16 }}>
      <div className="row">
        {bond.checkable ? <button className="btn" onClick={() => void check()} disabled={!w.account || w.onWrongNetwork}>Run a rug check</button> : null}
        {bond.due ? <button className="btn pink" onClick={() => void settle()} disabled={!w.account || w.onWrongNetwork}>Settle ({settleText[bond.due] ?? bond.due})</button> : null}
        {bond.status === "REDISTRIBUTING" && unpaid.length ? <button className="btn pink" onClick={() => void bonus()} disabled={!w.account || w.onWrongNetwork}>Pay the next bonus ({unpaid.length} left)</button> : null}
        {!w.account ? <span className="small">Connect a wallet: anyone may check, settle or pay a bonus.</span> : null}
      </div>
      <TxStatus p={p} />
    </div>
  );
}
