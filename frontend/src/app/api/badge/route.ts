/** GET /api/badge?bond=<n | demo-n> -> an SVG badge with the bond's status; ?address=0x… -> what it is owed. */
import { regAddr } from "@/lib/deployments";
import { bond } from "@/lib/server";
import { owed } from "@/lib/owed";
import { gen } from "@/lib/format";

export const dynamic = "force-dynamic";
const COLORS: Record<string, [string, string]> = { ACTIVE: ["#c6ff3d", "#0b0b0f"], HELD: ["#c6ff3d", "#0b0b0f"], RETURNED: ["#c6ff3d", "#0b0b0f"],
  RUGGED: ["#ff3d8b", "#0b0b0f"], CLOSED: ["#ff3d8b", "#0b0b0f"] };
const esc = (s: string) => s.replace(/[<>&"']/g, "");

function svg(left: string, right: string, [bg, fg]: [string, string]) {
  const lw = 8 + left.length * 6.8, rw = 12 + right.length * 6.8;
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${lw + rw}" height="22" role="img" aria-label="${esc(left)}: ${esc(right)}"><title>${esc(left)}: ${esc(right)}</title><rect width="${lw + rw}" height="22" rx="11" fill="#0b0b0f"/><rect x="${lw}" width="${rw}" height="22" rx="11" fill="${bg}"/><g font-family="ui-monospace,Menlo,monospace" font-size="11" font-weight="700"><text x="7" y="15" fill="#fff">${esc(left)}</text><text x="${lw + 6}" y="15" fill="${fg}">${esc(right)}</text></g></svg>`;
}

export async function GET(req: Request) {
  const u = new URL(req.url);
  const id = u.searchParams.get("bond") ?? "";
  const a = (u.searchParams.get("address") ?? "").toLowerCase();
  let right = "UNREADABLE", color: [string, string] = ["#ffc53d", "#0b0b0f"];
  try {
    if (id) {
      const reg = id.startsWith("demo-") ? "demo" : "canonical";
      const b = await bond(regAddr(reg), Number(reg === "demo" ? id.slice(5) : id));
      right = b.found ? `${b.status} · ${gen(b.amount)} GEN${b.replay ? " · replay" : ""}` : "NO BOND";
      color = COLORS[b.status] ?? color;
    } else if (/^0x[0-9a-f]{40}$/.test(a)) {
      const o = await owed(a);
      const due = o.rows.filter((r) => r.state === "CLAIMABLE").reduce((s, r) => s + BigInt(r.share), 0n);
      right = `owed ${gen(due)} GEN · ${o.rows.length} rugs`;
      color = due > 0n ? COLORS.RUGGED : COLORS.HELD;
    } else right = "BAD QUERY";
  } catch { right = "UNREADABLE"; }
  return new Response(svg("rugbond", right, color), { headers: { "content-type": "image/svg+xml", "cache-control": "public, s-maxage=60, stale-while-revalidate=300" } });
}
