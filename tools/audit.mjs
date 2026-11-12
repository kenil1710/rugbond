/**
 * The A-N audit -> docs/AUDIT.md. Reads docs/final_check.json (run tools/final_check.mjs first) and runs the
 * focused test groups each item rests on.
 *   A source      B funds        C stuck states   D evidence binding   E two sources   F identity
 *   G coverage    H counters     I real-world truth  J keeper (incl. a scheduled run)   K gate meaning
 *   L docs truth  M verification package   N demo
 *   node tools/audit.mjs
 */
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { spawnSync } from "node:child_process";
const root = new URL("..", import.meta.url).pathname;
const rd = (p) => readFileSync(root + p, "utf8");
const fc = JSON.parse(rd("docs/final_check.json"));
const C = (name) => fc.checks.find((c) => c.name === name) ?? { ok: false, detail: "not run" };
const unit = (...tests) => {
  const r = spawnSync("python3", ["-m", "unittest", ...tests], { cwd: root + "test", encoding: "utf8" });
  const n = Number((r.stderr.match(/Ran (\d+) tests/) ?? [])[1] ?? 0);
  return { ok: r.status === 0 && n > 0, n };
};
const rows = [];
const add = (id, name, ok, detail) => rows.push({ id, name, ok, detail });

add("A", "source", C("source match").ok && C("build and site copies fresh").ok, C("source match").detail);
add("B", "funds", C("balances match ledgers").ok && C("payouts arrived").ok,
  `${C("payouts arrived").detail}; ${C("balances match ledgers").detail}; conservation, share and unclaimed-GEN tests: ${unit("test_claims.Conservation", "test_claims.ShareMatrix", "test_claims.Unclaimed").n} pass`);
{
  const u = unit("test_claims.Settle", "test_claims.Unclaimed", "test_pending.Pending", "test_create.More", "test_scan.Flood");
  add("C", "stuck states", u.ok && C("canonical replays decided and settled").ok,
    `every status has an exit (HELD/VOID -> team; RUGGED after the window -> one settle sends everything unclaimed to the registry's fund -> CLOSED; ACTIVE with no cursor movement for the recovery window -> the registry's fund; credits withdrawable; stray swept); a flood of 1,000+ LP transfers out is scanned across checks and the recovery deadline moves with every check that moves the cursor: ${u.n} tests; on chain: ${C("canonical replays decided and settled").detail}`);
}
{
  const u = unit("test_scan.Detection", "test_scan.PairValidity", "test_attacks", "test_claims.TeamTransfers", "test_claims.ClaimLogFlood");
  add("D", "evidence binding", u.ok, `a RUGGED verdict stores R, its timestamp, the LP transfers out in R (tx hashes), LP before/after and the R-1 token snapshot; the pair must be one its listed factory maps back; claims bind to msg.sender, to balances at the start block and R-1 and to the summed transfers from team senders, all read from two RPCs (a team transfer subtracts its own amount; zero-value and dust transfers disqualify nobody); ${u.n} tests`);
}
{
  const u = unit("test_pending.Consensus", "test_pending.FailureMatrix", "test_static.Rpcs");
  const dm = spawnSync(root + ".venv-gl/bin/python", ["-m", "pytest", "tests/direct", "-q", "-k", "validator"], { cwd: root, encoding: "utf8" });
  const dmn = Number(dm.stdout.match(/(\d+) passed/)?.[1] ?? 0);
  const g = JSON.parse(rd("docs/feasibility_genvm.json"));
  add("E", "two sources", u.ok && dm.status === 0 && dmn > 0, `two log RPCs and two state RPCs per chain from different operators; any disagreement or failure is PENDING, never a verdict; validators derive the range from the bond's stored cursor and span and accept a leader's failure only if their own read fails (${u.n} offline tests, ${dmn} Direct Mode validator tests); feasibility study on the first read code, GenVM: ${g.rows.filter((r) => r.identical).length}/${g.rows.length} feasibility reads and ${(g.claim_reads?.rows ?? []).filter((r) => r.identical).length}/${(g.claim_reads?.rows ?? []).length} claim reads identical to this machine's`);
}
{
  const u = unit("test_claims.Beneficiary", "test_attacks.Attacks.test_a26_claimant_is_sender_not_argument", "test_attacks.Attacks.test_a17_victim_fund_cannot_be_team",
    "test_attacks.Attacks.test_a17b_the_fund_itself_cannot_post_a_bond", "test_attacks.Attacks.test_a18b_team_second_wallet_gets_nothing_from_any_path", "test_claims.Unclaimed.test_fund_is_fixed_at_deployment", "test_claims.Unclaimed.test_team_pre_start_float_gets_only_its_own_share");
  add("F", "identity", u.ok, `the claimant is msg.sender (claim takes only the bond id); a beneficiary is committed once by the holder itself; the team is the bond's sender and names no destination: a claimant gets its own share only and unclaimed GEN goes to the registry's fund, fixed in the constructor; ${u.n} tests`);
}
add("G", "coverage", C("tests").ok && C("e2e").ok, `${C("tests").detail}; ${C("e2e").detail}`);
{
  const u = unit("test_static.Money", "test_claims.Refusals.test_failed_claim_changes_nothing", "test_attacks.Attacks.test_a14_junk_checks_cannot_change_state");
  add("H", "counters", u.ok, `every write path checks everything before its first write; refused calls change no counter; ${u.n} tests`);
}
{
  const rw = JSON.parse(rd("docs/real_world.json"));
  add("I", "real-world truth", rw.rows.every((r) => r.agree), `${rw.rows.filter((r) => r.agree).length}/${rw.rows.length} verdicts agree with Burn events, rug-transaction senders, reserves and end balances (docs/REAL_WORLD_CHECK.md)`);
}
add("J", "keeper", C("keeper").ok, `${C("keeper").detail}; keeper tests: ${(rd("docs/final_check.json").match(/keeper suite (\d+)/) ?? [])[1] ?? "?"}`);
{
  const u = unit("test_gate", "test_meaning.NeverFavorable");
  add("K", "gate meaning", u.ok, `bound to (token, bond id) or (token, team); copycats never read; safe only for a fresh agreed read of an ACTIVE bond; every other status x read x age x replay combination unsafe; ${u.n} tests`);
}
{
  const u = unit("test_meaning.DocsMatchCode", "test_meaning.RoutersDocumented");
  add("L", "docs truth", u.ok && C("docs language").ok, `every constant, RPC, state and reason in docs/RULES.md checked against build/ (${u.n} tests); the site's /docs is that file; ${C("docs language").detail}`);
}
add("M", "verification package", fc.passed === fc.total, `tools/final_check.mjs ${fc.passed}/${fc.total}; tools/verify_source.mjs; docs/FEASIBILITY.md, SEEDS.md, DEMO.md, REAL_WORLD_CHECK.md, ATTACK_REPORT.md`);
{
  const d = existsSync(root + "docs/demo-run.json") ? JSON.parse(rd("docs/demo-run.json")) : { steps: [] };
  const z = [...d.steps].reverse().find((s) => s.id.startsWith("balance_zero"));
  add("N", "demo", d.steps.length > 0 && d.steps.every((s) => s.ok) && !!z?.ok, `${d.steps.filter((s) => s.ok).length}/${d.steps.length} demo steps ok on Base Sepolia (rug, claims with a dusting attempt and a real team transfer, refusals, no bonus for claimants, unclaimed GEN to the registry's fund, a bond nobody claimed, a flood of 1,100 LP transfers, held, copycat, gate); payouts verified; demo registry eth_getBalance ${z?.eth_getBalance ?? "?"} wei`);
}
const ok = rows.filter((r) => r.ok).length;
const L = ["# Audit A-N", "", `\`node tools/audit.mjs\` at ${new Date().toISOString()} (final check of ${fc.at}, HEAD ${fc.head.slice(0, 7)}): **${ok}/${rows.length}**.`, "", "| | item | result | evidence |", "|---|---|---|---|"];
for (const r of rows) L.push(`| ${r.id} | ${r.name} | ${r.ok ? "PASS" : "FAIL"} | ${r.detail.replace(/\|/g, "/")} |`);
writeFileSync(root + "docs/AUDIT.md", L.join("\n") + "\n");
writeFileSync(root + "docs/audit.json", JSON.stringify({ at: new Date().toISOString(), ok, total: rows.length, rows }, null, 1) + "\n");
for (const r of rows) console.log(r.id, r.ok ? "PASS" : "FAIL", r.name);
console.log(`${ok}/${rows.length}`);
process.exit(ok === rows.length ? 0 : 1);
