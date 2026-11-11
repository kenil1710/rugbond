import { STATUS } from "@/lib/format";
/** A bond's status as a sticker. An ACTIVE bond is "holding so far" only once an agreed read exists and the last check was not PENDING. */
export function StatusPill({ status, replay, nChecks, lastResult }: { status: string; replay?: boolean; nChecks?: number; lastResult?: string }) {
  let s = STATUS[status] ?? { label: status, tone: "wait" as const };
  if (status === "ACTIVE" && nChecks === 0) s = { label: "Awaiting first read", tone: "wait" };
  else if (status === "ACTIVE" && lastResult === "PENDING") s = { label: "Read pending", tone: "wait" };
  return <span className="row" style={{ gap: 6 }}><span className={`pill ${s.tone}`}>{s.label}</span>{replay ? <span className="pill done" title="Created after the events it describes">replay</span> : null}</span>;
}
