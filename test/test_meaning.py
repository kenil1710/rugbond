"""Meaning: docs/RULES.md says exactly what the deployed bytes do; the gate never answers favorably on missing data."""
import re
import unittest
from pathlib import Path

from fixtures import module, Sim, fresh, bond, check, until_verdict, get, A, NOW, TEAM, STRANGER
import stub

ROOT = Path(__file__).resolve().parent.parent
RULES = (ROOT / "docs" / "RULES.md").read_text()
RB = module("RugBond")
LG = module("LaunchGate")
SRC = (ROOT / "build" / "RugBond.py").read_text()


def fmt(n):
    return "{:,}".format(n)


class DocsMatchCode(unittest.TestCase):
    def test_canonical_chain(self):
        self.assertEqual(RB.MODES["CANONICAL"][0], ("ethereum",))
        self.assertEqual(RB.MODES["DEMO"][0], ("base-sepolia",))
        self.assertIn("`ethereum` on the canonical registry, `base-sepolia` on the demo registry", RULES)

    def test_claim_window_minimums(self):
        self.assertEqual((RB.MODES["CANONICAL"][1], RB.MODES["DEMO"][1]), (3600, 60))
        self.assertIn("at least 3600 (canonical) or 60 (demo), at most 180 days", RULES)
        self.assertEqual(RB.MAX_CLAIM_WINDOW_S, 180 * 86400)

    def test_recovery(self):
        self.assertEqual((RB.MODES["CANONICAL"][2], RB.MODES["DEMO"][2]), (7 * 86400, 3600))
        self.assertIn("max(end time, creation time) + 7 days (canonical) or 1 hour (demo)", RULES)
        self.assertIn("PENDING checks never extend it, and a scan that is making progress never runs into it", " ".join(RULES.split()))

    def test_stale(self):
        self.assertEqual((RB.MODES["CANONICAL"][3], RB.MODES["DEMO"][3]), (6 * 3600, 6 * 3600))
        self.assertIn("the last block read at most 6 h old", RULES)

    def test_sweep_delay(self):
        self.assertEqual((RB.MODES["CANONICAL"][4], RB.MODES["DEMO"][4]), (48 * 3600, 3600))
        self.assertIn("48 h (canonical) / 1 h (demo)", RULES)

    def test_limits(self):
        self.assertEqual(RB.MIN_BOND, 10 ** 15)
        self.assertIn("at least 0.001 GEN", RULES)
        self.assertEqual(RB.MAX_HOLDERS, 8)
        self.assertIn("1 to 8 addresses", RULES)
        self.assertEqual(RB.MAX_EXCLUDED, 24)
        self.assertIn("up to 24 extra addresses", RULES)
        self.assertEqual((RB.MAX_PROBE_CALLS, RB.probe_budget(1), RB.probe_budget(8)), (48, 48, 6))
        self.assertIn("as many blocks as 48 balanceOf calls pay for (48 for one LP holder, 6 for eight)", RULES)
        self.assertEqual(RB.MAX_LOGS, 400)
        self.assertIn("At most 400 transfers", RULES)
        self.assertEqual(RB.FIN_SLACK, {"ethereum": 300, "base-sepolia": 1800})
        self.assertIn("(300 on Ethereum, 1,800 on Base Sepolia", RULES)
        self.assertEqual(RB.REPLAY_GRACE_S, 3600)
        self.assertIn("more than 3600 s older", RULES)
        self.assertEqual(RB.MAX_PERIOD_S, 366 * 86400)
        self.assertIn("at most 366 days after creation", RULES)
        self.assertEqual(RB.PAGE_MAX, 50)
        self.assertIn("limit at most 50", RULES)
        self.assertEqual(RB.RPC_TRIES, 4)
        self.assertIn("retried up to 4 times", " ".join(RULES.split()))

    def test_rpcs_and_spans(self):
        for ch, v in RB.CHAINS.items():
            self.assertIn("| %s | %s | %s | %s | %s | %s |" % (ch, v[1][0], v[1][1], v[3][0], v[3][1], fmt(v[2])), RULES)
            for u in set(v[1]) | set(v[3]):
                lim = RB.RPC_LIMITS[u]
                span = fmt(lim[0]) if u in v[1] else "(state only)"
                past = "accepted" if lim[2] else "refused: up to the finalized block"
                self.assertIn("| %s | %s | %d | %s |" % (u, span, lim[1], past), RULES)
        self.assertIn("80,000 blocks on Ethereum, 40,000 on Base Sepolia", RULES)

    def test_refusal_reasons_exist_in_code(self):
        for r in re.findall(r"`([A-Z][A-Z_]+[A-Z])`", RULES):
            if r in ("ACTIVE", "RUGGED", "HELD", "VOID", "CLOSED", "RETURNED", "UNRESOLVED", "SCANNED", "PENDING", "REDISTRIBUTING"):
                continue
            self.assertIn(r, SRC, r)

    def test_statuses(self):
        for s in RB.STATUSES:
            self.assertIn(s, RULES)
        for s in LG.GATE_STATES:
            self.assertIn("| " + s + " |", RULES)

    def test_factories_documented(self):
        self.assertEqual(set(RB.FACTORIES), {"ethereum", "base-sepolia"})
        self.assertIn("Uniswap V2 and SushiSwap on Ethereum, the official Uniswap V2 factory on Base Sepolia", " ".join(RULES.split()))

    def test_share_formula(self):
        self.assertIn("eligible = max(0, min(balanceOf(holder, start block), balanceOf(holder, R-1)) - received from team senders)", RULES)
        self.assertIn("share = bond * eligible // (totalSupply(R-1) - sum of excluded balances at R-1)", RULES)
        self.assertEqual(RB.claim_balance(5, 3, 0), 3)
        self.assertEqual(RB.claim_balance(2, 9, 0), 2)
        self.assertEqual((RB.claim_balance(5, 9, 2), RB.claim_balance(5, 9, 5), RB.claim_balance(5, 9, 50)), (3, 0, 0))
        self.assertIn("bonus = pool * share // base", RULES)
        self.assertEqual((RB.bonus_of(10, 1, 3), RB.bonus_of(10, 3, 3), RB.bonus_of(0, 1, 3), RB.bonus_of(10, 1, 0)), (3, 10, 0, 0))
        self.assertEqual(RB.share_of(10, 1, 3), 3)
        self.assertEqual(RB.share_of(10, 5, 3), 10)
        self.assertEqual(RB.share_of(10, 1, 0), 0)

    def test_views_documented(self):
        for v in ("get_bond", "list_bonds", "bonds_by_token", "bonds_by_team", "list_checks", "get_check", "list_claims",
                  "get_claim", "holder_claims", "get_credit", "get_config", "get_stats"):
            self.assertIn("`%s`" % v, RULES)
            self.assertTrue(hasattr(RB.RugBond, v), v)

    def test_settle_table(self):
        self.assertIn("| HELD or VOID | any time | the team (the whole bond) | RETURNED |", RULES)
        self.assertIn("| RUGGED | after the claim window, somebody claimed | nobody yet: the unclaimed part is set aside for the claimants | REDISTRIBUTING |", RULES)
        self.assertIn("| RUGGED | after the claim window, nobody claimed | the registry's fund (the whole bond) | CLOSED |", RULES)
        self.assertIn("| REDISTRIBUTING | every bonus paid | the registry's fund (the integer leftover) | CLOSED |", RULES)
        self.assertIn("| ACTIVE | after the recovery deadline | the registry's fund (the whole bond) | UNRESOLVED |", RULES)
        self.assertNotIn("victim", RULES.lower())
        self.assertNotIn("victim", SRC.lower())


