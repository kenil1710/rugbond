import Link from "next/link";
import { WalletButton } from "./WalletButton";

const LINKS: [string, string][] = [["/", "Board"], ["/owed", "Am I owed?"], ["/claim", "Claim"], ["/team", "Teams"], ["/gate", "LaunchGate"],
  ["/keeper", "Keeper"], ["/verify", "Verify"], ["/docs", "Rules"]];

export function Nav() {
  return (
    <header className="nav">
      <Link href="/" className="brand"><span className="dot" aria-hidden="true" />RugBond</Link>
      <nav aria-label="Main">{LINKS.map(([h, t]) => <Link key={h} href={h}>{t}</Link>)}</nav>
      <WalletButton />
    </header>
  );
}
