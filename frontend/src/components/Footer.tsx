import { ADDR, COMMIT, REPO, STUDIO_EXPLORER } from "@/lib/deployments";

export function Footer() {
  return (
    <footer className="footer">
      <div className="wrap">
        <p>
          RugBond on GenLayer Studio Dev. Registry{" "}
          {ADDR.registry ? <a className="mono" href={`${STUDIO_EXPLORER}/address/${ADDR.registry}`}>{ADDR.registry}</a> : "not deployed"}, LaunchGate{" "}
          {ADDR.gate ? <a className="mono" href={`${STUDIO_EXPLORER}/address/${ADDR.gate}`}>{ADDR.gate}</a> : "not deployed"}
          {COMMIT ? <>, deployed from commit <a className="mono" href={`${REPO}/commit/${COMMIT}`}>{COMMIT.slice(0, 7)}</a></> : null}. Source: <a href={REPO}>{REPO.replace("https://", "")}</a>.
        </p>
        <p>Verdicts are decided by code from chain data read from two RPCs; no model, no admin. Bonds are GEN on Studio Dev, a test network. Board entries marked replay were created after the events they describe.</p>
      </div>
    </footer>
  );
}
