import type { Metadata } from "next";
import Link from "next/link";
import { owed } from "@/lib/owed";
import { CHAIN_LABEL, gen, units, when } from "@/lib/format";

export const metadata: Metadata = { title: "Am I owed?" };
export const dynamic = "force-dynamic";

const TEXT: Record<string, string> = {
  CLAIMED: "Claimed", CLAIMABLE: "Claimable now", EXCLUDED: "Excluded by the bond's terms (team, pair, LP holder, router…)",
  CONTRACT: "A contract: contracts cannot claim", NO_BALANCE: "Held nothing at the bond's start block (tokens bought after the bond opened earn nothing)",
  FROM_TEAM: "Received tokens directly from the team (or another excluded address) after the bond opened: refused", BELOW_DUST: "Below the bond's dust floor",
  WINDOW_OVER: "The claim window is over (unclaimed GEN went to the victim fund)", UNREADABLE: "The chain could not be read right now; try again",
};

export default async function Owed({ searchParams }: { searchParams: Promise<{ a?: string }> }) {
  const { a = "" } = await searchParams;
  const valid = /^0x[0-9a-fA-F]{40}$/.test(a.trim());
  const res = valid ? await owed(a.trim()).catch((e) => ({ error: String((e as Error).message).slice(0, 160) })) : null;
  return (
    <>
      <h1>Am I owed?</h1>
      <p style={{ maxWidth: 680 }}>Paste a wallet address. For every rugged bond, RugBond reads that address&apos;s token balance at the bond&apos;s start block and at the block before the rug, and pays on the smaller one. Holders claim with the same wallet (the same key works on GenLayer).</p>
      <form className="sticker row" action="/owed" method="get" style={{ maxWidth: 760 }}>
        <label htmlFor="a" style={{ margin: 0, flex: "1 1 100%" }}>Wallet address</label>
        <input id="a" name="a" defaultValue={a} placeholder="0x…" className="mono" style={{ flex: "1 1 360px" }} autoComplete="off" spellCheck={false} />
        <button className="btn" type="submit">Look up</button>
      </form>
      {a && !valid ? <p className="note warn">That is not an address.</p> : null}
      {res && "error" in res ? <p className="note warn">Could not read right now: {res.error}</p> : null}
      {res && "rows" in res ? (
        <>
          <h2>{res.rows.length ? `${res.rows.length} rugged bond${res.rows.length > 1 ? "s" : ""} involve this address` : "Nothing owed"}</h2>
          <p className="small">{res.scanned} rugged bonds checked. Shares are estimates read from the chain now; the contract re-reads the balance from two RPCs when you claim.</p>
          <div className="grid">
            {res.rows.map((r) => (
              <div key={r.reg + r.bond.bond_id} className={`sticker ${r.state === "CLAIMABLE" ? "lime" : r.state === "CLAIMED" ? "" : ""}`}>
                <div className="small">{r.reg} #{r.bond.bond_id} · {CHAIN_LABEL[r.bond.chain]} {r.bond.replay ? "· replay" : ""}</div>
                <h3>{r.bond.name}</h3>
                <div className="big">{gen(r.share)} <span style={{ fontSize: "1rem" }}>GEN</span></div>
                <p className="small">{r.start ? <>at the start block {units(r.start, 18, 6)} · at block {r.bond.rug_block - 1} {units(r.atR, 18, 6)} · paid on {units(r.balance, 18, 6)}</> : <>paid on {units(r.balance, 18, 6)}</>}</p>
                <p><b>{TEXT[r.state]}</b>{r.claim ? <> · paid to <span className="mono">{r.claim.payee.slice(0, 10)}…</span> {when(r.claim.claimed_at)}</> : null}</p>
                {r.state === "CLAIMABLE" ? <Link className="btn pink" href={`/claim?bond=${r.reg === "demo" ? "demo-" : ""}${r.bond.bond_id}`}>Claim before {when(r.bond.claim_deadline)}</Link> : null}
              </div>
            ))}
          </div>
          <p className="small">JSON: <a href={`/api/address?a=${res.address}`}>/api/address?a={res.address}</a></p>
        </>
      ) : null}
    </>
  );
}
