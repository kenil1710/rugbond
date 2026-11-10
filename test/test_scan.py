"""Rug checks: the floor, the start and end boundaries, R detection, windows, probes, VOID."""
import unittest

from fixtures import (Sim, fresh, bond, check, until_verdict, get, terms, create, Reverted, TEAM, TEAM2, LOCKER,
                      HOLDERS, ZERO, GEN, STRANGER, AERODROME, A, T, module)


def rug_world(rug_at=None, amount=None, chain="base-sepolia", mode="DEMO", min_lp=900 * GEN, end_s=3600, **o):
    w, reg = fresh(mode)
    s = Sim(chain=chain).launch()
    if rug_at is not None:
        s.rug(rug_at, amount=amount)
    s.install()
    bid = bond(w, reg, s, min_lp=min_lp, end_time=s.ts(s.start) + end_s, **o)
    return w, reg, s, bid


class FloorBoundary(unittest.TestCase):
    def _pull(self, keep):
        w, reg, s, bid = rug_world()
        return w, reg, s, bid

    def test_balance_exactly_at_floor_is_held(self):
        w, reg = fresh()
        s = Sim().launch()
        s.lp(s.start + 50, TEAM, A(9), 100 * GEN)          # 900 left == floor
        s.install()
        bid = bond(w, reg, s, min_lp=900 * GEN)
        self.assertEqual(until_verdict(w, reg, bid)[-1]["result"], "HELD")

    def test_one_wei_below_floor_is_rugged(self):
        w, reg = fresh()
        s = Sim().launch()
        s.lp(s.start + 50, TEAM, A(9), 100 * GEN + 1)
        s.install()
        bid = bond(w, reg, s, min_lp=900 * GEN)
        r = until_verdict(w, reg, bid)[-1]
        self.assertEqual(r["result"], "RUGGED")
        self.assertEqual(r["rug_block"], s.start + 50)

    def test_floor_equal_to_whole_position_any_outflow_rugs(self):
        w, reg = fresh()
        s = Sim().launch()
        s.lp(s.start + 7, TEAM, A(9), 1)
        s.install()
        bid = bond(w, reg, s, min_lp=1000 * GEN)
        self.assertEqual(until_verdict(w, reg, bid)[-1]["rug_block"], s.start + 7)

    def test_floor_above_position_rugs_at_start(self):
        w, reg = fresh()
        s = Sim().launch().install()
        bid = bond(w, reg, s, min_lp=1000 * GEN + 1)
        r = until_verdict(w, reg, bid)[-1]
        self.assertEqual((r["result"], r["rug_block"]), ("RUGGED", s.start))

    def test_partial_pull_above_floor_then_full_pull(self):
        w, reg = fresh()
        s = Sim().launch()
        s.rug(s.start + 10, amount=50 * GEN)
        s.rug(s.start + 30)
        s.install()
        bid = bond(w, reg, s, min_lp=900 * GEN)
        self.assertEqual(until_verdict(w, reg, bid)[-1]["rug_block"], s.start + 30)


class StartEnd(unittest.TestCase):
    def test_rug_in_start_block(self):
        w, reg = fresh()
        s = Sim().launch()
        s.rug(s.start)
        s.install()
        bid = bond(w, reg, s)
        self.assertEqual(until_verdict(w, reg, bid)[-1]["rug_block"], s.start)

    def test_rug_before_start_block_means_floor_broken_at_start(self):
        w, reg = fresh()
        s = Sim(start=1000).launch()
        s.rug(1003)
        s.install()
        bid = bond(w, reg, s, start_block=1010)
        r = until_verdict(w, reg, bid)[-1]
        self.assertEqual((r["result"], r["rug_block"]), ("RUGGED", 1010))

    def test_rug_in_last_block_before_end_time(self):
        w, reg = fresh()
        s = Sim().launch()
        end = s.ts(s.start) + 3600
        last = s.block_at(end)
        s.rug(last)
        s.install()
        bid = bond(w, reg, s, end_time=end)
        r = until_verdict(w, reg, bid)[-1]
        self.assertEqual((r["result"], r["rug_block"]), ("RUGGED", last))

    def test_rug_in_block_with_timestamp_equal_end_time(self):
        w, reg = fresh()
        s = Sim().launch()
        end = s.ts(s.start + 500)
        s.rug(s.start + 500)
        s.install()
        bid = bond(w, reg, s, end_time=end)
        self.assertEqual(until_verdict(w, reg, bid)[-1]["result"], "RUGGED")

    def test_rug_one_block_after_end_time_is_held(self):
        w, reg = fresh()
        s = Sim().launch()
        end = s.ts(s.start + 500)
        s.rug(s.start + 501)
        s.install()
        bid = bond(w, reg, s, end_time=end)
        r = until_verdict(w, reg, bid)[-1]
        self.assertEqual(r["result"], "HELD")
        self.assertEqual(get(w, reg, bid)["rug_block"], 0)

    def test_rug_long_after_end_is_held(self):
        w, reg, s, bid = rug_world(rug_at=1000 + 5000, end_s=600)
        self.assertEqual(until_verdict(w, reg, bid)[-1]["result"], "HELD")

    def test_held_needs_a_block_at_or_after_end(self):
        w, reg = fresh()
        s = Sim(fin=1000 + 100).launch().install()
        bid = bond(w, reg, s, end_time=s.ts(s.start) + 3600)
        r = check(w, reg, bid)
        self.assertEqual(r["result"], "SCANNED")
        self.assertEqual(r["cursor"], 1100)

    def test_held_when_finalized_reaches_end(self):
        w, reg = fresh()
        s = Sim(fin=1100).launch().install()
        bid = bond(w, reg, s, end_time=s.ts(s.start) + 3600)
        check(w, reg, bid)
        s.install(fin=1000 + 1800)
        self.assertEqual(check(w, reg, bid)["result"], "HELD")

    def test_end_exactly_at_cursor_block_timestamp_is_held(self):
        w, reg = fresh()
        s = Sim(fin=1500).launch().install()
        bid = bond(w, reg, s, end_time=s.ts(1500))
        self.assertEqual(check(w, reg, bid)["result"], "HELD")

    def test_end_one_second_after_cursor_is_scanned(self):
        w, reg = fresh()
        s = Sim(fin=1500).launch().install()
        bid = bond(w, reg, s, end_time=s.ts(1500) + 1)
        self.assertEqual(check(w, reg, bid)["result"], "SCANNED")


