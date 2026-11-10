import type { Metadata } from "next";
import { GateDemo } from "./GateDemo";
import { ADDR } from "@/lib/deployments";

export const metadata: Metadata = { title: "LaunchGate" };

export default function Gate() {
  return (
    <>
      <p className="small" style={{ marginTop: 28 }}>Consumer contract</p>
      <h1>LaunchGate</h1>
      <p style={{ maxWidth: 760 }}>What a launchpad listing, a DEX badge or a lending market asks before trusting a token&apos;s liquidity promise. Every question is bound to a bond: either the bond id itself, or the team that posted it. A copycat bond (the same token bonded by someone else, or a look-alike token) is never read. Never favorable on missing, pending or stale data.</p>
      <pre className="sticker mono small" style={{ whiteSpace: "pre-wrap", overflowX: "auto" }}>{`gate = gl.contract.get_at(Address("${ADDR.gate || "<LaunchGate>"}")).view()
s = gate.check_for(token, bond_id)        # reads exactly that bond, NO_BOND if it is for another token
t = gate.is_safe_for(token, team)         # only bonds that \`team\` itself posted for \`token\`; worst state wins
# NO_BOND | ACTIVE_HELD_SO_FAR | HELD_FINAL | RUGGED_PAYING | RUGGED_CLOSED | PENDING
if s["safe"]: ...                          # true only for ACTIVE_HELD_SO_FAR: a live promise read recently`}</pre>
      <GateDemo />
    </>
  );
}
