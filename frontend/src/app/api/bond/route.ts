/** GET /api/bond?id=<n | demo-n> — one bond with its checks and claims (every page), from the registry's views. */
import { regAddr } from "@/lib/deployments";
import { bond, bondChecks, bondClaims } from "@/lib/server";
export const dynamic = "force-dynamic";
export async function GET(req: Request) {
  const id = new URL(req.url).searchParams.get("id") ?? "";
  const reg = id.startsWith("demo-") ? "demo" : "canonical";
  const n = Number(reg === "demo" ? id.slice(5) : id);
  if (!Number.isInteger(n) || n <= 0 || !regAddr(reg)) return Response.json({ error: "id must be a bond number (or demo-<n>)" }, { status: 400 });
  try {
    const b = await bond(regAddr(reg), n);
    if (!b.found) return Response.json({ error: "no such bond" }, { status: 404 });
    const [checks, claims] = await Promise.all([bondChecks(regAddr(reg), n), bondClaims(regAddr(reg), n)]);
    return Response.json({ registry: reg, address: regAddr(reg), bond: b, checks, claims }, { headers: { "cache-control": "public, s-maxage=30, stale-while-revalidate=120" } });
  } catch (e) { return Response.json({ error: String((e as Error).message).slice(0, 200) }, { status: 502 }); }
}
