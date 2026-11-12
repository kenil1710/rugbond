"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { viewOf, send } from "@/lib/contract";
import { regAddr, type Reg } from "@/lib/deployments";
import { useWallet } from "@/components/WalletProvider";
import { TxStatus } from "@/components/TxStatus";
import type { Bond, Page, TxProgress } from "@/lib/types";
import { gen, STATUS } from "@/lib/format";

const toWei = (v: string) => { const [a, b = ""] = v.trim().split("."); return BigInt(a || "0") * 10n ** 18n + BigInt((b + "0".repeat(18)).slice(0, 18) || "0"); };

export function TeamForm() {
  const w = useWallet();
  const [reg, setReg] = useState<Reg>("demo");
  const [f, setF] = useState({ name: "", token: "", pair: "", holders: "", minLp: "", start: "", hours: "24", window: "60", excluded: "", dust: "0", bond: "1" });
  const [p, setP] = useState<TxProgress | null>(null);
  const [mine, setMine] = useState<Bond[]>([]);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value });
  const chain = reg === "demo" ? "base-sepolia" : "ethereum";
  useEffect(() => {
    let live = true;
    if (!w.account || !regAddr(reg)) return;
    viewOf<Page<Bond>>(regAddr(reg), "bonds_by_team", [w.account.toLowerCase(), 0, 50, Math.floor(Date.now() / 1000)], true)
      .then((pg) => { if (live) setMine(pg.items); }).catch(() => {});
    return () => { live = false; };
  }, [w.account, reg, p?.phase]);
  async function create() {
    if (!w.account) return;
    const list = (s: string) => JSON.stringify(s.split(/[\s,]+/).map((x) => x.trim().toLowerCase()).filter(Boolean));
    const end = Math.floor(Date.now() / 1000) + Math.round(Number(f.hours) * 3600);
    await send<{ ok: boolean; bond_id: number }>(w.account, regAddr(reg), "create_bond",
      [f.name, chain, f.token.trim().toLowerCase(), f.pair.trim().toLowerCase(), list(f.holders), toWei(f.minLp).toString(), Number(f.start), end,
        Math.round(Number(f.window) * 60), list(f.excluded), toWei(f.dust).toString()], toWei(f.bond), { onProgress: setP });
  }
  return (
    <>
      <div className="sticker" style={{ maxWidth: 820 }}>
        <label htmlFor="t-reg">Registry</label>
        <select id="t-reg" value={reg} onChange={(e) => setReg(e.target.value as Reg)}><option value="demo">Demo (Base Sepolia, minutes)</option><option value="canonical">Canonical (Ethereum)</option></select>
        <label htmlFor="t-name">Name</label><input id="t-name" value={f.name} onChange={set("name")} placeholder="MYTOKEN liquidity bond" />
        <div className="row">
          <div style={{ flex: "1 1 300px" }}><label htmlFor="t-token">Token</label><input id="t-token" className="mono" value={f.token} onChange={set("token")} placeholder="0x…" /></div>
          <div style={{ flex: "1 1 300px" }}><label htmlFor="t-pair">V2 pair</label><input id="t-pair" className="mono" value={f.pair} onChange={set("pair")} placeholder="0x…" /></div>
        </div>
        <label htmlFor="t-h">LP holders (team wallets / lockers, comma separated)</label><input id="t-h" className="mono" value={f.holders} onChange={set("holders")} />
        <div className="row">
          <div style={{ flex: "1 1 200px" }}><label htmlFor="t-min">Promised minimum LP (summed)</label><input id="t-min" value={f.minLp} onChange={set("minLp")} inputMode="decimal" /></div>
          <div style={{ flex: "1 1 160px" }}><label htmlFor="t-start">Start block</label><input id="t-start" value={f.start} onChange={set("start")} inputMode="numeric" /></div>
          <div style={{ flex: "1 1 160px" }}><label htmlFor="t-hours">Promise length (hours)</label><input id="t-hours" value={f.hours} onChange={set("hours")} inputMode="decimal" /></div>
        </div>
        <div className="row">
          <div style={{ flex: "1 1 160px" }}><label htmlFor="t-win">Claim window (minutes)</label><input id="t-win" value={f.window} onChange={set("window")} inputMode="numeric" /></div>
          <div style={{ flex: "1 1 160px" }}><label htmlFor="t-bond">Bond (GEN)</label><input id="t-bond" value={f.bond} onChange={set("bond")} inputMode="decimal" /></div>
          <div style={{ flex: "1 1 160px" }}><label htmlFor="t-dust">Dust floor (GEN)</label><input id="t-dust" value={f.dust} onChange={set("dust")} inputMode="decimal" /></div>
        </div>
        <p className="small">Unclaimed shares are redistributed to the holders who claimed. A bond cannot name a destination for them.</p>
        <label htmlFor="t-ex">Extra excluded addresses (routers, other team wallets)</label><input id="t-ex" className="mono" value={f.excluded} onChange={set("excluded")} />
        <div className="row" style={{ marginTop: 16 }}><button className="btn" onClick={() => void create()} disabled={!w.account || w.onWrongNetwork}>Post bond</button></div>
        <TxStatus p={p} />
      </div>
      <h2>Your bonds</h2>
      {!w.account ? <p className="small">Connect a wallet to see the bonds it posted.</p> : mine.length ? (
        <div className="grid">{mine.map((b) => <Link key={b.bond_id} className="sticker card-link" href={`/bond/${reg === "demo" ? "demo-" : ""}${b.bond_id}`}>
          <span className={`pill ${STATUS[b.status]?.tone ?? "wait"}`}>{STATUS[b.status]?.label ?? b.status}</span><h3 style={{ marginTop: 10 }}>{b.name}</h3>
          <p className="small">bond {gen(b.amount)} GEN · {b.n_checks} checks · {b.due ? `due: ${b.due}` : ""}</p></Link>)}</div>
      ) : <p className="small">None yet.</p>}
    </>
  );
}
