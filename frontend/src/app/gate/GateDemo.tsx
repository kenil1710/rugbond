"use client";
import { useState } from "react";
import { viewOf, send } from "@/lib/contract";
import { gateAddr, type Reg } from "@/lib/deployments";
import { useWallet } from "@/components/WalletProvider";
import { TxStatus } from "@/components/TxStatus";
import type { GateAnswer, TxProgress } from "@/lib/types";

export function GateDemo() {
  const w = useWallet();
  const [reg, setReg] = useState<Reg>("demo");
  const [mode, setMode] = useState<"bond" | "team">("bond");
  const [token, setToken] = useState("");
  const [arg, setArg] = useState("");
  const [out, setOut] = useState<GateAnswer | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [p, setP] = useState<TxProgress | null>(null);
  const tok = token.trim().toLowerCase();
  async function ask() {
    setErr(""); setOut(null); setBusy(true);
    try {
      if (!/^0x[0-9a-f]{40}$/.test(tok)) throw new Error("The token must be an address.");
      if (mode === "bond") setOut(await viewOf<GateAnswer>(gateAddr(reg), "check_for", [tok, Number(arg)], true));
      else setOut(await viewOf<GateAnswer>(gateAddr(reg), "is_safe_for", [tok, arg.trim().toLowerCase()], true));
    } catch (e) { setErr(String((e as Error).message)); } finally { setBusy(false); }
  }
  async function attest() {
    if (!w.account) return;
    await send(w.account, gateAddr(reg), mode === "bond" ? "attest" : "attest_team", [tok, mode === "bond" ? Number(arg) : arg.trim().toLowerCase()], 0n, { onProgress: setP });
  }
  const tone = out ? (out.safe ? "lime" : ["RUGGED_PAYING", "RUGGED_CLOSED"].includes(out.state) ? "pink" : "") : "";
  return (
    <div className="sticker" style={{ marginTop: 20 }}>
      <div className="row">
        <div style={{ flex: "1 1 220px" }}><label htmlFor="g-reg">Gate</label>
          <select id="g-reg" value={reg} onChange={(e) => setReg(e.target.value as Reg)}><option value="demo">LaunchGateDemo (Base Sepolia demo)</option><option value="canonical">LaunchGate (canonical)</option></select></div>
        <div style={{ flex: "1 1 220px" }}><label htmlFor="g-mode">Question</label>
          <select id="g-mode" value={mode} onChange={(e) => setMode(e.target.value as "bond" | "team")}><option value="bond">check_for(token, bond_id)</option><option value="team">is_safe_for(token, team)</option></select></div>
      </div>
      <label htmlFor="g-tok">Token</label><input id="g-tok" className="mono" value={token} onChange={(e) => setToken(e.target.value)} placeholder="0x…" spellCheck={false} />
      <label htmlFor="g-arg">{mode === "bond" ? "Bond id" : "Team address"}</label><input id="g-arg" className="mono" value={arg} onChange={(e) => setArg(e.target.value)} placeholder={mode === "bond" ? "1" : "0x…"} spellCheck={false} />
      <div className="row" style={{ marginTop: 14 }}>
        <button className="btn" onClick={() => void ask()} disabled={busy}>{busy ? "Reading…" : "Ask the gate"}</button>
        <button className="btn ghost" onClick={() => void attest()} disabled={!w.account || w.onWrongNetwork}>Attest on chain</button>
      </div>
      {err && <p className="note warn">{err}</p>}
      {out && <div className={`sticker ${tone}`} style={{ marginTop: 16 }} aria-live="polite"><div className="big" style={{ fontSize: "2rem" }}>{out.state}</div><p>safe: <b>{String(out.safe)}</b>{out.why ? ` · ${out.why}` : ""}</p>
        <pre className="mono small" style={{ whiteSpace: "pre-wrap", wordBreak: "break-all" }}>{JSON.stringify(out, null, 2)}</pre></div>}
      <TxStatus p={p} />
    </div>
  );
}
