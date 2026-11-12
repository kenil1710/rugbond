import type { Metadata } from "next";
import { TeamForm } from "./TeamForm";
export const metadata: Metadata = { title: "Teams & launchpads" };
export default function Team() {
  return (
    <>
      <h1>Bond your liquidity</h1>
      <p style={{ maxWidth: 760 }}>Post GEN behind a promise: these LP wallets (team wallets and/or lockers) keep at least this much LP of this pair from this block until this time. Everything is frozen at creation; there is no cancel. If the LP falls below the floor, the bond pays the token holders at the block before; whatever they do not claim is shared among the holders who did claim (if nobody claims, it goes to the registry's fund, an address fixed when the registry was deployed). You never choose where it goes. If it holds, settle returns the bond to you.</p>
      <TeamForm />
    </>
  );
}