class Detection(unittest.TestCase):
    def test_first_dip_wins_over_later(self):
        w, reg = fresh()
        s = Sim().launch()
        s.lp(1200, TEAM, A(9), 200 * GEN)            # dip below 900
        s.lp(1300, A(9), TEAM, 200 * GEN)            # restored
        s.rug(1400)
        s.install()
        bid = bond(w, reg, s)
        self.assertEqual(until_verdict(w, reg, bid)[-1]["rug_block"], 1200)

    def test_dip_and_restore_in_same_block_is_not_a_rug(self):
        w, reg = fresh()
        s = Sim().launch()
        s.lp(1200, TEAM, A(9), 200 * GEN)
        s.lp(1200, A(9), TEAM, 200 * GEN)
        s.install()
        bid = bond(w, reg, s)
        self.assertEqual(until_verdict(w, reg, bid)[-1]["result"], "HELD")

    def test_dip_restored_next_block_still_rugged(self):
        w, reg = fresh()
        s = Sim().launch()
        s.lp(1200, TEAM, A(9), 200 * GEN)
        s.lp(1201, A(9), TEAM, 200 * GEN)
        s.install()
        bid = bond(w, reg, s)
        self.assertEqual(until_verdict(w, reg, bid)[-1]["rug_block"], 1200)

    def test_transfer_between_listed_holders_is_held(self):
        w, reg = fresh()
        s = Sim().launch()
        s.lp(1200, TEAM, LOCKER, 1000 * GEN)
        s.install()
        bid = bond(w, reg, s, lp_holders=[TEAM, LOCKER])
        self.assertEqual(until_verdict(w, reg, bid)[-1]["result"], "HELD")

    def test_transfer_to_unlisted_wallet_is_rugged(self):
        w, reg = fresh()
        s = Sim().launch()
        s.lp(1200, TEAM, TEAM2, 1000 * GEN)
        s.install()
        bid = bond(w, reg, s, lp_holders=[TEAM])
        self.assertEqual(until_verdict(w, reg, bid)[-1]["rug_block"], 1200)

    def test_incoming_lp_does_not_create_probe(self):
        w, reg = fresh()
        s = Sim().launch()
        s.lp(1200, ZERO, TEAM, 5 * GEN)
        s.install()
        bid = bond(w, reg, s)
        until_verdict(w, reg, bid)
        c = w.view(reg, "list_checks", bid, 0, 10)["items"][0]
        self.assertEqual([p[0] for p in c["probes"]], [s.start])

    def test_rug_tx_hash_recorded(self):
        w, reg, s, bid = rug_world(rug_at=1100)
        until_verdict(w, reg, bid)
        b = get(w, reg, bid)
        self.assertEqual(len(b["rug"]["txs"]), 1)
        self.assertEqual(b["rug"]["lp_after"], "0")
        self.assertEqual(b["rug"]["lp_before"], str(1000 * GEN))

    def test_rug_records_snapshot(self):
        w, reg, s, bid = rug_world(rug_at=1100)
        until_verdict(w, reg, bid)
        b = get(w, reg, bid)
        self.assertEqual(b["rug"]["supply"], str(1_000_000 * GEN))
        self.assertEqual(b["denominator"], str(50_000 * GEN))

    def test_two_holders_summed(self):
        w, reg = fresh()
        s = Sim().launch()
        s.lp(1100, TEAM, LOCKER, 500 * GEN)
        s.lp(1200, LOCKER, A(9), 450 * GEN)        # 550 total left
        s.install()
        bid = bond(w, reg, s, lp_holders=[TEAM, LOCKER], min_lp=600 * GEN)
        self.assertEqual(until_verdict(w, reg, bid)[-1]["rug_block"], 1200)

    def test_many_outflow_blocks_above_floor_are_probed_in_steps(self):
        w, reg = fresh()
        s = Sim().launch()
        for i in range(15):
            s.lp(1100 + i * 10, TEAM, A(9), GEN)
        s.install()
        bid = bond(w, reg, s, min_lp=900 * GEN)
        out = until_verdict(w, reg, bid)
        self.assertEqual(out[-1]["result"], "HELD")
        self.assertGreaterEqual(len(out), 3)
        for c in w.view(reg, "list_checks", bid, 0, 50)["items"]:
            self.assertLessEqual(len(c["probes"]), module("RugBond").MAX_PROBES)

    def test_rug_after_many_small_outflows_found(self):
        w, reg = fresh()
        s = Sim().launch()
        for i in range(10):
            s.lp(1100 + i * 10, TEAM, A(9), GEN)
        s.rug(1500)
        s.install()
        bid = bond(w, reg, s, min_lp=900 * GEN)
        self.assertEqual(until_verdict(w, reg, bid)[-1]["rug_block"], 1500)

    def test_cursor_never_skips_blocks(self):
        w, reg = fresh()
        s = Sim(fin=1000 + 120000).launch()
        s.install()
        bid = bond(w, reg, s, end_time=s.ts(1000) + 2 * 86400)
        prev = 999
        for c in until_verdict(w, reg, bid):
            pass
        for c in w.view(reg, "list_checks", bid, 0, 50)["items"]:
            self.assertEqual(c["a"], prev + 1)
            prev = c["b"]

    def test_window_size_per_chain(self):
        rb = module("RugBond")
        for ch in ("ethereum", "base", "base-sepolia"):
            w, reg = fresh("DEMO" if ch == "base-sepolia" else "CANONICAL")
            s = Sim(chain=ch, fin=1000 + 10 ** 6).launch().install()
            bid = bond(w, reg, s, end_time=s.ts(1000) + 30 * 86400, claim_window_s=3600)
            r = check(w, reg, bid)
            self.assertEqual(r["cursor"] - 1000 + 1, rb.CHAINS[ch][2] * rb.CHAINS[ch][3], ch)

    def test_log_requests_respect_window(self):
        w, reg = fresh("CANONICAL")
        s = Sim(chain="base", fin=1000 + 10 ** 5).launch()
        s.install()
        for c in s.rpcs:
            c.log_span = 1000
        bid = bond(w, reg, s, end_time=s.ts(1000) + 30 * 86400, claim_window_s=3600)
        self.assertEqual(check(w, reg, bid)["result"], "SCANNED")


