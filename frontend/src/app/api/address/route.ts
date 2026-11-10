/** GET /api/address?a=0x… — what an address is owed across every rugged bond (both registries). */
import { owed } from "@/lib/owed";
export const dynamic = "force-dynamic";
export async function GET(req: Request) {
  const a = new URL(req.url).searchParams.get("a") ?? "";
  if (!/^0x[0-9a-fA-F]{40}$/.test(a)) return Response.json({ error: "a must be an address" }, { status: 400 });
  try { return Response.json(await owed(a), { headers: { "cache-control": "public, s-maxage=30, stale-while-revalidate=120" } }); }
  catch (e) { return Response.json({ error: String((e as Error).message).slice(0, 200) }, { status: 502 }); }
}
