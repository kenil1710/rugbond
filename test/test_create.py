"""Bond creation: frozen terms, every refusal credits the value back, credits, stray sweep, pagination."""
import json
import unittest

from fixtures import (Sim, fresh, bond, create, terms, check, until_verdict, get, Reverted, TEAM, TEAM2, LOCKER,
                      ROUTER, VICTIM_FUND, HOLDERS, ZERO, DEAD, GEN, STRANGER, NOW, A, module)


class Refusals(unittest.TestCase):
    CASES = [
        ("chain", "polygon", "UNSUPPORTED_CHAIN"),
        ("chain", "ethereum", "UNSUPPORTED_CHAIN"),           # DEMO allows base-sepolia only
        ("token", "0x12", "BAD_TOKEN_OR_PAIR"),
        ("token", ZERO, "BAD_TOKEN_OR_PAIR"),
        ("pair", "", "BAD_TOKEN_OR_PAIR"),
        ("lp_holders", [], "LP_HOLDERS_EMPTY"),
        ("lp_holders", ["nope"], "LP_HOLDERS_BAD_ADDRESS"),
        ("lp_holders", [A(i) for i in range(9)], "LP_HOLDERS_TOO_MANY"),
        ("min_lp", 0, "MIN_LP_INVALID"),
        ("min_lp", -5, "MIN_LP_INVALID"),
        ("min_lp", "abc", "MIN_LP_INVALID"),
        ("min_lp", 2 ** 256, "MIN_LP_INVALID"),
        ("start_block", 0, "START_BLOCK_INVALID"),
        ("start_block", -1, "START_BLOCK_INVALID"),
        ("end_time", 0, "END_TIME_INVALID"),
        ("end_time", NOW + 367 * 86400, "END_TIME_INVALID"),
        ("claim_window_s", 59, "CLAIM_WINDOW_INVALID"),
        ("claim_window_s", 181 * 86400, "CLAIM_WINDOW_INVALID"),
        ("victim_fund", "", "VICTIM_FUND_INVALID"),
        ("victim_fund", ZERO, "VICTIM_FUND_INVALID"),
        ("victim_fund", DEAD, "VICTIM_FUND_INVALID"),
        ("victim_fund", TEAM, "VICTIM_FUND_IS_TEAM"),
        ("excluded", [A(i) for i in range(25)], "EXCLUDED_TOO_MANY"),
        ("excluded", ["0xzz"], "EXCLUDED_BAD_ADDRESS"),
        ("dust_floor", -1, "DUST_FLOOR_INVALID"),
        ("name", "   ", "NAME_REQUIRED"),
    ]

    def _refused(self, key, val, why, value=GEN):
        w, reg = fresh()
        s = Sim()
        t = terms(s, **{key: val})
        r = create(w, reg, t, value=value)
        self.assertFalse(r["ok"])
        self.assertEqual(r["reason"], why)
        self.assertEqual(r["credited"], str(value))
        self.assertEqual(w.view(reg, "get_credit", TEAM)["credit"], str(value))
        self.assertEqual(w.view(reg, "get_stats")["bonds"], 0)
        return w, reg


def _gen():
    for i, (k, v, why) in enumerate(Refusals.CASES):
        def t(self, k=k, v=v, why=why):
            self._refused(k, v, why)
        setattr(Refusals, "test_refuse_%02d_%s_%s" % (i, k, why.lower()), t)


_gen()


