import Link from "next/link";
import type { Bond } from "@/lib/types";
import { CHAIN_LABEL, gen, short, units, ago } from "@/lib/format";
import { StatusPill } from "./Status";

/** Liquidity vs floor as a bar: what the bond last knew. */
export function Meter({ b }: { b: Bond }) {
  const floor = BigInt(b.min_lp || "0");
  const rug = b.rug && "lp_before" in b.rug ? b.rug : null;
  const now = rug ? BigInt(rug.lp_after ?? "0") : floor;
  const top = rug ? (BigInt(rug.lp_before ?? "0") > floor ? BigInt(rug.lp_before ?? "0") : floor) : (floor * 12n) / 10n;
  const pct = top > 0n ? Number((now * 1000n) / top) / 10 : 0;
  const fl = top > 0n ? Number((floor * 1000n) / top) / 10 : 0;
  return (
    <div>
      <div className={`meter ${rug ? "rug" : ""}`} role="img" aria-label={rug ? `LP fell to ${units(now)} below the floor of ${units(floor)}` : `LP at or above the floor of ${units(floor)} so far`}>
        <span style={{ width: `${Math.max(rug ? pct : 100 * 10 / 12, rug && pct === 0 ? 1.5 : 0)}%` }} />
        <i className="floor" style={{ left: `${fl}%` }} />
      </div>
      <div className="small">{rug ? <>LP {units(rug.lp_before)} → <b style={{ color: "var(--pink)" }}>{units(rug.lp_after)}</b> · floor {units(floor)}</> : <>floor {units(floor)} LP · {b.status === "ACTIVE" ? `read to block ${b.cursor || "—"}` : "held to the end"}</>}</div>
    </div>
  );
}

export function BondCard({ b, reg }: { b: Bond; reg: "canonical" | "demo" }) {
  const tone = ["RUGGED", "CLOSED"].includes(b.status) ? "pink" : ["HELD", "RETURNED"].includes(b.status) ? "lime" : "";
  return (
    <Link className="card-link sticker" href={`/bond/${reg === "demo" ? "demo-" : ""}${b.bond_id}`} style={{ borderColor: tone === "pink" ? "var(--pink)" : tone === "lime" ? "var(--lime)" : "#000" }}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <span className="small">#{b.bond_id} · {CHAIN_LABEL[b.chain] ?? b.chain}</span>
        <StatusPill status={b.status} replay={b.replay} nChecks={b.n_checks} lastResult={b.last_result} />
      </div>
      <h3 style={{ marginTop: 10 }}>{b.name}</h3>
      <div className="small mono">token {short(b.token, 4)} · pair {short(b.pair, 4)}</div>
      <Meter b={b} />
      <div className="row" style={{ justifyContent: "space-between", marginTop: 10 }}>
        <div><div className="small">bond</div><div className="display" style={{ fontSize: "1.6rem" }}>{gen(b.amount)} GEN</div></div>
        <div style={{ textAlign: "right" }}><div className="small">holders paid</div><div className="display" style={{ fontSize: "1.6rem" }}>{b.n_claims} · {gen(b.paid)}</div></div>
      </div>
      <div className="small">{b.status === "ACTIVE" ? `last read ${ago(b.scanned_at)}` : b.verdict_at ? `verdict ${ago(b.verdict_at)}` : ""}</div>
    </Link>
  );
}
