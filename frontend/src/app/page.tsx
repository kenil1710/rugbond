import Link from "next/link";
import { ADDR } from "@/lib/deployments";
import { allBonds, stats } from "@/lib/server";
import type { Bond, Stats } from "@/lib/types";
import { BondCard } from "@/components/BondCard";
import { gen } from "@/lib/format";

export const revalidate = 60;

async function load(addr: string) {
  if (!addr) return { bonds: [] as Bond[], stats: null as Stats | null, error: "" };
  try { return { bonds: [...(await allBonds(addr))].reverse(), stats: await stats(addr), error: "" }; }
  catch (e) { return { bonds: [] as Bond[], stats: null, error: String((e as Error).message).slice(0, 120) }; }
}

export default async function Home() {
  const [c, d] = await Promise.all([load(ADDR.registry), load(ADDR.registryDemo)]);
  const s = c.stats;
  return (
    <>
      <section className="hero">
        <span className="tag">liquidity, bonded</span>
        <h1>Pull the liquidity early,<br />the bond pays the holders.</h1>
        <p style={{ maxWidth: 720, fontSize: "1.1rem" }}>
          A token team locks GEN behind a frozen promise: these LP wallets keep at least this much LP until this time.
          GenLayer validators read the pool from two RPCs. If the LP drops below the floor, everyone who held the token since
          the promise began claims a pro-rata share of the bond. If it holds, the team gets its bond back. Code decides;
          nobody approves.
        </p>
        <div className="row"><Link className="btn" href="/owed">Am I owed?</Link><Link className="btn ghost" href="/team">Post a bond</Link><Link className="btn ghost" href="/docs">The rules</Link></div>
      </section>
      <div className="kpis">
        <div className="sticker kpi"><div className="label">bonds</div><div className="big">{s?.bonds ?? "—"}</div></div>
        <div className="sticker kpi lime"><div className="label">GEN bonded</div><div className="big">{s ? gen(s.received_total) : "—"}</div></div>
        <div className="sticker kpi pink"><div className="label">paid to holders</div><div className="big">{s ? gen(s.claims_paid_total) : "—"}</div></div>
        <div className="sticker kpi"><div className="label">unclaimed, shared among claimants</div><div className="big">{s ? gen(s.bonus_paid_total) : "—"}</div><div className="small">{s ? gen(s.fund_total) : "—"} GEN to the registry&apos;s fund</div></div>
        <div className="sticker kpi"><div className="label">returned to teams</div><div className="big">{s ? gen(s.returned_total) : "—"}</div></div>
      </div>
      <h2>Bonded tokens</h2>
      <p className="small">The canonical registry (Ethereum). Its seed bonds are historical replays of real rugs and real held liquidity, created after the events and marked <span className="pill done">replay</span>.</p>
      {c.error ? <p className="note warn">The registry could not be read right now ({c.error}). Reload in a minute.</p> : null}
      <div className="grid">{c.bonds.map((b) => <BondCard key={b.bond_id} b={b} reg="canonical" />)}</div>
      {!c.bonds.length && !c.error ? <p className="small">No bonds yet.</p> : null}
      <h2>Demo registry (Base Sepolia)</h2>
      <p className="small">A real test token and a real Uniswap V2 pair on Base Sepolia, rugged and held on purpose; short windows.</p>
      <div className="grid">{d.bonds.map((b) => <BondCard key={b.bond_id} b={b} reg="demo" />)}</div>
      {!d.bonds.length ? <p className="small">No demo bonds yet.</p> : null}
    </>
  );
}
