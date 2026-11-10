import type { Metadata } from "next";
import { keeperStatus } from "@/lib/server";
import { REPO, STUDIO_EXPLORER } from "@/lib/deployments";
import { short } from "@/lib/format";

export const metadata: Metadata = { title: "Keeper" };
export const revalidate = 60;

export default async function Keeper() {
  const s = await keeperStatus();
  if (!s) return <><h1>Keeper</h1><p className="note warn">The keeper&apos;s status file (keeper-state branch) is unreadable right now.</p></>;
  return (
    <>
      <p className="small" style={{ marginTop: 28 }}>GitHub Actions · hourly and 6-hourly · signer <span className="mono">{short(s.keeper)}</span></p>
      <h1>Keeper</h1>
      <p style={{ maxWidth: 760 }}>Walks every page of bonds (offsets persisted on the keeper-state branch), reads each chain&apos;s finalized head from two endpoints (a head counts only when both answered), files the next rug check for every active bond, settles every bond that is due, walks every page of claims, waits for FINALIZED and re-reads the bond, retries what did not land, and resubmits a hash stuck for 6 hours. Nothing is skipped silently: everything not finished is listed below.</p>
      <p>Last run: {s.started_at} → {s.finished_at} ({s.trigger}){s.run_url && <> · <a href={s.run_url}>run log</a></>} · <a href={`${REPO}/tree/keeper-state`}>keeper-state branch</a> · <a href={`${REPO}/actions/workflows/keeper.yml`}>workflow</a></p>
      {Object.entries(s.contracts).map(([name, c]) => (
        <section key={name}>
          <h2>{name}</h2>
          <div className="kpis">
            {Object.entries(c.totals ?? {}).filter(([k]) => k !== "by_result").map(([k, v]) => <div key={k} className="sticker kpi"><div className="label">{k}</div><div className="big">{String(v)}</div></div>)}
          </div>
          <p className="small">Results: {Object.entries((c.totals?.by_result as Record<string, number>) ?? {}).map(([k, v]) => `${k} ${v}`).join(" · ") || "none yet"}</p>
          <h3>Bonds</h3>
          <div className="table-wrap"><table><thead><tr><th>bond</th><th>status</th><th>cursor</th><th>checks (pending)</th><th>last result</th><th>due</th><th>claims seen</th></tr></thead><tbody>
            {Object.entries(c.bonds ?? {}).map(([id, b]) => <tr key={id}><td>#{id} {b.name}</td><td>{b.status}</td><td className="mono">{b.cursor}</td><td>{b.n_checks} ({b.n_pending})</td><td>{b.last_result}{b.waiting ? <div className="small">{b.waiting}</div> : null}</td><td>{b.due}</td><td>{b.claims_seen ?? 0}</td></tr>)}
          </tbody></table></div>
          <h3>Not finished ({c.unprocessed?.length ?? 0})</h3>
          {c.unprocessed?.length ? <ul className="small">{c.unprocessed.map((u) => <li key={u.key}><span className="mono">{u.key}</span>: {u.why}</li>)}</ul> : <p className="small">Nothing pending.</p>}
          <h3>Actions ({c.actions?.length ?? 0})</h3>
          <div className="table-wrap"><table><thead><tr><th>action</th><th>status</th><th>result</th><th>tx</th><th>attempts</th><th>last error</th></tr></thead><tbody>
            {[...(c.actions ?? [])].reverse().slice(0, 300).map((a) => <tr key={a.key}><td className="mono small">{a.key}</td><td>{a.status}</td><td>{a.result}</td><td>{a.tx && <a className="mono small" href={`${STUDIO_EXPLORER}/tx/${a.tx}`}>{short(a.tx, 6)}</a>}</td><td>{a.attempts}</td><td className="small">{a.last_error}</td></tr>)}
          </tbody></table></div>
        </section>
      ))}
      <h2>Run history</h2>
      <div className="table-wrap"><table><thead><tr><th>started</th><th>trigger</th><th>runs</th></tr></thead><tbody>
        {[...(s.history ?? [])].reverse().map((h) => <tr key={h.started_at}><td>{h.run_url ? <a href={h.run_url}>{h.started_at}</a> : h.started_at}</td><td>{h.trigger}</td><td className="small">{Object.entries(h.runs).map(([n, r]) => `${n}: submitted ${r.submitted}, done ${r.done}, pages ${r.pages} (failed ${r.pages_failed})`).join(" · ")}</td></tr>)}
      </tbody></table></div>
    </>
  );
}
