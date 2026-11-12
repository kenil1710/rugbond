"use client";
import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { viewOf, send } from "@/lib/contract";
import { regAddr, type Reg } from "@/lib/deployments";
import { useWallet } from "@/components/WalletProvider";
import { TxStatus } from "@/components/TxStatus";
import type { Bond, TxProgress } from "@/lib/types";
import { gen, when } from "@/lib/format";

export function ClaimForm() {
  const sp = useSearchParams();
  const w = useWallet();
  const initial = sp.get("bond") ?? "";
  const [id, setId] = useState(initial);
  const [b, setB] = useState<Bond | null>(null);
  const [mine, setMine] = useState<{ found: boolean; share?: string; payee?: string; beneficiary: string } | null>(null);
  const [ben, setBen] = useState("");
  const [p, setP] = useState<TxProgress | null>(null);
  const [err, setErr] = useState("");
  const reg: Reg = id.startsWith("demo-") ? "demo" : "canonical";
  const n = Number(reg === "demo" ? id.slice(5) : id);
  useEffect(() => {
    let live = true;
    if (!Number.isInteger(n) || n <= 0 || !regAddr(reg)) return;
    (async () => {
      try {
        const x = await viewOf<Bond>(regAddr(reg), "get_bond", [n, Math.floor(Date.now() / 1000)]);
        if (live) setB(x.found ? x : null);
        if (w.account) { const c = await viewOf<typeof mine>(regAddr(reg), "get_claim", [n, w.account.toLowerCase()], true); if (live) setMine(c); }
      } catch (e) { if (live) setErr(String((e as Error).message)); }
    })();
    return () => { live = false; };
  }, [n, reg, w.account, p?.phase]);
  async function claim() {
    if (!w.account || !b) return;
    setErr("");
    const payee = mine?.beneficiary || w.account;
    await send(w.account, regAddr(reg), "claim", [n], 0n, { payee, onProgress: setP,
      confirm: async () => (await viewOf<{ found: boolean }>(regAddr(reg), "get_claim", [n, w.account!.toLowerCase()], true)).found });
  }
  async function commit() {
    if (!w.account) return;
    await send(w.account, regAddr(reg), "commit_beneficiary", [n, ben.trim().toLowerCase()], 0n, { onProgress: setP,
      confirm: async () => (await viewOf<{ beneficiary: string }>(regAddr(reg), "get_claim", [n, w.account!.toLowerCase()], true)).beneficiary !== "" });
  }
  return (
    <div className="sticker" style={{ maxWidth: 760 }}>
      <label htmlFor="c-id">Bond (number, or demo-number for the demo registry)</label>
      <input id="c-id" className="mono" value={id} onChange={(e) => { setId(e.target.value.trim()); setB(null); setMine(null); }} placeholder="demo-1" />
      {b ? <p className="small">{b.name} · {b.status} · bond {gen(b.amount)} GEN · {b.status === "RUGGED" ? `claims until ${when(b.claim_deadline)}` : b.rug_block ? "the claim window is over; what nobody claimed goes to the registry's fund" : "claims open only after RUGGED"}</p> : null}
      {!w.account ? <p className="note">Connect a wallet to claim.</p> : null}
      {mine?.found ? <p className="note">You claimed {gen(mine.share)} GEN, paid to <span className="mono">{mine.payee}</span>.</p> : null}
      <div className="row" style={{ marginTop: 12 }}>
        <button className="btn pink" onClick={() => void claim()} disabled={!w.account || w.onWrongNetwork || !b || b.status !== "RUGGED" || mine?.found}>Claim my share</button>
      </div>
      <h3 style={{ marginTop: 24 }}>Beneficiary (optional, once)</h3>
      {mine?.beneficiary ? <p className="small">Committed: <span className="mono">{mine.beneficiary}</span></p> : (
        <div className="row"><input className="mono" value={ben} onChange={(e) => setBen(e.target.value)} placeholder="0x… where your share should go" style={{ flex: "1 1 320px" }} />
          <button className="btn ghost" onClick={() => void commit()} disabled={!w.account || w.onWrongNetwork || !b || !/^0x[0-9a-fA-F]{40}$/.test(ben.trim())}>Commit</button></div>
      )}
      {err && <p className="note warn">{err}</p>}
      <TxStatus p={p} />
    </div>
  );
}