class More(unittest.TestCase):
    def test_bond_below_minimum(self):
        w, reg = fresh()
        r = create(w, reg, terms(Sim()), value=10 ** 15 - 1)
        self.assertEqual(r["reason"], "BOND_BELOW_MINIMUM")

    def test_zero_value_refused_no_credit(self):
        w, reg = fresh()
        r = create(w, reg, terms(Sim()), value=0)
        self.assertEqual((r["ok"], r["credited"]), (False, "0"))

    def test_victim_fund_cannot_be_lp_holder(self):
        w, reg = fresh()
        r = create(w, reg, terms(Sim(), lp_holders=[TEAM, LOCKER], victim_fund=LOCKER))
        self.assertEqual(r["reason"], "VICTIM_FUND_IS_LP_HOLDER")

    def test_victim_fund_cannot_be_excluded(self):
        w, reg = fresh()
        r = create(w, reg, terms(Sim(), excluded=[VICTIM_FUND]))
        self.assertEqual(r["reason"], "VICTIM_FUND_IS_EXCLUDED")

    def test_lp_holder_cannot_be_pair(self):
        s = Sim()
        w, reg = fresh()
        r = create(w, reg, terms(s, lp_holders=[s.pair]))
        self.assertEqual(r["reason"], "LP_HOLDER_IS_PAIR_OR_TOKEN")

    def test_token_equal_pair(self):
        s = Sim()
        w, reg = fresh()
        r = create(w, reg, terms(s, pair=s.token))
        self.assertEqual(r["reason"], "TOKEN_IS_PAIR")

    def test_canonical_allows_ethereum_and_base_only(self):
        for ch, ok in (("ethereum", True), ("base", True), ("base-sepolia", False)):
            w, reg = fresh("CANONICAL")
            r = create(w, reg, terms(Sim(chain=ch), claim_window_s=3600))
            self.assertEqual(r["ok"], ok, ch)

    def test_canonical_min_claim_window_one_hour(self):
        w, reg = fresh("CANONICAL")
        r = create(w, reg, terms(Sim(chain="base"), claim_window_s=3599))
        self.assertEqual(r["reason"], "CLAIM_WINDOW_INVALID")

    def test_withdraw_credit(self):
        w, reg = fresh()
        create(w, reg, terms(Sim(), victim_fund=TEAM), value=2 * GEN)
        r = w.call(reg, "withdraw_credit", sender=TEAM)
        self.assertEqual(r["withdrawn"], str(2 * GEN))
        self.assertEqual(w.view(reg, "get_stats")["balance"], "0")
        with self.assertRaises(Reverted):
            w.call(reg, "withdraw_credit", sender=TEAM)

    def test_terms_frozen_and_normalized(self):
        w, reg = fresh()
        s = Sim()
        bid = bond(w, reg, s, lp_holders=[LOCKER.upper().replace("0X", "0x"), TEAM, TEAM], excluded=[ROUTER, ROUTER])
        b = get(w, reg, bid)
        self.assertEqual(b["lp_holders"], sorted([TEAM, LOCKER]))
        self.assertEqual(b["excluded"], [ROUTER])
        for a in (TEAM, s.pair, s.token, ZERO, DEAD, LOCKER, ROUTER):
            self.assertIn(a, b["excluded_all"])
        self.assertEqual(b["team"], TEAM)
        self.assertEqual(b["status"], "ACTIVE")

    def test_no_cancel_or_amend_method(self):
        rb = module("RugBond").RugBond
        for name in ("cancel", "amend", "update_terms", "withdraw_bond", "set_terms", "top_up"):
            self.assertFalse(hasattr(rb, name), name)

    def test_recovery_deadline_from_end_or_creation(self):
        w, reg = fresh()
        s = Sim()
        b1 = get(w, reg, bond(w, reg, s, end_time=NOW - 86400))
        self.assertEqual(b1["recovery_deadline"], NOW + module("RugBond").MODES["DEMO"][2])
        b2 = get(w, reg, bond(w, reg, s, end_time=NOW + 86400))
        self.assertEqual(b2["recovery_deadline"], NOW + 86400 + module("RugBond").MODES["DEMO"][2])

    def test_value_on_non_payable_refused(self):
        w, reg = fresh()
        with self.assertRaises(Reverted):
            w.call(reg, "check", 1, value=GEN)

    def test_sweep_stray(self):
        w, reg = fresh()
        bond(w, reg, Sim(), value=GEN)
        w.instances[reg].balance += 5
        self.assertEqual(w.call(reg, "sweep_stray", sender=STRANGER)["swept"], "5")
        self.assertEqual(w.view(reg, "get_stats")["balance"], str(GEN))
        w2, reg2 = fresh()
        w2.instances[reg2].balance += 7
        r = w2.call(reg2, "sweep_stray", sender=STRANGER)
        self.assertEqual(r["swept"], "7")

    def test_sweep_never_touches_bonds(self):
        w, reg = fresh()
        bond(w, reg, Sim(), value=GEN)
        with self.assertRaises(Reverted) as e:
            w.call(reg, "sweep_stray", sender=STRANGER)
        self.assertIn("NO_STRAY", e.exception.msg)

    def test_sweep_waits_after_send(self):
        w, reg = fresh()
        s = Sim().launch().install()
        bid = bond(w, reg, s)
        until_verdict(w, reg, bid)
        w.call(reg, "settle", bid, sender=STRANGER)
        w.instances[reg].balance += 9
        with self.assertRaises(Reverted) as e:
            w.call(reg, "sweep_stray", sender=STRANGER)
        self.assertIn("SENDS_MAY_BE_PENDING", e.exception.msg)
        w.advance(3601)
        self.assertEqual(w.call(reg, "sweep_stray", sender=STRANGER)["swept"], "9")

    def test_constructor_mode(self):
        w, reg = fresh()
        with self.assertRaises(Exception):
            w.deploy("RugBond", "PROD")


