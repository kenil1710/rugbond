// A case (data/cases.json) or a bond view -> the terms object the contract freezes
// (same keys as parse_terms in contracts/RugBond.py).
const ZERO = "0x0000000000000000000000000000000000000000", DEAD = "0x000000000000000000000000000000000000dead";
export function termsOf(c, team = c.team) {
  const holders = [...new Set(c.lp_holders.map((x) => x.toLowerCase()))].sort();
  const extra = [...new Set((c.excluded ?? []).map((x) => x.toLowerCase()))].sort();
  const all = [...new Set([team.toLowerCase(), c.pair, c.token, ZERO, DEAD, ...holders, ...extra])].sort();
  return { chain: c.chain, token: c.token, pair: c.pair, lp_holders: holders, min_lp: String(c.min_lp), start_block: Number(c.start_block),
    end_time: Number(c.end_time), claim_window_s: Number(c.claim_window_s ?? 3600),
    excluded: extra, excluded_all: all, dust_floor: String(c.dust_floor ?? "0") };
}
