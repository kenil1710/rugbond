import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { regAddr, STUDIO_EXPLORER, type Reg } from "@/lib/deployments";
import { bond, bondChecks, bondClaims, keeperStatus } from "@/lib/server";
import { lpSeries } from "@/lib/evm";
import { LiquidityChart } from "@/components/LiquidityChart";
import { StatusPill } from "@/components/Status";
import { Meter } from "@/components/BondCard";
import { BondActions } from "@/components/BondActions";
import { CHAIN_LABEL, REASON_TEXT, ago, gen, scan, short, units, when } from "@/lib/format";

export const revalidate = 60;
const parse = (id: string): { reg: Reg; n: number } => (id.startsWith("demo-") ? { reg: "demo", n: Number(id.slice(5)) } : { reg: "canonical", n: Number(id) });

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }): Promise<Metadata> {
  const { id } = await params;
  return { title: `Bond ${id}` };
}

export default async function BondPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const { reg, n } = parse(id);
  const addr = regAddr(reg);
  if (!addr || !Number.isInteger(n) || n <= 0) notFound();
  const b = await bond(addr, n).catch(() => null);
  if (!b?.found) notFound();
  const [checks, claims, series, ks] = await Promise.all([bondChecks(addr, n).catch(() => []), bondClaims(addr, n).catch(() => []),
    lpSeries(b), keeperStatus()]);
  const rug = b.rug_block ? { block: b.rug_block, ts: b.rug_ts } : null;
  const r = b.rug && "lp_before" in b.rug ? b.rug : null;
  const settleTx = (ks?.contracts?.[reg === "demo" ? "RugBondDemo" : "RugBond"]?.actions ?? []).find((a) => a.kind === "SETTLE" && a.bond_id === n && a.status === "DONE")?.tx;
  const terms: [string, React.ReactNode][] = [
    ["chain", CHAIN_LABEL[b.chain] ?? b.chain], ["token", <a key="t" className="mono" href={scan(b.chain, "token", b.token)}>{b.token}</a>],
    ["pair", <a key="p" className="mono" href={scan(b.chain, "address", b.pair)}>{b.pair}</a>],
    ["LP holders", <span key="h">{b.lp_holders.map((h) => <a key={h} className="mono" href={scan(b.chain, "address", h)} style={{ display: "block" }}>{h}</a>)}</span>],
    ["promised minimum LP", `${units(b.min_lp, 18, 6)} LP (summed)`], ["start block", <a key="s" href={scan(b.chain, "block", b.start_block)}>{b.start_block}</a>],
    ["end time", when(b.end_time)], ["bond", `${gen(b.amount)} GEN`], ["claim window", `${Math.round(b.claim_window_s / 60)} min`],
    ["victim fund", <span key="v" className="mono">{b.victim_fund}</span>], ["dust floor", `${gen(b.dust_floor)} GEN`],
    ["excluded (all)", <span key="e" className="mono small">{b.excluded_all.map((e) => short(e)).join(", ")}</span>],
    ["team", <span key="tm" className="mono">{b.team}</span>], ["created", when(b.created_at)], ["recovery deadline", when(b.recovery_deadline)],
  ];
  return (
    <>
      <p className="small"><Link href="/">← board</Link> · {reg === "demo" ? "demo registry" : "canonical registry"} · bond #{n}</p>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h1 style={{ marginBottom: 0 }}>{b.name}</h1>
        <StatusPill status={b.status} replay={b.replay} nChecks={b.n_checks} lastResult={b.last_result} />
      </div>
      {b.replay ? <p className="note">Replay: this bond was created after the events it covers (its start block is older than the bond), to show the rule on real history. LaunchGate never answers favorably for a replay.</p> : null}
      <div className="kpis">
        <div className="sticker kpi"><div className="label">bond</div><div className="big">{gen(b.amount)}</div><div className="small">GEN</div></div>
        <div className={`sticker kpi ${r ? "pink" : "lime"}`}><div className="label">{r ? "rug block" : "read to block"}</div><div className="big" style={{ fontSize: "2rem" }}>{r ? b.rug_block : b.cursor || "—"}</div><div className="small">{r ? when(b.rug_ts) : b.cursor_ts ? when(b.cursor_ts) : "no read yet"}</div></div>
        <div className="sticker kpi"><div className="label">holders paid</div><div className="big">{b.n_claims}</div><div className="small">{gen(b.paid)} GEN</div></div>
        <div className="sticker kpi"><div className="label">checks</div><div className="big">{b.n_checks}</div><div className="small">{b.n_pending} pending · last {ago(b.last_check_at)}</div></div>
      </div>
      <BondActions address={addr} bond={{ bond_id: b.bond_id, status: b.status, checkable: b.checkable, due: b.due, team: b.team, victim_fund: b.victim_fund, n_checks: b.n_checks }} />
      <section className="sticker" style={{ marginTop: 16 }}>
        <h2 style={{ marginTop: 0 }}>Liquidity vs the promise</h2>
        {series ? <LiquidityChart points={series.points} floor={b.min_lp} rug={rug} endTime={b.end_time} title={`LP held by ${b.name}'s LP holders against the promised floor`} />
          : <p className="small">The chart appears after the first agreed read.</p>}
        <Meter b={b} />
      </section>
      {r ? (
        <>
          <h2>The rug</h2>
          <div className="sticker pink">
            <p>At block <b><a href={scan(b.chain, "block", b.rug_block)}>{b.rug_block}</a></b> ({when(b.rug_ts)}) the LP holders&apos; summed LP fell from <b>{units(r.lp_before, 18, 6)}</b> to <b>{units(r.lp_after, 18, 6)}</b>, below the promised {units(b.min_lp, 18, 6)}.</p>
            <p>LP transfer{r.txs.length > 1 ? "s" : ""} out in that block: {r.txs.map((t) => <a key={t} className="mono" href={scan(b.chain, "tx", t)} style={{ display: "block" }}>{t}</a>)}</p>
            <p>Snapshot at block {b.rug_block - 1}: total supply {units(r.supply, 18, 6)}, excluded balances {units(String(BigInt(r.supply ?? "0") - BigInt(r.denom ?? "0")), 18, 6)} → claimable supply <b>{units(r.denom, 18, 6)}</b>.</p>
            <p>Share = bond × min(balance at the start block {b.start_block}, balance at block {b.rug_block - 1}) ÷ {units(r.denom, 18, 6)}; tokens received directly from the team after the start do not count. Claim window until <b>{when(b.claim_deadline)}</b> ({ago(b.claim_deadline)}). <Link href={`/claim?bond=${id}`}>Claim →</Link></p>
          </div>
        </>
      ) : null}
      {b.settled_at ? (
        <>
          <h2>Settlement</h2>
          <div className="sticker">
            <p><b>{gen(b.settled_amount)} GEN</b> sent to <span className="mono">{b.settled_to}</span> ({b.settled_to === b.team ? "the team: the promise held" : "the victim fund: what holders did not claim"}) at {when(b.settled_at)}, by <span className="mono">{short(b.settled_by)}</span>.
              {settleTx ? <> Transaction <a className="mono" href={`${STUDIO_EXPLORER}/tx/${settleTx}`}>{short(settleTx, 10)}</a>.</> : null}</p>
          </div>
        </>
      ) : null}
      <h2>Holder claims ({claims.length})</h2>
      {claims.length ? (
        <div className="table-wrap"><table>
          <thead><tr><th>#</th><th>holder</th><th>paid to</th><th className="num">paid on (min of start, R-1)</th><th className="num">share (GEN)</th><th>when</th></tr></thead>
          <tbody>{claims.map((c) => <tr key={c.holder}><td>{c.claim_no + 1}</td><td className="mono">{short(c.holder)}</td><td className="mono">{c.payee === c.holder ? "itself" : short(c.payee)}</td>
            <td className="num">{units(c.balance, 18, 6)}</td><td className="num">{gen(c.share)}</td><td className="small">{when(c.claimed_at)}</td></tr>)}</tbody>
        </table></div>
      ) : <p className="small">{b.status === "RUGGED" ? "No claims yet." : "Claims open only after a RUGGED verdict."}</p>}
      <h2>Rug checks ({checks.length})</h2>
      <div className="table-wrap"><table>
        <thead><tr><th>#</th><th>result</th><th>blocks read</th><th>LP transfers out</th><th>probes (block: summed LP)</th><th>by / when</th></tr></thead>
        <tbody>{checks.map((c) => <tr key={c.check_id}><td>{c.check_id}</td><td><b style={{ color: c.result === "RUGGED" ? "var(--pink)" : c.result === "PENDING" ? "var(--amber)" : "var(--lime)" }}>{c.result}</b>
          {c.reason ? <div className="small">{c.reason}{REASON_TEXT[c.reason] ? ": " + REASON_TEXT[c.reason] : ""}</div> : null}</td>
          <td className="mono small">{c.a ? `${c.a} – ${c.b}` : "—"}</td><td>{c.n_logs}</td>
          <td className="mono small">{c.probes.map((p) => `${p[0]}: ${units(p[1], 18, 4)}`).join(" · ") || "—"}</td><td className="small"><span className="mono">{short(c.by)}</span><br />{when(c.at)}</td></tr>)}</tbody>
      </table></div>
      <h2>Frozen terms</h2>
      <div className="table-wrap"><table><tbody>{terms.map(([k, v]) => <tr key={k}><th style={{ width: 200 }}>{k}</th><td>{v}</td></tr>)}</tbody></table></div>
      <p className="small">Data: the registry&apos;s views (get_bond, list_checks, list_claims) on Studio Dev; the chart is a display read of the chain. JSON: <a href={`/api/bond?id=${id}`}>/api/bond?id={id}</a> · badge <a href={`/api/badge?bond=${id}`}>/api/badge?bond={id}</a></p>
    </>
  );
}
