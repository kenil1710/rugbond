"""Claims after RUGGED: shares, rounding, dust, exclusions, contracts, EIP-7702, beneficiary, windows, settle."""
import unittest

from fixtures import (Sim, fresh, bond, check, until_verdict, get, Reverted, TEAM, TEAM2, LOCKER, ROUTER,
                      VICTIM_FUND, HOLDERS, ZERO, DEAD, GEN, STRANGER, BOT, A, module)
import stub


def rugged(holders=5, amount=10_000 * GEN, value=GEN, dust=0, window=600, extra=None, setup=None, **o):
    w, reg = fresh()
    s = Sim().launch(holders=HOLDERS[:holders], holder_amount=amount)
    if setup:
        setup(s)
    s.rug(1500)
    s.install()
    bid = bond(w, reg, s, value=value, dust_floor=dust, claim_window_s=window, excluded=extra or [ROUTER], **o)
    r = until_verdict(w, reg, bid)[-1]
    assert r["result"] == "RUGGED", r
    return w, reg, s, bid


def paid_to(w, who):
    return sum(a for (_, to, a) in w.transfers if to == who)


class Shares(unittest.TestCase):
    def test_equal_holders_equal_shares(self):
        w, reg, s, bid = rugged()
        for h in HOLDERS[:5]:
            self.assertEqual(w.call(reg, "claim", bid, sender=h)["share"], str(GEN // 5))

    def test_share_formula(self):
        def setup(s):
            s.buy(s.start, HOLDERS[7], 30_000 * GEN)
        w, reg, s, bid = rugged(setup=setup)
        b = get(w, reg, bid)
        self.assertEqual(b["denominator"], str(80_000 * GEN))
        r = w.call(reg, "claim", bid, sender=HOLDERS[7])
        self.assertEqual(int(r["share"]), GEN * 30_000 // 80_000)

    def test_rounding_down(self):
        w, reg, s, bid = rugged(holders=3, value=10 ** 18 + 1)
        shares = [int(w.call(reg, "claim", bid, sender=h)["share"]) for h in HOLDERS[:3]]
        self.assertTrue(all(x == (10 ** 18 + 1) // 3 for x in shares))
        w.advance(700)
        r = w.call(reg, "settle", bid, sender=STRANGER)
        self.assertEqual(int(r["amount"]), 10 ** 18 + 1 - sum(shares))

    def test_shares_never_exceed_bond(self):
        w, reg, s, bid = rugged(holders=7, value=7 * GEN + 3)
        tot = sum(int(w.call(reg, "claim", bid, sender=h)["share"]) for h in HOLDERS[:7])
        self.assertLessEqual(tot, 7 * GEN + 3)

    def test_bought_after_start_earns_nothing(self):
        def setup(s):
            s.buy(1499, HOLDERS[9], 10_000 * GEN)       # bought one block before R
        w, reg, s, bid = rugged(setup=setup)
        with self.assertRaises(Reverted) as e:
            w.call(reg, "claim", bid, sender=HOLDERS[9])
        self.assertIn("NO_BALANCE_AT_START_AND_R_MINUS_1", e.exception.msg)

    def test_paid_on_the_lower_of_start_and_r_minus_1(self):
        def setup(s):
            s.tok(1300, HOLDERS[0], s.pair, 4_000 * GEN)   # sold some after the start
            s.buy(1300, HOLDERS[1], 7_000 * GEN)           # bought more after the start
        w, reg, s, bid = rugged(setup=setup)
        self.assertEqual(w.call(reg, "claim", bid, sender=HOLDERS[0])["balance"], str(6_000 * GEN))
        r = w.call(reg, "claim", bid, sender=HOLDERS[1])
        self.assertEqual((r["balance"], r["start_balance"], r["r_balance"]), (str(10_000 * GEN), str(10_000 * GEN), str(17_000 * GEN)))

    def test_held_at_start_sold_all_before_r_earns_nothing(self):
        def setup(s):
            s.tok(1300, HOLDERS[0], s.pair, 10_000 * GEN)
        w, reg, s, bid = rugged(setup=setup)
        with self.assertRaises(Reverted):
            w.call(reg, "claim", bid, sender=HOLDERS[0])

    def test_bought_in_block_r_gets_nothing(self):
        def setup(s):
            s.buy(1500, HOLDERS[9], 10_000 * GEN)
        w, reg, s, bid = rugged(setup=setup)
        with self.assertRaises(Reverted) as e:
            w.call(reg, "claim", bid, sender=HOLDERS[9])
        self.assertIn("NO_BALANCE", e.exception.msg)

    def test_sold_before_r_gets_nothing(self):
        def setup(s):
            s.tok(1300, HOLDERS[0], s.pair, 10_000 * GEN)
        w, reg, s, bid = rugged(setup=setup)
        with self.assertRaises(Reverted):
            w.call(reg, "claim", bid, sender=HOLDERS[0])

    def test_sold_after_r_still_paid(self):
        def setup(s):
            pass
        w, reg, s, bid = rugged()
        self.assertEqual(int(w.call(reg, "claim", bid, sender=HOLDERS[0])["share"]), GEN // 5)

    def test_payout_arrives_at_holder(self):
        w, reg, s, bid = rugged()
        w.call(reg, "claim", bid, sender=HOLDERS[0])
        self.assertEqual(paid_to(w, HOLDERS[0]), GEN // 5)

    def test_excluded_balances_out_of_denominator(self):
        def setup(s):
            s.tok(1200, TEAM, ROUTER, 50_000 * GEN)
        w, reg, s, bid = rugged(setup=setup)
        self.assertEqual(get(w, reg, bid)["denominator"], str(50_000 * GEN))

    def test_contract_holder_in_denominator_and_refused(self):
        def setup(s):
            s.tok(1200, TEAM, BOT, 50_000 * GEN)
        w, reg, s, bid = rugged(setup=setup)
        self.assertEqual(get(w, reg, bid)["denominator"], str(100_000 * GEN))
        with self.assertRaises(Reverted) as e:
            w.call(reg, "claim", bid, sender=BOT)
        self.assertIn("CONTRACT_HOLDER", e.exception.msg)
        self.assertEqual(int(w.call(reg, "claim", bid, sender=HOLDERS[0])["share"]), GEN // 10)

    def test_eip7702_delegated_eoa_can_claim(self):
        def setup(s):
            s.c.code[HOLDERS[0]] = "0xef0100" + "ab" * 20
        w, reg, s, bid = rugged(setup=setup)
        self.assertEqual(int(w.call(reg, "claim", bid, sender=HOLDERS[0])["share"]), GEN // 5)

    def test_code_with_7702_prefix_but_longer_is_contract(self):
        def setup(s):
            s.c.code[HOLDERS[0]] = "0xef0100" + "ab" * 21
        w, reg, s, bid = rugged(setup=setup)
        with self.assertRaises(Reverted):
            w.call(reg, "claim", bid, sender=HOLDERS[0])


class Refusals(unittest.TestCase):
    def test_double_claim(self):
        w, reg, s, bid = rugged()
        w.call(reg, "claim", bid, sender=HOLDERS[0])
        with self.assertRaises(Reverted) as e:
            w.call(reg, "claim", bid, sender=HOLDERS[0])
        self.assertIn("ALREADY_CLAIMED", e.exception.msg)

    def test_team_cannot_claim(self):
        w, reg, s, bid = rugged()
        with self.assertRaises(Reverted) as e:
            w.call(reg, "claim", bid, sender=TEAM)
        self.assertIn("EXCLUDED", e.exception.msg)

    def test_each_automatic_exclusion(self):
        w, reg, s, bid = rugged()
        for who in (TEAM, s.pair, s.token, ZERO, DEAD, ROUTER):
            with self.assertRaises(Reverted, msg=who):
                w.call(reg, "claim", bid, sender=who)

    def test_lp_holder_excluded(self):
        w, reg, s, bid = rugged(lp_holders=[TEAM, LOCKER])
        with self.assertRaises(Reverted):
            w.call(reg, "claim", bid, sender=LOCKER)

    def test_extra_excluded_team_wallet(self):
        def setup(s):
            s.tok(1200, TEAM, TEAM2, 10_000 * GEN)
        w, reg, s, bid = rugged(setup=setup, extra=[ROUTER, TEAM2])
        with self.assertRaises(Reverted):
            w.call(reg, "claim", bid, sender=TEAM2)
        self.assertEqual(get(w, reg, bid)["denominator"], str(50_000 * GEN))

    def test_fresh_team_wallet_funded_after_start_refused(self):
        def setup(s):
            s.tok(1200, TEAM, TEAM2, 10_000 * GEN)
        w, reg, s, bid = rugged(setup=setup)
        with self.assertRaises(Reverted) as e:
            w.call(reg, "claim", bid, sender=TEAM2)
        self.assertIn("RECEIVED_FROM_EXCLUDED_ADDRESS", e.exception.msg)

    def test_claim_after_window(self):
        w, reg, s, bid = rugged(window=600)
        w.advance(601)
        with self.assertRaises(Reverted) as e:
            w.call(reg, "claim", bid, sender=HOLDERS[0])
        self.assertIn("CLAIM_WINDOW_OVER", e.exception.msg)

    def test_claim_at_window_edge(self):
        w, reg, s, bid = rugged(window=600)
        w.advance(600)
        w.call(reg, "claim", bid, sender=HOLDERS[0])

    def test_claim_on_active_bond(self):
        w, reg = fresh()
        s = Sim().launch().install()
        bid = bond(w, reg, s)
        with self.assertRaises(Reverted) as e:
            w.call(reg, "claim", bid, sender=HOLDERS[0])
        self.assertIn("BOND_IS_ACTIVE", e.exception.msg)

    def test_claim_on_held_bond(self):
        w, reg = fresh()
        s = Sim().launch().install()
        bid = bond(w, reg, s)
        until_verdict(w, reg, bid)
        with self.assertRaises(Reverted):
            w.call(reg, "claim", bid, sender=HOLDERS[0])

    def test_wrong_bond(self):
        w, reg, s, bid = rugged()
        with self.assertRaises(Reverted):
            w.call(reg, "claim", bid + 1, sender=HOLDERS[0])

    def test_claim_on_closed_bond(self):
        w, reg, s, bid = rugged()
        w.advance(700)
        w.call(reg, "settle", bid, sender=STRANGER)
        with self.assertRaises(Reverted) as e:
            w.call(reg, "claim", bid, sender=HOLDERS[0])
        self.assertIn("BOND_IS_CLOSED", e.exception.msg)

    def test_dust_floor(self):
        w, reg, s, bid = rugged(dust=GEN // 5 + 1)
        with self.assertRaises(Reverted) as e:
            w.call(reg, "claim", bid, sender=HOLDERS[0])
        self.assertIn("DUST", e.exception.msg)

    def test_dust_floor_exact_share_passes(self):
        w, reg, s, bid = rugged(dust=GEN // 5)
        w.call(reg, "claim", bid, sender=HOLDERS[0])

    def test_zero_share_refused_without_dust_floor(self):
        def setup(s):
            s.buy(s.start, HOLDERS[11], 1)
        w, reg, s, bid = rugged(setup=setup, value=10 ** 15)
        with self.assertRaises(Reverted):
            w.call(reg, "claim", bid, sender=HOLDERS[11])

    def test_failed_claim_changes_nothing(self):
        w, reg, s, bid = rugged()
        before = w.view(reg, "get_stats")
        with self.assertRaises(Reverted):
            w.call(reg, "claim", bid, sender=TEAM)
        self.assertEqual(w.view(reg, "get_stats"), before)


class Beneficiary(unittest.TestCase):
    def test_paid_to_beneficiary(self):
        w, reg, s, bid = rugged()
        w.call(reg, "commit_beneficiary", bid, A(500), sender=HOLDERS[0])
        r = w.call(reg, "claim", bid, sender=HOLDERS[0])
        self.assertEqual(r["payee"], A(500))
        self.assertEqual(paid_to(w, A(500)), GEN // 5)
        self.assertEqual(paid_to(w, HOLDERS[0]), 0)

    def test_commit_before_rug(self):
        w, reg = fresh()
        s = Sim().launch(holders=HOLDERS[:5])
        s.rug(1500)
        s.install(fin=1100)
        bid = bond(w, reg, s)
        w.call(reg, "commit_beneficiary", bid, A(501), sender=HOLDERS[1])
        check(w, reg, bid)
        s.install(fin=5000)
        until_verdict(w, reg, bid)
        self.assertEqual(w.call(reg, "claim", bid, sender=HOLDERS[1])["payee"], A(501))

    def test_commit_once(self):
        w, reg, s, bid = rugged()
        w.call(reg, "commit_beneficiary", bid, A(500), sender=HOLDERS[0])
        with self.assertRaises(Reverted) as e:
            w.call(reg, "commit_beneficiary", bid, A(502), sender=HOLDERS[0])
        self.assertIn("ALREADY_COMMITTED", e.exception.msg)

    def test_commit_after_claim_refused(self):
        w, reg, s, bid = rugged()
        w.call(reg, "claim", bid, sender=HOLDERS[0])
        with self.assertRaises(Reverted):
            w.call(reg, "commit_beneficiary", bid, A(500), sender=HOLDERS[0])

    def test_bad_beneficiary(self):
        w, reg, s, bid = rugged()
        for b in ("", "0x12", ZERO, DEAD, "not an address"):
            with self.assertRaises(Reverted, msg=b):
                w.call(reg, "commit_beneficiary", bid, b, sender=HOLDERS[0])

    def test_beneficiary_per_bond(self):
        w, reg, s, bid = rugged()
        w.call(reg, "commit_beneficiary", bid, A(500), sender=HOLDERS[0])
        self.assertEqual(w.view(reg, "get_claim", bid, HOLDERS[0])["beneficiary"], A(500))
        self.assertEqual(w.view(reg, "get_claim", bid, HOLDERS[1])["beneficiary"], "")

    def test_someone_else_cannot_commit_for_holder(self):
        w, reg, s, bid = rugged()
        w.call(reg, "commit_beneficiary", bid, A(500), sender=STRANGER)
        self.assertEqual(w.call(reg, "claim", bid, sender=HOLDERS[0])["payee"], HOLDERS[0])

    def test_commit_on_settled_bond_refused(self):
        w, reg, s, bid = rugged()
        w.advance(700)
        w.call(reg, "settle", bid, sender=STRANGER)
        with self.assertRaises(Reverted):
            w.call(reg, "commit_beneficiary", bid, A(500), sender=HOLDERS[0])


class Settle(unittest.TestCase):
    def test_unclaimed_to_victim_fund(self):
        w, reg, s, bid = rugged()
        w.call(reg, "claim", bid, sender=HOLDERS[0])
        w.advance(601)
        r = w.call(reg, "settle", bid, sender=STRANGER)
        self.assertEqual((r["to"], r["amount"], r["status"]), (VICTIM_FUND, str(GEN - GEN // 5), "CLOSED"))
        self.assertEqual(paid_to(w, VICTIM_FUND), GEN - GEN // 5)

    def test_settle_during_window_refused(self):
        w, reg, s, bid = rugged()
        with self.assertRaises(Reverted) as e:
            w.call(reg, "settle", bid, sender=STRANGER)
        self.assertIn("CLAIM_WINDOW_OPEN", e.exception.msg)

    def test_settle_twice_refused(self):
        w, reg, s, bid = rugged()
        w.advance(601)
        w.call(reg, "settle", bid, sender=STRANGER)
        with self.assertRaises(Reverted):
            w.call(reg, "settle", bid, sender=STRANGER)

    def test_all_claimed_settles_zero(self):
        w, reg, s, bid = rugged(value=5 * GEN)
        for h in HOLDERS[:5]:
            w.call(reg, "claim", bid, sender=h)
        w.advance(601)
        r = w.call(reg, "settle", bid, sender=STRANGER)
        self.assertEqual(r["amount"], "0")
        self.assertEqual(w.view(reg, "get_stats")["balance"], "0")

    def test_held_returns_to_team_not_settler(self):
        w, reg = fresh()
        s = Sim().launch().install()
        bid = bond(w, reg, s, value=3 * GEN)
        until_verdict(w, reg, bid)
        r = w.call(reg, "settle", bid, sender=STRANGER)
        self.assertEqual((r["to"], r["amount"]), (TEAM, str(3 * GEN)))
        self.assertEqual(paid_to(w, TEAM), 3 * GEN)

    def test_active_before_recovery_refused(self):
        w, reg = fresh()
        s = Sim(fin=1050).launch().install()
        bid = bond(w, reg, s)
        with self.assertRaises(Reverted):
            w.call(reg, "settle", bid, sender=STRANGER)

    def test_unresolved_after_recovery_to_victim_fund(self):
        w, reg = fresh()
        s = Sim(fin=1050).launch().install()
        bid = bond(w, reg, s)
        b = get(w, reg, bid)
        w.set_time(b["recovery_deadline"] + 1)
        r = w.call(reg, "settle", bid, sender=STRANGER)
        self.assertEqual((r["status"], r["to"]), ("UNRESOLVED", VICTIM_FUND))

    def test_check_refused_after_recovery(self):
        w, reg = fresh()
        s = Sim(fin=1050).launch().install()
        bid = bond(w, reg, s)
        w.set_time(get(w, reg, bid)["recovery_deadline"] + 1)
        with self.assertRaises(Reverted) as e:
            check(w, reg, bid)
        self.assertIn("RECOVERY_WINDOW_OVER", e.exception.msg)


class Conservation(unittest.TestCase):
    def _ledger(self, w, reg):
        st = w.view(reg, "get_stats")
        out = sum(int(st[k]) for k in ("claims_paid_total", "returned_total", "victim_total", "credit_paid_total",
                                       "stray_swept_total"))
        self.assertEqual(int(st["received_total"]), int(st["held"]) + out)
        self.assertEqual(int(st["balance"]), int(st["held"]))
        return st

    def test_many_bonds_mixed(self):
        w, reg = fresh()
        sims = []
        for i in range(6):
            s = Sim(token=A(300 + i), pair=A(400 + i)).launch(holders=HOLDERS[:4])
            if i % 2 == 0:
                s.rug(1300 + i)
            sims.append(s)
        bids = []
        for s in sims:
            s.install()
            bids.append(bond(w, reg, s, value=(1 + len(bids)) * GEN))
            until_verdict(w, reg, bids[-1])
            self._ledger(w, reg)
        for bid, s in zip(bids, sims):
            if get(w, reg, bid)["status"] == "RUGGED":
                s.install()
                for h in HOLDERS[:3]:
                    w.call(reg, "claim", bid, sender=h)
                    self._ledger(w, reg)
        w.advance(700)
        for bid in bids:
            w.call(reg, "settle", bid, sender=STRANGER)
            self._ledger(w, reg)
        st = self._ledger(w, reg)
        self.assertEqual(st["balance"], "0")
        self.assertEqual(int(st["received_total"]), 21 * GEN)


def _gen_share_cases():
    for n in (1, 2, 3, 7, 13):
        for value in (10 ** 15, 10 ** 18, 10 ** 18 + 7, 123456789 * 10 ** 12):
            def t(self, n=n, value=value):
                w, reg, s, bid = rugged(holders=n, value=value)
                tot = 0
                for h in HOLDERS[:n]:
                    tot += int(w.call(reg, "claim", bid, sender=h)["share"])
                self.assertEqual(tot, (value // n) * n)
                w.advance(601)
                r = w.call(reg, "settle", bid, sender=STRANGER)
                self.assertEqual(int(r["amount"]), value - tot)
                self.assertEqual(w.view(reg, "get_stats")["balance"], "0")
            setattr(ShareMatrix, "test_%d_holders_bond_%d" % (n, value), t)


class ShareMatrix(unittest.TestCase):
    pass


_gen_share_cases()

if __name__ == "__main__":
    unittest.main()
