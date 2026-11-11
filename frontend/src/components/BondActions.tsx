"use client";
import { useState } from "react";
import { send, viewOf } from "@/lib/contract";
import { useWallet } from "./WalletProvider";
import { TxStatus } from "./TxStatus";
import type { Bond, TxProgress } from "@/lib/types";

/** Anyone may file the next rug check or settle a bond that is due. */
export function BondActions({ address, bond }: { address: string; bond: Pick<Bond, "bond_id" | "status" | "checkable" | "due" | "team" | "victim_fund" | "n_checks"> }) {
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
    const payee = bond.due === "RETURN" ? bond.team : bond.victim_fund;
    await send(w.account, address, "settle", [bond.bond_id], 0n, { payee, onProgress: setP,
      confirm: async () => ["CLOSED", "RETURNED", "UNRESOLVED"].includes((await viewOf<Bond>(address, "get_bond", [bond.bond_id, now()], true)).status) });
  }
  if (!bond.checkable && !bond.due) return null;
  return (
    <div className="sticker" style={{ marginTop: 16 }}>
      <div className="row">
        {bond.checkable ? <button className="btn" onClick={() => void check()} disabled={!w.account || w.onWrongNetwork}>Run a rug check</button> : null}
        {bond.due ? <button className="btn pink" onClick={() => void settle()} disabled={!w.account || w.onWrongNetwork}>Settle ({bond.due === "RETURN" ? "bond back to the team" : "to the victim fund"})</button> : null}
        {!w.account ? <span className="small">Connect a wallet: anyone may check or settle.</span> : null}
      </div>
      <TxStatus p={p} />
    </div>
  );
}