class PairValidity(unittest.TestCase):
    def _void(self, mutate):
        w, reg = fresh()
        s = Sim().launch()
        mutate(s)
        s.install()
        bid = bond(w, reg, s)
        r = check(w, reg, bid)
        return r, get(w, reg, bid)

    def test_token_not_in_pair_is_void(self):
        r, b = self._void(lambda s: s.c.calls.__setitem__((s.pair, "0x0dfe1681"), T(A(77))) or
                          s.c.calls.__setitem__((s.pair, "0xd21220a7"), T(A(78))))
        self.assertEqual((r["result"], r["reason"], b["status"]), ("VOID", "TOKEN_NOT_IN_PAIR", "VOID"))

    def test_unknown_factory_is_void(self):
        r, b = self._void(lambda s: s.c.calls.__setitem__((s.pair, "0xc45a0155"), T(A(79))))
        self.assertEqual(r["reason"], "UNKNOWN_FACTORY")

    def test_factory_not_mapping_pair_is_void(self):
        def m(s):
            for k in list(s.c.calls):
                if k[0] == s.factory:
                    s.c.calls[k] = T(A(80))
        r, b = self._void(m)
        self.assertEqual(r["reason"], "FACTORY_DOES_NOT_KNOW_PAIR")

    def test_not_a_pair_is_void(self):
        r, b = self._void(lambda s: s.c.calls.pop((s.pair, "0xc45a0155")))
        self.assertIn(r["result"], ("VOID", "PENDING"))

    def test_void_returns_bond_to_team(self):
        w, reg = fresh()
        s = Sim().launch()
        s.c.calls[(s.pair, "0xc45a0155")] = T(A(79))
        s.install()
        bid = bond(w, reg, s)
        check(w, reg, bid)
        r = w.call(reg, "settle", bid, sender=STRANGER)
        self.assertEqual((r["status"], r["to"]), ("RETURNED", TEAM))

    def test_aerodrome_volatile_pool_accepted(self):
        w, reg = fresh("CANONICAL")
        s = Sim(chain="base", factory=AERODROME).launch().install()
        bid = bond(w, reg, s, claim_window_s=3600)
        self.assertNotEqual(check(w, reg, bid)["result"], "VOID")

    def test_pair_checked_only_on_first_check(self):
        w, reg = fresh()
        s = Sim(fin=1050).launch().install()
        bid = bond(w, reg, s)
        check(w, reg, bid)
        s.c.calls[(s.pair, "0xc45a0155")] = T(A(79))
        s.install(fin=3000)
        self.assertNotEqual(check(w, reg, bid)["result"], "VOID")


