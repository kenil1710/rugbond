"""Claims after RUGGED: shares, rounding, dust, exclusions, contracts, EIP-7702, beneficiary, windows, settle."""
import unittest

from fixtures import (Sim, fresh, bond, check, until_verdict, get, close, Reverted, TEAM, TEAM2, LOCKER, ROUTER,
                      FUND, HOLDERS, ZERO, DEAD, GEN, STRANGER, BOT, A, module)
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
        out = close(w, reg, bid)
        # 2 wei are left; 2 * share // (3 shares) is 0 for each claimant, so the leftover goes to the registry's fund
        self.assertEqual([x["bonus"] for x in out["bonuses"]], ["0", "0", "0"])
        self.assertEqual((out["settles"][-1]["to"], int(out["settles"][-1]["amount"])), (FUND, 10 ** 18 + 1 - sum(shares)))

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
        self.assertIn("NO_BALANCE_AT_START_AND_R_MINUS_1", e.exception.msg)

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
    def test_unclaimed_goes_to_the_claimants(self):
        w, reg, s, bid = rugged()
        w.call(reg, "claim", bid, sender=HOLDERS[0])
        w.advance(601)
        r = w.call(reg, "settle", bid, sender=STRANGER)
        self.assertEqual((r["status"], r["pool"], r["base"], r["claims"]), ("REDISTRIBUTING", str(GEN - GEN // 5), str(GEN // 5), 1))
        self.assertEqual(paid_to(w, FUND), 0)
        r = w.call(reg, "pay_bonus", bid, HOLDERS[0], sender=STRANGER)
        self.assertEqual((r["bonus"], r["status"], r["payee"]), (str(GEN - GEN // 5), "CLOSED", HOLDERS[0]))
        self.assertEqual(paid_to(w, HOLDERS[0]), GEN)
        self.assertEqual(w.view(reg, "get_stats")["balance"], "0")

    def test_nobody_claimed_goes_to_the_registry_fund(self):
        w, reg, s, bid = rugged()
        w.advance(601)
        r = w.call(reg, "settle", bid, sender=STRANGER)
        self.assertEqual((r["to"], r["amount"], r["status"]), (FUND, str(GEN), "CLOSED"))
        self.assertEqual(paid_to(w, FUND), GEN)
        self.assertEqual(w.view(reg, "get_config")["fund"], FUND)

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

    def test_settle_refused_while_bonuses_are_unpaid(self):
        w, reg, s, bid = rugged()
        w.call(reg, "claim", bid, sender=HOLDERS[0])
        w.call(reg, "claim", bid, sender=HOLDERS[1])
        w.advance(601)
        w.call(reg, "settle", bid, sender=STRANGER)
        with self.assertRaises(Reverted) as e:
            w.call(reg, "settle", bid, sender=STRANGER)
        self.assertIn("BONUSES_UNPAID_2", e.exception.msg)

    def test_all_claimed_settles_zero(self):
        w, reg, s, bid = rugged(value=5 * GEN)
        for h in HOLDERS[:5]:
            w.call(reg, "claim", bid, sender=h)
        w.advance(601)
        r = w.call(reg, "settle", bid, sender=STRANGER)
        self.assertEqual((r["amount"], r["to"], r["status"]), ("0", "", "CLOSED"))
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

    def test_unresolved_after_recovery_to_the_registry_fund(self):
        w, reg = fresh()
        s = Sim(fin=1050).launch().install()
        bid = bond(w, reg, s)
        b = get(w, reg, bid)
        w.set_time(b["recovery_deadline"] + 1)
        r = w.call(reg, "settle", bid, sender=STRANGER)
        self.assertEqual((r["status"], r["to"]), ("UNRESOLVED", FUND))

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
        out = sum(int(st[k]) for k in ("claims_paid_total", "bonus_paid_total", "returned_total", "fund_total", "credit_paid_total",
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
            for c in w.view(reg, "list_claims", bid, 0, 50)["items"]:
                if get(w, reg, bid)["status"] == "REDISTRIBUTING":
                    w.call(reg, "pay_bonus", bid, c["holder"], sender=STRANGER)
                    self._ledger(w, reg)
            if get(w, reg, bid)["status"] == "REDISTRIBUTING":
                w.call(reg, "settle", bid, sender=STRANGER)
                self._ledger(w, reg)
        st = self._ledger(w, reg)
        self.assertEqual(st["balance"], "0")
        self.assertEqual(int(st["received_total"]), 21 * GEN)


class TeamTransfers(unittest.TestCase):
    """C1: a transfer from the team takes away what it carried, never the holder's whole claim."""

    def _share(self, setup, who=HOLDERS[0], **o):
        w, reg, s, bid = rugged(setup=setup, **o)
        return w, reg, bid, w.call(reg, "claim", bid, sender=who)

    def test_zero_value_dusting_changes_nothing(self):
        def setup(s):
            for h in HOLDERS[:5]:
                s.tok(1200, TEAM, h, 0)
        w, reg, bid, r = self._share(setup)
        self.assertEqual((r["share"], r["from_team"], r["balance"]), (str(GEN // 5), "0", str(10_000 * GEN)))
        for h in HOLDERS[1:5]:
            self.assertEqual(w.call(reg, "claim", bid, sender=h)["share"], str(GEN // 5))

    def test_small_dust_costs_only_the_dust(self):
        def setup(s):
            for h in HOLDERS[:5]:
                s.tok(1200, TEAM, h, 1)
        w, reg, bid, r = self._share(setup)
        # balance at start 10,000; at R-1 10,000 + 1 wei; 1 wei received from the team: eligible 10,000 - 1 wei
        self.assertEqual(r["from_team"], "1")
        self.assertEqual(int(r["balance"]), 10_000 * GEN - 1)
        self.assertEqual(int(r["share"]), GEN * (10_000 * GEN - 1) // (50_000 * GEN + 5))
        self.assertLess(GEN // 5 - int(r["share"]), 10 ** 5)        # a few wei of 0.2 GEN

    def test_dusting_every_holder_many_times_disqualifies_nobody(self):
        def setup(s):
            for i in range(40):
                for h in HOLDERS[:5]:
                    s.tok(1100 + i, TEAM, h, 1)
        w, reg, s, bid = rugged(setup=setup)
        for h in HOLDERS[:5]:
            r = w.call(reg, "claim", bid, sender=h)
            self.assertEqual(r["from_team"], "40")
            self.assertGreater(int(r["share"]), GEN // 5 - 10 ** 6)

    def test_real_team_transfer_is_subtracted(self):
        def setup(s):
            s.tok(1100, HOLDERS[0], A(77), 6_000 * GEN)        # the holder sells 6,000 after the start
            s.tok(1200, TEAM, HOLDERS[0], 6_000 * GEN)         # and the team hands it 6,000
        w, reg, bid, r = self._share(setup)
        # min(10,000 at start, 10,000 at R-1) - 6,000 from the team = 4,000
        self.assertEqual((r["start_balance"], r["r_balance"], r["from_team"], r["balance"]),
                         (str(10_000 * GEN), str(10_000 * GEN), str(6_000 * GEN), str(4_000 * GEN)))
        # the team's own balance fell by 6,000, so the claimable supply is 56,000
        self.assertEqual(int(r["share"]), GEN * 4_000 // 56_000)

    def test_multiple_transfers_are_summed(self):
        def setup(s):
            s.tok(1100, TEAM, HOLDERS[0], 1_000 * GEN)
            s.tok(1200, TEAM, HOLDERS[0], 2_500 * GEN)
            s.tok(1300, TEAM2, HOLDERS[0], 500 * GEN)          # TEAM2 is not excluded here: not a team sender
            s.tok(1400, TEAM, HOLDERS[0], 0)
        def pre(s):
            s.tok(s.start, s.pair, TEAM2, 500 * GEN)
            setup(s)
        w, reg, bid, r = self._share(pre)
        self.assertEqual(r["from_team"], str(3_500 * GEN))
        self.assertEqual(r["balance"], str(6_500 * GEN))

    def test_extra_excluded_wallet_counts_as_team_sender(self):
        def setup(s):
            s.tok(s.start, s.pair, TEAM2, 5_000 * GEN)
            s.tok(1200, TEAM2, HOLDERS[0], 5_000 * GEN)
        w, reg, bid, r = self._share(setup, extra=[ROUTER, TEAM2])
        self.assertEqual((r["from_team"], r["balance"]), (str(5_000 * GEN), str(5_000 * GEN)))

    def test_team_transfer_larger_than_balance_leaves_nothing(self):
        def setup(s):
            s.tok(1200, TEAM, HOLDERS[0], 10_000 * GEN)
        w, reg, s, bid = rugged(setup=setup)
        with self.assertRaises(Reverted) as e:
            w.call(reg, "claim", bid, sender=HOLDERS[0])
        self.assertIn("NOTHING_ELIGIBLE_AFTER_TEAM_TRANSFERS", e.exception.msg)

    def test_transfer_in_the_start_block_is_part_of_the_start_balance(self):
        w, reg = fresh()
        s = Sim().launch(holders=HOLDERS[:4])
        s.tok(s.start, TEAM, HOLDERS[4], 10_000 * GEN)        # an airdrop in the start block itself
        s.rug(1500)
        s.install()
        bid = bond(w, reg, s)
        until_verdict(w, reg, bid)
        r = w.call(reg, "claim", bid, sender=HOLDERS[4])
        self.assertEqual((r["from_team"], r["balance"]), ("0", str(10_000 * GEN)))

    def test_transfer_in_the_rug_block_is_subtracted(self):
        def setup(s):
            s.tok(1500, TEAM, HOLDERS[0], 4_000 * GEN)
        w, reg, bid, r = self._share(setup)
        self.assertEqual((r["from_team"], r["balance"]), (str(4_000 * GEN), str(6_000 * GEN)))

    def test_buys_from_the_pair_and_router_are_not_team_transfers(self):
        router = module("RugBond").ROUTERS["base-sepolia"][0]

        def setup(s):
            s.tok(s.start, s.pair, router, 1_000 * GEN)
            s.buy(1200, HOLDERS[0], 3_000 * GEN)
            s.tok(1300, router, HOLDERS[0], 1_000 * GEN)
        w, reg, bid, r = self._share(setup, extra=[router])
        self.assertEqual((r["from_team"], r["balance"]), ("0", str(10_000 * GEN)))

    def test_team_cannot_wash_its_own_supply_into_a_claim(self):
        # the Medium this replaces: a fresh wallet funded by the team earns nothing, and neither does topping up an old holder
        def setup(s):
            s.tok(1200, TEAM, A(700), 50_000 * GEN)
            s.tok(1300, TEAM, HOLDERS[0], 50_000 * GEN)
        w, reg, s, bid = rugged(setup=setup)
        with self.assertRaises(Reverted):
            w.call(reg, "claim", bid, sender=A(700))
        with self.assertRaises(Reverted):
            w.call(reg, "claim", bid, sender=HOLDERS[0])

    def test_one_rpc_hiding_the_team_transfer_is_pending(self):
        def setup(s):
            s.tok(1200, TEAM, HOLDERS[0], 2_000 * GEN)
        w, reg, s, bid = rugged(setup=setup)
        s.rpcs[1].logs = [lg for lg in s.rpcs[1].logs if not (lg["address"] == s.token and int(lg["blockNumber"], 16) == 1200)]
        with self.assertRaises(Reverted) as e:
            w.call(reg, "claim", bid, sender=HOLDERS[0])
        self.assertIn("PENDING", e.exception.msg)


class Redistribution(unittest.TestCase):
    """C2: what nobody claimed goes to the holders who claimed, pro rata, in one bounded round."""

    def test_pro_rata_math(self):
        def setup(s):
            s.buy(s.start, HOLDERS[7], 30_000 * GEN)
        w, reg, s, bid = rugged(setup=setup, value=8 * GEN)          # 80,000 claimable: 1 GEN per 10,000
        w.call(reg, "claim", bid, sender=HOLDERS[0])                # 1 GEN
        w.call(reg, "claim", bid, sender=HOLDERS[7])                # 3 GEN
        w.advance(601)
        out = close(w, reg, bid)
        self.assertEqual(out["settles"][0]["pool"], str(4 * GEN))
        self.assertEqual([x["bonus"] for x in out["bonuses"]], [str(GEN), str(3 * GEN)])
        self.assertEqual((paid_to(w, HOLDERS[0]), paid_to(w, HOLDERS[7]), paid_to(w, FUND)), (2 * GEN, 6 * GEN, 0))
        self.assertEqual(len(out["settles"]), 1)                    # nothing left over: the last bonus closed the bond
        self.assertEqual(get(w, reg, bid)["status"], "CLOSED")

    def test_rounding_leftover_goes_to_the_registry_fund(self):
        w, reg, s, bid = rugged(holders=3, value=10 ** 18 + 1)       # shares 333333333333333333 each
        w.call(reg, "claim", bid, sender=HOLDERS[0])
        w.call(reg, "claim", bid, sender=HOLDERS[1])
        w.advance(601)
        out = close(w, reg, bid)
        pool = 10 ** 18 + 1 - 2 * (10 ** 18 // 3)
        self.assertEqual(pool % 2, 1)
        self.assertEqual(out["settles"][0]["pool"], str(pool))
        self.assertEqual([int(x["bonus"]) for x in out["bonuses"]], [pool // 2, pool // 2])
        self.assertEqual((out["settles"][1]["to"], out["settles"][1]["amount"], out["settles"][1]["status"]),
                         (FUND, str(pool - 2 * (pool // 2)), "CLOSED"))
        self.assertEqual(w.view(reg, "get_stats")["balance"], "0")

    def test_bonus_goes_to_the_committed_beneficiary(self):
        w, reg, s, bid = rugged()
        w.call(reg, "commit_beneficiary", bid, A(500), sender=HOLDERS[0])
        w.call(reg, "claim", bid, sender=HOLDERS[0])
        w.advance(601)
        close(w, reg, bid)
        self.assertEqual((paid_to(w, A(500)), paid_to(w, HOLDERS[0])), (GEN, 0))

    def test_bonus_once_per_claim(self):
        w, reg, s, bid = rugged()
        w.call(reg, "claim", bid, sender=HOLDERS[0])
        w.call(reg, "claim", bid, sender=HOLDERS[1])
        w.advance(601)
        w.call(reg, "settle", bid, sender=STRANGER)
        w.call(reg, "pay_bonus", bid, HOLDERS[0], sender=STRANGER)
        with self.assertRaises(Reverted) as e:
            w.call(reg, "pay_bonus", bid, HOLDERS[0], sender=STRANGER)
        self.assertIn("BONUS_ALREADY_PAID", e.exception.msg)

    def test_no_bonus_for_someone_who_did_not_claim(self):
        w, reg, s, bid = rugged()
        w.call(reg, "claim", bid, sender=HOLDERS[0])
        w.advance(601)
        w.call(reg, "settle", bid, sender=STRANGER)
        for who in (HOLDERS[1], TEAM, FUND, "nonsense"):
            with self.assertRaises(Reverted) as e:
                w.call(reg, "pay_bonus", bid, who, sender=who if who.startswith("0x") else STRANGER)
            self.assertIn("NO_SUCH_CLAIM", e.exception.msg)

    def test_no_bonus_before_the_window_ends_or_after_close(self):
        w, reg, s, bid = rugged()
        w.call(reg, "claim", bid, sender=HOLDERS[0])
        with self.assertRaises(Reverted) as e:
            w.call(reg, "pay_bonus", bid, HOLDERS[0], sender=STRANGER)
        self.assertIn("BOND_IS_RUGGED", e.exception.msg)
        w.advance(601)
        close(w, reg, bid)
        with self.assertRaises(Reverted) as e:
            w.call(reg, "pay_bonus", bid, HOLDERS[0], sender=STRANGER)
        self.assertIn("BOND_IS_CLOSED", e.exception.msg)

    def test_no_claim_once_redistributing(self):
        w, reg, s, bid = rugged()
        w.call(reg, "claim", bid, sender=HOLDERS[0])
        w.advance(601)
        w.call(reg, "settle", bid, sender=STRANGER)
        with self.assertRaises(Reverted) as e:
            w.call(reg, "claim", bid, sender=HOLDERS[1])
        self.assertIn("BOND_IS_REDISTRIBUTING", e.exception.msg)

    def test_round_is_bounded_by_the_number_of_claims(self):
        w, reg, s, bid = rugged(holders=13, value=13 * GEN + 5)
        for h in HOLDERS[:9]:
            w.call(reg, "claim", bid, sender=h)
        w.advance(601)
        out = close(w, reg, bid)
        self.assertEqual(len(out["bonuses"]), 9)
        b = get(w, reg, bid)
        self.assertEqual((b["n_bonus"], b["n_claims"], b["status"], b["remaining"]), (9, 9, "CLOSED", "0"))
        self.assertEqual(sum(int(x["bonus"]) for x in out["bonuses"]) + int(b["settled_amount"]), int(b["bonus_pool"]))
        self.assertEqual(w.view(reg, "get_stats")["balance"], "0")

    def test_bonus_order_does_not_change_amounts(self):
        got = []
        for order in ((0, 1, 2), (2, 1, 0), (1, 2, 0)):
            def setup(s):
                s.buy(s.start, HOLDERS[7], 7_777 * GEN)
            w, reg, s, bid = rugged(setup=setup, value=10 ** 18 + 11)
            who = [HOLDERS[0], HOLDERS[1], HOLDERS[7]]
            for h in who:
                w.call(reg, "claim", bid, sender=h)
            w.advance(601)
            w.call(reg, "settle", bid, sender=STRANGER)
            res = {}
            for i in order:
                res[who[i]] = w.call(reg, "pay_bonus", bid, who[i], sender=STRANGER)["bonus"]
            got.append([res[h] for h in who])
        self.assertEqual(got[0], got[1])
        self.assertEqual(got[0], got[2])

    def test_anyone_may_run_the_round_and_cannot_redirect_it(self):
        w, reg, s, bid = rugged()
        w.call(reg, "claim", bid, sender=HOLDERS[0])
        w.advance(601)
        w.call(reg, "settle", bid, sender=TEAM)
        r = w.call(reg, "pay_bonus", bid, HOLDERS[0], sender=TEAM)
        self.assertEqual(r["payee"], HOLDERS[0])
        self.assertEqual(paid_to(w, TEAM), 0)

    def test_fund_is_fixed_at_deployment(self):
        import inspect
        from pathlib import Path
        M = module("RugBond")
        src = (Path(__file__).resolve().parent.parent / "build" / "RugBond.py").read_text()
        self.assertEqual(src.count("self.fund = "), 1)
        init = src[src.index("    def __init__(self, mode: str, fund: str)"):src.index("    # --- helpers")]
        self.assertIn("self.fund = f", init)
        self.assertNotIn("victim", src.lower())
        self.assertEqual([n for n in dir(M.RugBond) if "fund" in n.lower() and callable(getattr(M.RugBond, n))], [])
        self.assertEqual(list(inspect.signature(M.RugBond.create_bond).parameters),
                         ["self", "name", "chain", "token", "pair", "lp_holders_json", "min_lp", "start_block", "end_time",
                          "claim_window_s", "excluded_json", "dust_floor"])

    def test_bad_fund_refused_at_deployment(self):
        w, reg = fresh()
        for bad in ("", ZERO, DEAD, "0x12"):
            with self.assertRaises(Exception):
                w.deploy("RugBond", "DEMO", bad)


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
                out = close(w, reg, bid)
                paid = sum(int(x["bonus"]) for x in out["bonuses"])
                self.assertEqual(tot + paid + int(out["settles"][-1]["amount"]), value)
                self.assertLess(int(out["settles"][-1]["amount"]), n)
                self.assertEqual(get(w, reg, bid)["status"], "CLOSED")
                self.assertEqual(w.view(reg, "get_stats")["balance"], "0")
            setattr(ShareMatrix, "test_%d_holders_bond_%d" % (n, value), t)


class ShareMatrix(unittest.TestCase):
    pass


_gen_share_cases()

if __name__ == "__main__":
    unittest.main()
