"""Attack round (docs/ATTACK_REPORT.md): each test is one attack and the property that stops it."""
import json
import unittest

import stub
from fixtures import (close, Sim, fresh, bond, check, until_verdict, get, create, terms, Reverted, TEAM, TEAM2, LOCKER,
                      ROUTER, FUND, HOLDERS, ZERO, DEAD, GEN, STRANGER, BOT, A, T, W, urls, module)


def rugged_with(setup, **o):
    w, reg = fresh()
    s = Sim().launch(holders=HOLDERS[:4])
    setup(s)
    s.rug(1500)
    s.install()
    bid = bond(w, reg, s, **o)
    r = until_verdict(w, reg, bid)[-1]
    assert r["result"] == "RUGGED", r
    return w, reg, s, bid


class Attacks(unittest.TestCase):
    def test_a01_buy_at_r_minus_1_earns_nothing(self):
        # bought after the bond opened: min(balance at start, balance at R-1) = 0
        w, reg, s, bid = rugged_with(lambda s: s.buy(1499, HOLDERS[10], 40_000 * GEN))
        with self.assertRaises(Reverted) as e:
            w.call(reg, "claim", bid, sender=HOLDERS[10])
        self.assertIn("NO_BALANCE_AT_START_AND_R_MINUS_1", e.exception.msg)

    def test_a02_flash_loan_inside_block_r_minus_1_returned_same_block(self):
        # borrow and return within R-1: end-of-block balance is what counts
        def setup(s):
            s.buy(s.start, HOLDERS[10], 40_000 * GEN)
            s.tok(1499, HOLDERS[10], TEAM, 40_000 * GEN)
        w, reg, s, bid = rugged_with(setup)
        with self.assertRaises(Reverted):
            w.call(reg, "claim", bid, sender=HOLDERS[10])

    def test_a03_sybil_split_gains_nothing(self):
        w1, r1, s1, b1 = rugged_with(lambda s: s.buy(s.start, HOLDERS[10], 40_000 * GEN))
        one = int(w1.call(r1, "claim", b1, sender=HOLDERS[10])["share"])

        def split(s):
            for i in range(4):
                s.buy(s.start, HOLDERS[10 + i], 10_000 * GEN)
        w2, r2, s2, b2 = rugged_with(split)
        many = sum(int(w2.call(r2, "claim", b2, sender=HOLDERS[10 + i])["share"]) for i in range(4))
        self.assertLessEqual(many, one)
        self.assertLessEqual(one - many, 4)

    def test_a04_sybil_dust_splitting_blocked_by_dust_floor(self):
        def setup(s):
            for i in range(5):
                s.buy(s.start, HOLDERS[10 + i], 10 ** 6)
        w, reg, s, bid = rugged_with(setup, dust_floor=10 ** 12)
        for i in range(5):
            with self.assertRaises(Reverted):
                w.call(reg, "claim", bid, sender=HOLDERS[10 + i])

    def test_a05_team_funds_fresh_wallet_after_start_refused(self):
        # the team sends tokens to a fresh wallet after the bond opened: it held nothing at the start
        w, reg, s, bid = rugged_with(lambda s: s.tok(1200, TEAM, TEAM2, 40_000 * GEN))
        with self.assertRaises(Reverted) as e:
            w.call(reg, "claim", bid, sender=TEAM2)
        self.assertIn("NO_BALANCE_AT_START_AND_R_MINUS_1", e.exception.msg)

    def test_a05b_team_buys_supply_before_rug_earns_nothing(self):
        # the attack: buy most of the float from the pool (the ETH comes back with the LP), rug, claim
        def setup(s):
            for i in range(4):
                s.buy(1400 + i, A(600 + i), 100_000 * GEN)
        w, reg, s, bid = rugged_with(setup)
        for i in range(4):
            with self.assertRaises(Reverted):
                w.call(reg, "claim", bid, sender=A(600 + i))
        # the honest holders who held at the start are paid
        self.assertEqual(int(w.call(reg, "claim", bid, sender=HOLDERS[0])["share"]), GEN * 10_000 // 440_000)

    def test_a05c_team_funds_wallet_before_start_allowed_unless_excluded(self):
        # funded before the promise began: a holder at the start block, as the rule says; list it to exclude it
        def build(extra):
            w, reg = fresh()
            s = Sim().launch(holders=HOLDERS[:4])
            s.tok(1050, TEAM, TEAM2, 40_000 * GEN)
            s.rug(1500)
            s.install()
            bid = bond(w, reg, s, start_block=1100, excluded=extra)
            until_verdict(w, reg, bid)
            return w, reg, bid
        w, reg, bid = build([ROUTER])
        self.assertGreater(int(w.call(reg, "claim", bid, sender=TEAM2)["share"]), 0)
        w, reg, bid = build([ROUTER, TEAM2])
        with self.assertRaises(Reverted):
            w.call(reg, "claim", bid, sender=TEAM2)

    def test_a05d_received_from_lp_holder_or_token_contract_subtracted(self):
        for sender in (LOCKER, "token"):
            def setup(s, sender=sender):
                frm = s.token if sender == "token" else LOCKER
                s.buy(s.start, HOLDERS[11], 5_000 * GEN)
                s.tok(1100, TEAM, frm, 50_000 * GEN)
                s.tok(1200, frm, HOLDERS[11], 1_000 * GEN)
            w, reg, s, bid = rugged_with(setup, lp_holders=[TEAM, LOCKER])
            r = w.call(reg, "claim", bid, sender=HOLDERS[11])
            # 5,000 at the start, 6,000 at R-1, 1,000 of it from a team sender: 4,000 eligible
            self.assertEqual((r["from_team"], r["balance"]), (str(1_000 * GEN), str(4_000 * GEN)), sender)

    def test_a05e_received_via_router_is_a_buy(self):
        def setup(s):
            r = module("RugBond").ROUTERS["base-sepolia"][0]
            s.buy(s.start, r, 1_000 * GEN)
            s.buy(s.start, HOLDERS[12], 5_000 * GEN)
            s.tok(1200, r, HOLDERS[12], 1_000 * GEN)
        w, reg, s, bid = rugged_with(setup, excluded=[module("RugBond").ROUTERS["base-sepolia"][0]])
        self.assertEqual(int(w.call(reg, "claim", bid, sender=HOLDERS[12])["balance"]), 5_000 * GEN)

    def test_a05f_transfer_from_team_after_r_does_not_count(self):
        def setup(s):
            s.buy(s.start, HOLDERS[13], 5_000 * GEN)
            s.tok(1600, TEAM, HOLDERS[13], 1 * GEN)
        w, reg, s, bid = rugged_with(setup)
        self.assertGreater(int(w.call(reg, "claim", bid, sender=HOLDERS[13])["share"]), 0)

    def test_a05g_transfer_from_team_in_block_r_counts(self):
        def setup(s):
            s.buy(s.start, HOLDERS[13], 5_000 * GEN)
            s.tok(1500, TEAM, HOLDERS[13], 1 * GEN)
        w, reg, s, bid = rugged_with(setup)
        r = w.call(reg, "claim", bid, sender=HOLDERS[13])
        self.assertEqual((r["from_team"], r["balance"]), (str(GEN), str(4_999 * GEN)))

    def test_a05h_transfer_logs_disagree_is_pending(self):
        def setup(s):
            s.buy(s.start, HOLDERS[13], 5_000 * GEN)
        w, reg, s, bid = rugged_with(setup)
        s.rpcs[1].logs.append({"address": s.token, "topics": ["0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef",
                               T(TEAM), T(HOLDERS[13])], "data": W(GEN), "blockNumber": hex(1300), "logIndex": "0x9",
                               "transactionHash": "0x" + "cd" * 32, "removed": False})
        with self.assertRaises(Reverted) as e:
            w.call(reg, "claim", bid, sender=HOLDERS[13])
        self.assertIn("RPC_DISAGREE", e.exception.msg)

    def test_a06_team_wallet_cannot_add_itself_to_exclusions_later(self):
        rb = module("RugBond").RugBond
        self.assertFalse(any(n.startswith("set_") or n.startswith("amend") for n in dir(rb)))

    def test_a07_fake_locker_unlisted_moves_lp_out(self):
        # LP sent to a "locker" that is not listed: the move itself breaks the floor
        w, reg = fresh()
        s = Sim().launch()
        s.lp(1200, TEAM, LOCKER, 1000 * GEN)
        s.install()
        bid = bond(w, reg, s, lp_holders=[TEAM])
        self.assertEqual(until_verdict(w, reg, bid)[-1]["rug_block"], 1200)

    def test_a08_listed_fake_locker_that_releases_is_caught(self):
        # a listed locker contract that lets the team pull: its outflow is read like any holder's
        w, reg = fresh()
        s = Sim().launch()
        s.lp(1100, TEAM, LOCKER, 1000 * GEN)
        s.lp(1300, LOCKER, s.pair, 1000 * GEN)
        s.install()
        bid = bond(w, reg, s, lp_holders=[TEAM, LOCKER])
        self.assertEqual(until_verdict(w, reg, bid)[-1]["rug_block"], 1300)

    def test_a09_lp_moved_to_listed_wallet_still_held(self):
        w, reg = fresh()
        s = Sim().launch()
        s.lp(1100, TEAM, TEAM2, 1000 * GEN)
        s.install()
        bid = bond(w, reg, s, lp_holders=[TEAM, TEAM2])
        self.assertEqual(until_verdict(w, reg, bid)[-1]["result"], "HELD")

    def test_a10_fake_pair_with_lying_balances_is_void(self):
        w, reg = fresh()
        s = Sim().launch()
        s.c.calls[(s.pair, "0xc45a0155")] = T(A(666))      # its own "factory"
        s.install()
        bid = bond(w, reg, s)
        self.assertEqual(check(w, reg, bid)["result"], "VOID")

    def test_a11_fake_pair_claiming_real_factory_is_void(self):
        w, reg = fresh()
        s = Sim().launch()
        for k in list(s.c.calls):
            if k[0] == s.factory:
                s.c.calls[k] = T(A(667))                     # the factory maps the tokens to another pair
        s.install()
        bid = bond(w, reg, s)
        self.assertEqual(check(w, reg, bid)["reason"], "FACTORY_DOES_NOT_KNOW_PAIR")

    def test_a12_rebasing_token_snapshot_is_balanceof_at_r_minus_1(self):
        # rebases change balanceOf without Transfer logs; the snapshot uses balanceOf, so it is what the chain said
        def setup(s):
            s.c.bal[(s.token, HOLDERS[0])].append((1400, 20_000 * GEN))
            s.c.supply[s.token].append((1400, 1_000_000 * GEN + 10_000 * GEN))
        w, reg, s, bid = rugged_with(setup)
        self.assertEqual(get(w, reg, bid)["denominator"], str(50_000 * GEN))
        # a rebase up after the start does not raise the claim: min(start, R-1)
        self.assertEqual(int(w.call(reg, "claim", bid, sender=HOLDERS[0])["share"]), GEN * 10_000 // 50_000)

    def test_a13_fee_on_transfer_token_balances_are_what_holders_hold(self):
        def setup(s):
            s.buy(s.start, HOLDERS[10], 9_000 * GEN)       # 10% fee: the holder ends with 9000
            s.tok(1200, TEAM, s.token, 1_000 * GEN)           # fee to the token contract (excluded)
        w, reg, s, bid = rugged_with(setup)
        self.assertEqual(get(w, reg, bid)["denominator"], str(49_000 * GEN))

    def test_a14_junk_checks_cannot_change_state(self):
        w, reg = fresh()
        s = Sim(fin=1100).launch().install()
        bid = bond(w, reg, s)
        check(w, reg, bid)
        before = get(w, reg, bid)
        for _ in range(5):
            with self.assertRaises(Reverted):
                check(w, reg, bid)
        after = get(w, reg, bid)
        self.assertEqual(before, after)

    def test_a15_junk_checks_on_wrong_bond(self):
        w, reg = fresh()
        for bid in (0, -1, "1; drop", 10 ** 30):
            with self.assertRaises(Reverted):
                check(w, reg, bid)

    def test_a16_double_claim_by_beneficiary_switch(self):
        w, reg, s, bid = rugged_with(lambda s: None)
        w.call(reg, "commit_beneficiary", bid, A(500), sender=HOLDERS[0])
        w.call(reg, "claim", bid, sender=HOLDERS[0])
        with self.assertRaises(Reverted):
            w.call(reg, "commit_beneficiary", bid, A(501), sender=HOLDERS[0])
        with self.assertRaises(Reverted):
            w.call(reg, "claim", bid, sender=HOLDERS[0])

    def test_a17_victim_fund_cannot_be_team(self):
        # a bond has no destination field at all: a team's second wallet cannot be named anywhere
        w, reg = fresh()
        t = terms(Sim())
        self.assertNotIn("victim_fund", t)
        with self.assertRaises(TypeError):
            w.call(reg, "create_bond", t["name"], t["chain"], t["token"], t["pair"], json.dumps(t["lp_holders"]),
                   t["min_lp"], t["start_block"], t["end_time"], t["claim_window_s"], TEAM2,
                   json.dumps(t["excluded"]), t["dust_floor"], sender=TEAM, value=GEN)
        bid = bond(w, reg, Sim().launch().install())
        b = get(w, reg, bid)
        self.assertNotIn("victim_fund", b)
        self.assertEqual(b["fund"], FUND)

    def test_a17b_the_fund_itself_cannot_post_a_bond(self):
        w, reg = fresh()
        r = create(w, reg, terms(Sim()), sender=FUND)
        self.assertEqual(r["reason"], "TEAM_IS_REGISTRY_FUND")
        for o in (dict(lp_holders=[TEAM, FUND]), dict(excluded=[FUND])):
            self.assertEqual(create(w, reg, terms(Sim(), **o))["reason"], "REGISTRY_FUND_IN_TERMS")

    def test_a18_team_cannot_redirect_unclaimed(self):
        w, reg, s, bid = rugged_with(lambda s: None)
        w.advance(601)
        r = w.call(reg, "settle", bid, sender=TEAM)
        self.assertEqual(r["to"], FUND)
        self.assertEqual(sum(a for (_, to, a) in w.transfers if to in (TEAM, TEAM2)), 0)

    def test_a18b_team_second_wallet_gets_nothing_from_any_path(self):
        # rugged with claims, rugged without claims, unresolved: every wei goes to claimants or the registry's fund
        for case in ("claims", "none", "unresolved"):
            if case == "unresolved":
                w, reg = fresh()
                s = Sim().launch().install(fin=1050)
                bid = bond(w, reg, s)
                w.set_time(get(w, reg, bid)["recovery_deadline"] + 1)
            else:
                w, reg, s, bid = rugged_with(lambda s: None)
                if case == "claims":
                    w.call(reg, "claim", bid, sender=HOLDERS[0])
                w.advance(601)
            close(w, reg, bid, sender=TEAM2)
            got = {}
            for (_, to, a) in w.transfers:
                got[to] = got.get(to, 0) + a
            self.assertEqual(sum(got.values()), GEN, case)
            self.assertTrue(set(got) <= {FUND, HOLDERS[0]}, case)
            self.assertEqual(w.view(reg, "get_stats")["balance"], "0", case)

    def test_a19_settle_by_anyone_same_destination(self):
        for who in (TEAM, STRANGER, HOLDERS[0]):
            w, reg = fresh()
            s = Sim().launch().install()
            bid = bond(w, reg, s)
            until_verdict(w, reg, bid)
            self.assertEqual(w.call(reg, "settle", bid, sender=who)["to"], TEAM)

    def test_a20_rpc_lying_on_one_side_never_verdict(self):
        w, reg = fresh()
        s = Sim().launch().install()
        bid = bond(w, reg, s)
        s.rpcs[0].bal[(s.pair, TEAM)] = [(1000, 1000 * GEN), (1200, 0)]
        s.rpcs[0].logs.append({"address": s.pair, "topics": ["0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef", T(TEAM), T(A(9))],
                               "data": W(1000 * GEN), "blockNumber": hex(1200), "logIndex": "0x1", "transactionHash": "0x" + "ab" * 32,
                               "removed": False})
        self.assertEqual(check(w, reg, bid)["result"], "PENDING")

    def test_a21_contract_holder_cannot_claim_even_with_balance(self):
        w, reg, s, bid = rugged_with(lambda s: s.tok(1200, TEAM, BOT, 10_000 * GEN))
        with self.assertRaises(Reverted):
            w.call(reg, "claim", bid, sender=BOT)

    def test_a22_rug_by_burn_to_zero_detected(self):
        w, reg = fresh()
        s = Sim().launch()
        s.lp(1200, TEAM, ZERO, 1000 * GEN)
        s.install()
        bid = bond(w, reg, s)
        self.assertEqual(until_verdict(w, reg, bid)[-1]["rug_block"], 1200)

    def test_a23_probe_flood_cannot_hide_rug(self):
        # many tiny outflows before the rug only slow the scan; the rug block is still the first below the floor
        w, reg = fresh()
        s = Sim().launch()
        for i in range(20):
            s.lp(1010 + i, TEAM, A(9), 1)
        s.rug(1100)
        s.install()
        bid = bond(w, reg, s, min_lp=900 * GEN)
        self.assertEqual(until_verdict(w, reg, bid)[-1]["rug_block"], 1100)

    def test_a24_stalled_bond_goes_to_the_registry_fund(self):
        w, reg = fresh()
        s = Sim().launch()
        s.install(fin=1050)
        bid = bond(w, reg, s)
        check(w, reg, bid)
        w.set_time(get(w, reg, bid)["recovery_deadline"] + 1)
        self.assertEqual(w.call(reg, "settle", bid, sender=TEAM)["to"], FUND)

    def test_a25_share_cannot_exceed_remaining(self):
        # an inconsistent snapshot (balances above the denominator) is capped by what is left
        w, reg, s, bid = rugged_with(lambda s: None, value=GEN)
        b = w.instances[reg].bonds[1]
        b.denom = 1
        r = w.call(reg, "claim", bid, sender=HOLDERS[0])
        self.assertEqual(r["share"], str(GEN))
        with self.assertRaises(Reverted):
            w.call(reg, "claim", bid, sender=HOLDERS[1])

    def test_a26_claimant_is_sender_not_argument(self):
        import inspect
        src = inspect.getsource(module("RugBond").RugBond.claim)
        self.assertIn("who = self._sender()", src)
        self.assertEqual(list(inspect.signature(module("RugBond").RugBond.claim).parameters), ["self", "bond_id"])


if __name__ == "__main__":
    unittest.main()