class Replay(unittest.TestCase):
    def test_old_start_block_marks_replay(self):
        w, reg = fresh()
        s = Sim(fin=1000 + 20000).launch().install()
        bid = bond(w, reg, s)
        check(w, reg, bid)
        self.assertTrue(get(w, reg, bid)["replay"])

    def test_recent_start_block_is_not_replay(self):
        w, reg = fresh()
        s = Sim(start=1000, fin=1000 + 100).launch().install()
        bid = bond(w, reg, s, end_time=s.ts(1000) + 3600)
        check(w, reg, bid)
        b = get(w, reg, bid)
        self.assertFalse(b["replay"])
        self.assertEqual(b["start_ts"], s.ts(1000))


class NothingNew(unittest.TestCase):
    def test_check_with_no_new_finalized_block_refused(self):
        w, reg = fresh()
        s = Sim(fin=1100).launch().install()
        bid = bond(w, reg, s)
        check(w, reg, bid)
        with self.assertRaises(Reverted) as e:
            check(w, reg, bid)
        self.assertIn("NOTHING_NEW_FINALIZED", e.exception.msg)
        self.assertEqual(get(w, reg, bid)["n_checks"], 1)

    def test_start_block_not_yet_finalized_refused(self):
        w, reg = fresh()
        s = Sim(fin=990).launch().install()
        bid = bond(w, reg, s)
        with self.assertRaises(Reverted):
            check(w, reg, bid)

    def test_check_after_verdict_refused(self):
        w, reg, s, bid = rug_world(rug_at=1100)
        until_verdict(w, reg, bid)
        with self.assertRaises(Reverted) as e:
            check(w, reg, bid)
        self.assertIn("BOND_IS_RUGGED", e.exception.msg)

    def test_check_unknown_bond(self):
        w, reg = fresh()
        with self.assertRaises(Reverted):
            check(w, reg, 9)


def _gen_floor_cases():
    """Generated boundary matrix: amount pulled vs floor (one test each)."""
    for keep in (0, 1, 899, 900, 901, 999, 1000):
        def t(self, keep=keep):
            w, reg = fresh()
            s = Sim().launch()
            pulled = 1000 * GEN - keep * GEN
            if pulled > 0:
                s.lp(1300, TEAM, A(9), pulled)
            s.install()
            bid = bond(w, reg, s, min_lp=900 * GEN)
            r = until_verdict(w, reg, bid)[-1]
            self.assertEqual(r["result"], "RUGGED" if keep < 900 else "HELD")
        setattr(FloorMatrix, "test_keep_%d_of_1000" % keep, t)
    for blk in (1000, 1001, 1500, 2799, 2800, 2801, 3000):
        def t(self, blk=blk):
            w, reg = fresh()
            s = Sim().launch()
            s.rug(blk)
            s.install()
            end = s.ts(2800)
            bid = bond(w, reg, s, end_time=end)
            r = until_verdict(w, reg, bid)[-1]
            self.assertEqual(r["result"], "RUGGED" if blk <= 2800 else "HELD")
        setattr(FloorMatrix, "test_rug_at_block_%d_end_2800" % blk, t)
    for fin in (1000, 1001, 2000, 2799, 2800, 5000):
        def t(self, fin=fin):
            w, reg = fresh()
            s = Sim(fin=fin).launch().install()
            bid = bond(w, reg, s, end_time=s.ts(2800))
            r = check(w, reg, bid)
            self.assertEqual(r["result"], "HELD" if fin >= 2800 else "SCANNED")
            self.assertEqual(r["cursor"], fin)
        setattr(FloorMatrix, "test_finalized_%d_end_2800" % fin, t)


class FloorMatrix(unittest.TestCase):
    pass


_gen_floor_cases()

if __name__ == "__main__":
    unittest.main()