class NeverFavorable(unittest.TestCase):
    """Every gate answer that is not built from a fresh agreed read of the named bond is unsafe."""

    def test_every_status_and_age_combination(self):
        n = 0
        for st in ("ACTIVE", "HELD", "RETURNED", "RUGGED", "REDISTRIBUTING", "CLOSED", "VOID", "UNRESOLVED", "X"):
            for last in ("", "SCANNED", "PENDING", "HELD", "RUGGED"):
                for n_checks in (0, 1):
                    for age in (0, 10, 10 ** 9):
                        for replay in (False, True):
                            v = {"found": True, "bond_id": 1, "status": st, "token": A(1), "team": A(2), "cursor_ts": max(NOW - age, 0),
                                 "n_checks": n_checks, "claim_deadline": NOW + 5, "replay": replay, "last_result": last}
                            r = LG.gate_state(v, A(1), NOW, 3600)
                            fresh_agreed = st == "ACTIVE" and last != "PENDING" and n_checks > 0 and age <= 3600 and not replay \
                                and v["cursor_ts"] > 0
                            self.assertEqual(r["safe"], fresh_agreed, v)
                            n += 1
        self.assertEqual(n, 9 * 5 * 2 * 3 * 2)

    def test_no_clock_never_safe(self):
        v = {"found": True, "bond_id": 1, "status": "ACTIVE", "token": A(1), "team": A(2), "cursor_ts": NOW, "n_checks": 1,
             "claim_deadline": 0, "replay": False, "last_result": "SCANNED"}
        self.assertFalse(LG.gate_state(v, A(1), 0, 3600)["safe"])

    def test_wrong_token_never_safe(self):
        v = {"found": True, "bond_id": 1, "status": "ACTIVE", "token": A(1), "team": A(2), "cursor_ts": NOW, "n_checks": 1,
             "claim_deadline": 0, "replay": False, "last_result": "SCANNED"}
        self.assertFalse(LG.gate_state(v, A(3), NOW, 3600)["safe"])


if __name__ == "__main__":
    unittest.main()


class RoutersDocumented(unittest.TestCase):
    def test_routers_and_team_senders(self):
        self.assertEqual(set(RB.ROUTERS), set(RB.CHAINS))
        self.assertIn("Team senders", RULES)
        t = {"chain": "ethereum", "pair": A(1), "excluded_all": sorted([A(1), A(2), "0x" + "0" * 40, RB.DEAD, RB.ROUTERS["ethereum"][0]])}
        self.assertEqual(RB.team_senders(t), [A(2)])
