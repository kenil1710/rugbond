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
        # 2 wei are left: they go to the registry's fund, not to a claimant
        self.assertEqual((out["to"], int(out["amount"]), out["status"]), (FUND, 10 ** 18 + 1 - sum(shares), "CLOSED"))
        self.assertEqual([paid_to(w, h) for h in HOLDERS[:3]], shares)

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
    def test_unclaimed_goes_to_the_registry_fund_not_to_claimants(self):
        w, reg, s, bid = rugged()
        w.call(reg, "claim", bid, sender=HOLDERS[0])
        w.advance(601)
        r = w.call(reg, "settle", bid, sender=STRANGER)
        self.assertEqual((r["status"], r["to"], r["amount"]), ("CLOSED", FUND, str(GEN - GEN // 5)))
        self.assertEqual((paid_to(w, HOLDERS[0]), paid_to(w, FUND), paid_to(w, TEAM)), (GEN // 5, GEN - GEN // 5, 0))
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
        out = sum(int(st[k]) for k in ("claims_paid_total", "returned_total", "fund_total", "credit_paid_total",
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


class ClaimLogFlood(unittest.TestCase):
    """A team cannot lock a holder out of its claim by sending it more dust transfers than an endpoint returns."""

    def _cap(self, s, most):
        def cap(req, ans):
            if req["method"] == "eth_getLogs" and isinstance(ans.get("result"), list) and len(ans["result"]) > most:
                return {"jsonrpc": "2.0", "id": req["id"], "error": {"code": -32005, "message": "query returned more than %d results" % most}}
            return ans
        for u in module("RugBond").CHAINS[s.chain][1]:
            stub.WEB.tamper[u] = cap

    def test_300_dust_transfers_to_one_holder_are_summed_through_split_windows(self):
        def setup(s):
            for i in range(300):
                s.tok(1100 + i, TEAM, HOLDERS[0], 1)
        w, reg, s, bid = rugged(setup=setup)
        self._cap(s, 50)
        r = w.call(reg, "claim", bid, sender=HOLDERS[0])
        self.assertEqual((r["from_team"], int(r["balance"])), ("300", 10_000 * GEN - 300))
        self.assertEqual(w.view(reg, "get_claim", bid, HOLDERS[0])["from_team"], "300")

    def test_other_holders_are_not_slowed_by_the_flood(self):
        def setup(s):
            for i in range(300):
                s.tok(1100 + i, TEAM, HOLDERS[0], 1)
        w, reg, s, bid = rugged(setup=setup)
        self._cap(s, 50)
        before = len(stub.WEB.log)
        w.call(reg, "claim", bid, sender=HOLDERS[1])
        # leader + validator: 2 state requests and 2 log requests each
        self.assertLessEqual(len(stub.WEB.log) - before, 8)

    def test_more_dust_in_one_block_than_an_endpoint_returns_is_pending_not_a_wrong_share(self):
        def setup(s):
            for i in range(60):
                s.tok(1200, TEAM, HOLDERS[0], 1)
        w, reg, s, bid = rugged(setup=setup)
        self._cap(s, 50)
        with self.assertRaises(Reverted) as e:
            w.call(reg, "claim", bid, sender=HOLDERS[0])
        self.assertIn("PENDING", e.exception.msg)
        stub.WEB.tamper.clear()
        self.assertEqual(w.call(reg, "claim", bid, sender=HOLDERS[0])["from_team"], "60")

    def test_request_budget(self):
        M = module("RugBond")
        self.assertEqual(M.MAX_CLAIM_LOG_CALLS, 64)

        def setup(s):
            for i in range(400):
                s.tok(1050 + i, TEAM, HOLDERS[0], 1)
        w, reg, s, bid = rugged(setup=setup)
        self._cap(s, 3)                                   # 400 logs at 3 per answer needs far more than 64 requests
        with self.assertRaises(Reverted) as e:
            w.call(reg, "claim", bid, sender=HOLDERS[0])
        self.assertIn("PENDING", e.exception.msg)


class Unclaimed(unittest.TestCase):
    """A claimant receives its own share and nothing else; everything unclaimed goes to the registry's fund."""

    def test_low_turnout_gives_no_bonus(self):
        # one of five holders claims: it gets a fifth, exactly what it gets when all five claim
        w, reg, s, bid = rugged()
        low = int(w.call(reg, "claim", bid, sender=HOLDERS[0])["share"])
        w.advance(601)
        out = close(w, reg, bid)
        w2, reg2, s2, bid2 = rugged()
        full = [int(w2.call(reg2, "claim", bid2, sender=h)["share"]) for h in HOLDERS[:5]]
        w2.advance(601)
        close(w2, reg2, bid2)
        self.assertEqual((low, full[0]), (GEN // 5, GEN // 5))
        self.assertEqual((paid_to(w, HOLDERS[0]), paid_to(w2, HOLDERS[0])), (GEN // 5, GEN // 5))
        self.assertEqual((out["to"], out["amount"]), (FUND, str(GEN - GEN // 5)))
        self.assertEqual(len([t for t in w.transfers if t[1] == HOLDERS[0]]), 1)

    def test_turnout_never_changes_a_share(self):
        for k in range(1, 6):
            w, reg, s, bid = rugged(value=7 * GEN + 3)
            shares = [int(w.call(reg, "claim", bid, sender=h)["share"]) for h in HOLDERS[:k]]
            w.advance(601)
            out = close(w, reg, bid)
            self.assertEqual(shares, [(7 * GEN + 3) // 5] * k)
            self.assertEqual([paid_to(w, h) for h in HOLDERS[:5]], shares + [0] * (5 - k))
            self.assertEqual(paid_to(w, FUND), 7 * GEN + 3 - sum(shares))
            self.assertEqual(out["status"], "CLOSED")
            self.assertEqual(w.view(reg, "get_stats")["balance"], "0")

    def test_team_pre_start_float_gets_only_its_own_share(self):
        # the team holds 30,000 of the 80,000 claimable tokens in an unlisted wallet from before the start block,
        # sets the shortest claim window and is the only claimant: it gets 3/8 of the bond, never the rest
        hidden = A(777)
        def setup(s):
            s.buy(s.start, hidden, 30_000 * GEN)
        w, reg, s, bid = rugged(setup=setup, value=8 * GEN, window=600)
        r = w.call(reg, "claim", bid, sender=hidden)
        self.assertEqual(int(r["share"]), 3 * GEN)
        w.advance(601)
        out = close(w, reg, bid)
        self.assertEqual((paid_to(w, hidden), paid_to(w, TEAM), paid_to(w, FUND)), (3 * GEN, 0, 5 * GEN))
        self.assertEqual((out["to"], out["amount"]), (FUND, str(5 * GEN)))
        with self.assertRaises(Reverted):
            w.call(reg, "claim", bid, sender=hidden)

    def test_nobody_claimed_whole_bond_to_the_fund(self):
        w, reg, s, bid = rugged(value=3 * GEN + 1)
        w.advance(601)
        out = close(w, reg, bid)
        self.assertEqual((out["to"], out["amount"], out["status"]), (FUND, str(3 * GEN + 1), "CLOSED"))
        self.assertEqual((paid_to(w, FUND), paid_to(w, TEAM)), (3 * GEN + 1, 0))
        self.assertEqual(w.view(reg, "get_stats")["balance"], "0")

    def test_rounding_goes_to_the_fund(self):
        w, reg, s, bid = rugged(holders=3, value=10 ** 18 + 1)       # shares 333333333333333333 each
        w.call(reg, "claim", bid, sender=HOLDERS[0])
        w.call(reg, "claim", bid, sender=HOLDERS[1])
        w.advance(601)
        out = close(w, reg, bid)
        self.assertEqual((out["to"], int(out["amount"])), (FUND, 10 ** 18 + 1 - 2 * (10 ** 18 // 3)))
        self.assertEqual((paid_to(w, HOLDERS[0]), paid_to(w, HOLDERS[1])), (10 ** 18 // 3, 10 ** 18 // 3))
        self.assertEqual(w.view(reg, "get_stats")["balance"], "0")

    def test_beneficiary_gets_the_share_only(self):
        w, reg, s, bid = rugged()
        w.call(reg, "commit_beneficiary", bid, A(500), sender=HOLDERS[0])
        w.call(reg, "claim", bid, sender=HOLDERS[0])
        w.advance(601)
        close(w, reg, bid)
        self.assertEqual((paid_to(w, A(500)), paid_to(w, HOLDERS[0]), paid_to(w, FUND)), (GEN // 5, 0, GEN - GEN // 5))

    def test_no_claim_and_no_second_payment_after_close(self):
        w, reg, s, bid = rugged()
        w.call(reg, "claim", bid, sender=HOLDERS[0])
        w.advance(601)
        close(w, reg, bid)
        for h in (HOLDERS[0], HOLDERS[1]):
            with self.assertRaises(Reverted):
                w.call(reg, "claim", bid, sender=h)
        with self.assertRaises(Reverted) as e:
            w.call(reg, "settle", bid, sender=STRANGER)
        self.assertIn("BOND_IS_CLOSED", e.exception.msg)

    def test_no_redistribution_in_the_code(self):
        from pathlib import Path
        M = module("RugBond")
        src = (Path(__file__).resolve().parent.parent / "build" / "RugBond.py").read_text().lower()
        for word in ("bonus", "redistribut"):
            self.assertNotIn(word, src)
        self.assertFalse(hasattr(M.RugBond, "pay_bonus"))
        self.assertNotIn("REDISTRIBUTING", M.STATUSES)

    def test_settler_cannot_redirect(self):
        w, reg, s, bid = rugged()
        w.call(reg, "claim", bid, sender=HOLDERS[0])
        w.advance(601)
        w.call(reg, "settle", bid, sender=TEAM)
        self.assertEqual((paid_to(w, TEAM), paid_to(w, FUND)), (0, GEN - GEN // 5))

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
                self.assertEqual(tot + int(out["amount"]), value)
                self.assertLess(int(out["amount"]), n)
                self.assertEqual(get(w, reg, bid)["status"], "CLOSED")
                self.assertEqual(w.view(reg, "get_stats")["balance"], "0")
            setattr(ShareMatrix, "test_%d_holders_bond_%d" % (n, value), t)


class ShareMatrix(unittest.TestCase):
    pass


_gen_share_cases()

if __name__ == "__main__":
    unittest.main()