class Pagination(unittest.TestCase):
    def test_list_bonds_pages_over_60(self):
        w, reg = fresh()
        s = Sim()
        for i in range(61):
            bond(w, reg, s, value=10 ** 15, name="b%d" % i)
        seen = []
        off = 0
        while off >= 0:
            pg = w.view(reg, "list_bonds", off, 50, NOW)
            self.assertLessEqual(len(pg["items"]), 50)
            seen += [b["bond_id"] for b in pg["items"]]
            off = pg["next_offset"]
        self.assertEqual(seen, list(range(1, 62)))

    def test_limit_clamped(self):
        w, reg = fresh()
        pg = w.view(reg, "list_bonds", -5, 10 ** 6, NOW)
        self.assertEqual((pg["offset"], pg["limit"]), (0, 50))

    def test_bonds_by_token_and_team(self):
        w, reg = fresh()
        s = Sim()
        other = Sim(token=A(333), pair=A(334))
        bond(w, reg, s)
        bond(w, reg, other)
        bond(w, reg, s, sender=TEAM2)
        t = w.view(reg, "bonds_by_token", "base-sepolia", s.token, 0, 50, NOW)
        self.assertEqual([b["bond_id"] for b in t["items"]], [1, 3])
        m = w.view(reg, "bonds_by_team", TEAM, 0, 50, NOW)
        self.assertEqual([b["bond_id"] for b in m["items"]], [1, 2])
        self.assertEqual(w.view(reg, "bonds_by_team", STRANGER, 0, 50, NOW)["total"], 0)

    def test_list_claims_pages(self):
        w, reg = fresh()
        s = Sim().launch(holders=HOLDERS[:20], holder_amount=GEN)
        s.rug(1500)
        s.install()
        bid = bond(w, reg, s)
        until_verdict(w, reg, bid)
        for h in HOLDERS[:20]:
            w.call(reg, "claim", bid, sender=h)
        got = []
        off = 0
        while off >= 0:
            pg = w.view(reg, "list_claims", bid, off, 7)
            got += [c["holder"] for c in pg["items"]]
            off = pg["next_offset"]
        self.assertEqual(got, HOLDERS[:20])
        hc = w.view(reg, "holder_claims", HOLDERS[3], 0, 10)
        self.assertEqual(hc["items"][0]["bond_id"], bid)

    def test_list_checks_pages(self):
        w, reg = fresh()
        s = Sim(fin=1000 + 200000).launch().install()
        bid = bond(w, reg, s, end_time=s.ts(1000) + 4 * 86400)
        until_verdict(w, reg, bid)
        n = get(w, reg, bid)["n_checks"]
        got = []
        off = 0
        while off >= 0:
            pg = w.view(reg, "list_checks", bid, off, 2)
            got += [c["check_id"] for c in pg["items"]]
            off = pg["next_offset"]
        self.assertEqual(len(got), n)

    def test_bond_view_has_keeper_fields(self):
        w, reg = fresh()
        b = get(w, reg, bond(w, reg, Sim()))
        for k in ("bond_id", "team", "chain", "token", "pair", "lp_holders", "min_lp", "start_block", "end_time",
                  "claim_window_s", "victim_fund", "excluded", "dust_floor", "amount", "status", "cursor", "cursor_ts",
                  "n_checks", "n_pending", "last_result", "recovery_deadline", "rug_block", "rug", "denominator",
                  "claim_deadline", "paid", "n_claims", "remaining", "settled_to", "due", "checkable", "replay"):
            self.assertIn(k, b)

    def test_missing_bond_view(self):
        w, reg = fresh()
        self.assertFalse(w.view(reg, "get_bond", 5, NOW)["found"])
        self.assertEqual(w.view(reg, "list_checks", 5, 0, 10)["total"], 0)
        self.assertEqual(w.view(reg, "list_claims", 5, 0, 10)["total"], 0)


if __name__ == "__main__":
    unittest.main()
