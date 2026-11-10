import type { Point } from "@/lib/evm";
import { units, when } from "@/lib/format";

/** The LP holders' summed LP over time, the promised floor, and the rug moment. Server-rendered SVG, no JS. */
export function LiquidityChart({ points, floor, rug, endTime, title }: {
  points: Point[]; floor: string; rug?: { block: number; ts: number } | null; endTime: number; title: string;
}) {
  if (points.length < 2) return <p className="small">No chart: the chain could not be read for display right now.</p>;
  const W = 760, H = 300, L = 64, R = 18, T = 22, B = 44;
  const t0 = points[0].ts;
  const t1 = Math.max(points[points.length - 1].ts, Math.min(endTime, points[points.length - 1].ts));
  const maxLp = points.reduce((m, p) => (BigInt(p.lp) > m ? BigInt(p.lp) : m), BigInt(floor)) || 1n;
  const yMax = (maxLp * 115n) / 100n;
  const x = (ts: number) => L + ((ts - t0) / Math.max(t1 - t0, 1)) * (W - L - R);
  const y = (v: string | bigint) => T + (1 - Number((BigInt(v) * 10000n) / yMax) / 10000) * (H - T - B);
  // a step line: the balance holds until the next sampled block
  let d = `M ${x(points[0].ts)} ${y(points[0].lp)}`;
  for (let i = 1; i < points.length; i++) d += ` H ${x(points[i].ts)} V ${y(points[i].lp)}`;
  const preRug = rug ? points.filter((p) => p.block < rug.block) : points;
  let area = "";
  if (preRug.length > 1) {
    area = `M ${x(preRug[0].ts)} ${H - B} V ${y(preRug[0].lp)}`;
    for (let i = 1; i < preRug.length; i++) area += ` H ${x(preRug[i].ts)} V ${y(preRug[i].lp)}`;
    area += ` H ${rug ? x(rug.ts) : x(preRug[preRug.length - 1].ts)} V ${H - B} Z`;
  }
  const fy = y(floor);
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => (yMax * BigInt(Math.round(f * 1000))) / 1000n);
  const hours = (t1 - t0) / 3600;
  const xt = [0, 0.25, 0.5, 0.75, 1].map((f) => t0 + f * (t1 - t0));
  const fmtT = (ts: number) => (hours > 72 ? new Date(ts * 1000).toISOString().slice(5, 10) : new Date(ts * 1000).toISOString().slice(11, 16));
  const endX = endTime <= t1 ? x(endTime) : null;
  return (
    <figure className="chart" style={{ margin: 0 }}>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={title}>
        <title>{title}</title>
        {ticks.map((v, i) => (
          <g key={i}>
            <line x1={L} x2={W - R} y1={y(v)} y2={y(v)} stroke="#2c2c38" strokeWidth="1" />
            <text x={L - 8} y={y(v) + 4} fill="#b9b9c8" fontSize="11" textAnchor="end">{units(v, 18, 3)}</text>
          </g>
        ))}
        {xt.map((t, i) => <text key={i} x={x(t)} y={H - B + 18} fill="#b9b9c8" fontSize="11" textAnchor="middle">{fmtT(t)}</text>)}
        <text x={L} y={H - 6} fill="#b9b9c8" fontSize="11">{hours > 72 ? "date (UTC)" : "time (UTC)"}</text>
        {area && <path d={area} fill="#c6ff3d" opacity="0.16" />}
        <line x1={L} x2={W - R} y1={fy} y2={fy} stroke="#ffffff" strokeWidth="2" strokeDasharray="7 6" />
        <text x={W - R} y={fy - 7} fill="#ffffff" fontSize="12" fontWeight="700" textAnchor="end">promised floor</text>
        {endX !== null && <>
          <line x1={endX} x2={endX} y1={T} y2={H - B} stroke="#b9b9c8" strokeWidth="1.5" strokeDasharray="3 4" />
          <text x={endX - 4} y={T + 10} fill="#b9b9c8" fontSize="11" textAnchor="end">end of promise</text>
        </>}
        <path d={d} fill="none" stroke={rug ? "#c6ff3d" : "#c6ff3d"} strokeWidth="3.5" strokeLinejoin="round" />
        {rug && (() => {
          const rx = x(rug.ts);
          return (
            <g>
              <line x1={rx} x2={rx} y1={T} y2={H - B} stroke="#ff3d8b" strokeWidth="3" />
              <circle cx={rx} cy={y("0")} r="8" fill="#ff3d8b" stroke="#000" strokeWidth="3" />
              <rect x={Math.min(rx + 8, W - R - 128)} y={T + 18} width="120" height="26" rx="8" fill="#ff3d8b" stroke="#000" strokeWidth="2.5" />
              <text x={Math.min(rx + 68, W - R - 68)} y={T + 36} fill="#0b0b0f" fontSize="13" fontWeight="800" textAnchor="middle">RUG · block {rug.block}</text>
            </g>
          );
        })()}
      </svg>
      <figcaption className="legend">
        <span><span className="swatch" style={{ background: "#c6ff3d" }} />LP held by the bond&apos;s LP holders</span>
        <span><span className="swatch" style={{ background: "#fff" }} />promised minimum ({units(floor, 18, 4)} LP)</span>
        {rug ? <span><span className="swatch" style={{ background: "#ff3d8b" }} />rug at {when(rug.ts)}</span> : null}
      </figcaption>
    </figure>
  );
}
