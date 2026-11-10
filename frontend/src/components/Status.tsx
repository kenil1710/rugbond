import { STATUS } from "@/lib/format";
export function StatusPill({ status, replay }: { status: string; replay?: boolean }) {
  const s = STATUS[status] ?? { label: status, tone: "wait" as const };
  return <span className="row" style={{ gap: 6 }}><span className={`pill ${s.tone}`}>{s.label}</span>{replay ? <span className="pill done" title="Created after the events it describes">replay</span> : null}</span>;
}
