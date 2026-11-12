"""Read failures and disagreements: PENDING, never a verdict; consensus behavior; recovery window."""
import json
import unittest

import stub
from fixtures import (Sim, fresh, bond, check, until_verdict, get, Reverted, TEAM, HOLDERS, GEN, STRANGER, A, urls,
                      module, W)


def world(rug=True, fin=None):
    w, reg = fresh()
    s = Sim(fin=fin).launch()
    if rug:
        s.rug(1500)
    s.install()
    bid = bond(w, reg, s)
    return w, reg, s, bid


def err(code=-32000, msg="boom"):
    return lambda m, p: {"code": code, "message": msg}


class Pending(unittest.TestCase):
    def assertPending(self, w, reg, bid, reason=None):
        r = check(w, reg, bid)
        self.assertEqual(r["result"], "PENDING")
        if reason:
            self.assertEqual(r["reason"], reason)
        b = get(w, reg, bid)
        self.assertEqual(b["status"], "ACTIVE")
        self.assertEqual(b["cursor"], 0)
        self.assertEqual(b["last_result"], "PENDING")
        return r

    def test_rpc_a_down(self):
        w, reg, s, bid = world()
        stub.WEB.down.add(urls(s.chain)[0])
        self.assertPending(w, reg, bid, "RPC_UNREADABLE")

    def test_rpc_b_down(self):
        w, reg, s, bid = world()
        stub.WEB.down.add(urls(s.chain)[1])
        self.assertPending(w, reg, bid, "RPC_UNREADABLE")

    def test_http_429_everywhere(self):
        w, reg, s, bid = world()
        for u in urls(s.chain):
            stub.WEB.rpc_status[u] = 429
        self.assertPending(w, reg, bid)

    def test_http_500(self):
        w, reg, s, bid = world()
        stub.WEB.rpc_status[urls(s.chain)[0]] = 503
        self.assertPending(w, reg, bid)

    def test_json_rpc_error_on_logs(self):
        w, reg, s, bid = world()
        s.rpcs[1].fail = lambda m, p: {"code": -32005, "message": "limit"} if m == "eth_getLogs" else None
        self.assertPending(w, reg, bid)

    def test_json_rpc_error_on_balance(self):
        w, reg, s, bid = world()
        s.states[0].fail = lambda m, p: {"code": 3, "message": "reverted"} if m == "eth_call" else None
        self.assertPending(w, reg, bid)

    def test_wrong_chain_id(self):
        w, reg, s, bid = world()
        s.rpcs[0].chain_id = 1
        self.assertPending(w, reg, bid)

    def test_rpcs_disagree_on_logs(self):
        w, reg, s, bid = world()
        s.rpcs[1].logs = [lg for lg in s.rpcs[1].logs if int(lg["blockNumber"], 16) != 1500]
        self.assertPending(w, reg, bid, "RPC_DISAGREE")

    def test_rpcs_disagree_on_balance(self):
        w, reg, s, bid = world()
        s.rpcs[1].bal[(s.pair, TEAM)] = [(1000, 999 * GEN)]
        self.assertPending(w, reg, bid, "RPC_DISAGREE")

    def test_rpcs_disagree_on_timestamp(self):
        w, reg, s, bid = world()
        s.rpcs[1].ts_override[1500] = s.ts(1500) + 1
        self.assertPending(w, reg, bid, "RPC_DISAGREE")

    def test_removed_log_is_pending(self):
        w, reg, s, bid = world()
        for c in s.rpcs:
            for lg in c.logs:
                lg["removed"] = True
        self.assertPending(w, reg, bid)

    def test_malformed_log_is_pending(self):
        w, reg, s, bid = world()
        for c in s.rpcs:
            for lg in c.logs:
                if int(lg["blockNumber"], 16) == 1500:
                    lg["data"] = "0x12"
        self.assertPending(w, reg, bid)

    def test_garbage_json(self):
        w, reg, s, bid = world()
        stub.WEB.tamper[urls(s.chain)[0]] = lambda req, ans: {"jsonrpc": "2.0", "id": req["id"], "result": "zz"}
        self.assertPending(w, reg, bid)

    def test_missing_finalized_head(self):
        w, reg, s, bid = world()
        stub.WEB.tamper[urls(s.chain)[0]] = lambda req, ans: ({"jsonrpc": "2.0", "id": req["id"], "result": None}
                                                              if req["params"][:1] == ["finalized"] else ans)
        self.assertPending(w, reg, bid)

    def test_pending_then_recovers_same_verdict(self):
        w, reg, s, bid = world()
        stub.WEB.down.add(urls(s.chain)[0])
        self.assertPending(w, reg, bid)
        stub.WEB.down.clear()
        r = check(w, reg, bid)
        self.assertEqual((r["result"], r["rug_block"]), ("RUGGED", 1500))
        b = get(w, reg, bid)
        self.assertEqual((b["n_pending"], b["n_checks"]), (1, 2))

    def test_pending_counts_but_no_claims(self):
        w, reg, s, bid = world()
        stub.WEB.down.add("*")
        self.assertPending(w, reg, bid)
        with self.assertRaises(Reverted):
            w.call(reg, "claim", bid, sender=HOLDERS[0])

    def test_pending_cannot_extend_recovery(self):
        w, reg, s, bid = world(rug=False)
        dl = get(w, reg, bid)["recovery_deadline"]
        stub.WEB.down.add("*")
        for _ in range(5):
            check(w, reg, bid)
            w.advance(60)
        self.assertEqual(get(w, reg, bid)["recovery_deadline"], dl)

    def test_pending_until_recovery_then_unresolved(self):
        w, reg, s, bid = world(rug=False)
        stub.WEB.down.add("*")
        check(w, reg, bid)
        w.set_time(get(w, reg, bid)["recovery_deadline"] + 1)
        r = w.call(reg, "settle", bid, sender=STRANGER)
        self.assertEqual(r["status"], "UNRESOLVED")


class Consensus(unittest.TestCase):
    def test_leader_lies_about_rug_validator_disagrees(self):
        w, reg, s, bid = world(rug=False)

        def lie(r):
            r["facts"]["window"]["probes"] = [[1000, "1"]]
            r["facts"]["window"]["rug"] = {"block": 1000, "ts": 1, "txs": [], "lp_after": "1", "supply": "1",
                                            "lp_before": "1", "excluded": [], "denom": "1"}
            return r
        stub.FORGE["mutate"] = lie
        with self.assertRaises(Reverted) as e:
            check(w, reg, bid)
        self.assertIn("UNDETERMINED", e.exception.msg)
        self.assertEqual(get(w, reg, bid)["n_checks"], 0)

    def test_leader_hides_rug_validator_disagrees(self):
        w, reg, s, bid = world()

        def hide(r):
            r["facts"]["window"]["rug"] = None
            r["facts"]["window"]["probes"] = r["facts"]["window"]["probes"][:1]
            return r
        stub.FORGE["mutate"] = hide
        with self.assertRaises(Reverted):
            check(w, reg, bid)

    def test_leader_claims_unreadable_when_readable(self):
        w, reg, s, bid = world()
        stub.FORGE["mutate"] = lambda r: {"reason": "RPC_UNREADABLE", "detail": "x", "range": r["range"]}
        with self.assertRaises(Reverted):
            check(w, reg, bid)

    # --- C3: a validator derives the range from contract state and never takes the leader's word for a failure

    def _forged_pending_rolls_back(self, payload, **kw):
        w, reg, s, bid = world(**kw)
        stub.FORGE["payload"] = payload
        with self.assertRaises(Reverted) as e:
            check(w, reg, bid)
        self.assertIn("UNDETERMINED", e.exception.msg)
        b = get(w, reg, bid)
        self.assertEqual((b["n_checks"], b["n_pending"], b["cursor"], b["span"]), (0, 0, 0, 40000))
        # the next leader is honest: the check reads and decides
        stub.FORGE["payload"] = None
        self.assertEqual(check(w, reg, bid)["result"], "RUGGED" if kw.get("rug", True) else "HELD")

    def test_leader_pending_with_zero_range_is_refused(self):
        self._forged_pending_rolls_back({"reason": "RPC_UNREADABLE", "detail": "x", "range": [0, 0]})

    def test_leader_pending_with_no_range_is_refused(self):
        self._forged_pending_rolls_back({"reason": "RPC_UNREADABLE", "detail": "x"})

    def test_leader_pending_with_wrong_ranges_is_refused(self):
        for rng in ([1000, 1000], [1, 2], [10 ** 9, 10 ** 9 + 1], [2000, 1000], [0, 10 ** 12], "junk", [0], None, [-1, -1]):
            for reason in ("RPC_UNREADABLE", "RPC_DISAGREE"):
                self._forged_pending_rolls_back({"reason": reason, "detail": "x", "range": rng})

    def test_leader_nothing_new_when_there_is_something_new_is_refused(self):
        for rng in ([0, 0], [21001, 21000], None):
            self._forged_pending_rolls_back({"reason": "NOTHING_NEW", "detail": "x", "range": rng})

    def test_leader_unknown_reason_is_refused(self):
        for reason in ("RANGE_MISMATCH", "", "HELD", 7, None):
            self._forged_pending_rolls_back({"reason": reason, "detail": "x", "range": [0, 0]}, rug=False)

    def test_leader_facts_together_with_a_reason_is_refused(self):
        w, reg, s, bid = world()

        def both(r):
            r["reason"] = "RPC_UNREADABLE"
            return r
        stub.FORGE["mutate"] = both
        with self.assertRaises(Reverted):
            check(w, reg, bid)

    def test_genuine_outage_pending_is_accepted_whatever_range_the_leader_sent(self):
        for rng in ([1000, 21000], [0, 0], None):
            w, reg, s, bid = world()
            stub.WEB.down.add("*")
            stub.FORGE["payload"] = {"reason": "RPC_UNREADABLE", "detail": "x", "range": rng}
            r = check(w, reg, bid)
            self.assertEqual((r["result"], r["reason"]), ("PENDING", "RPC_UNREADABLE"))
            b = get(w, reg, bid)
            self.assertEqual((b["n_pending"], b["cursor"], b["status"]), (1, 0, "ACTIVE"))

    def test_outage_on_the_validators_only_does_not_make_a_real_read_pending(self):
        w, reg, s, bid = world()
        stub.WEB.validator_hook = lambda: stub.WEB.down.add("*")
        with self.assertRaises(Reverted):
            check(w, reg, bid)
        self.assertEqual(get(w, reg, bid)["n_checks"], 0)

    def test_outage_on_the_leader_only_is_not_pending(self):
        w, reg, s, bid = world()
        stub.WEB.down.add("*")
        stub.WEB.validator_hook = lambda: stub.WEB.down.clear()
        with self.assertRaises(Reverted):
            check(w, reg, bid)
        self.assertEqual(get(w, reg, bid)["n_pending"], 0)

    def test_validator_reads_what_the_leader_names_only_inside_its_own_range(self):
        # the range is [cursor + 1, cursor + span] cut at the finalized head: 1000..21000 here
        for b_claimed, ok in ((21000, True), (21001, False), (20999, True), (21000 - 1800, True), (21000 - 1801, False),
                              (1000, False), (999, False), (0, False)):
            w, reg, s, bid = world(rug=False)

            def move(r, b_claimed=b_claimed):
                r["range"][1] = b_claimed
                return r
            stub.FORGE["mutate"] = move
            if ok and b_claimed == 21000:
                self.assertEqual(check(w, reg, bid)["result"], "HELD")
            else:
                # inside the slack the range is acceptable, but the facts the leader sent are for another range
                with self.assertRaises(Reverted):
                    check(w, reg, bid)
                self.assertEqual(get(w, reg, bid)["n_checks"], 0, b_claimed)

    def test_leader_with_a_slightly_older_head_is_accepted(self):
        w, reg = fresh()
        s = Sim(fin=1050).launch().install()
        bid = bond(w, reg, s)

        def hook():
            for c in s.all_mocks():
                c.finalized = 1050 + 1800
        stub.WEB.validator_hook = hook
        r = check(w, reg, bid)
        self.assertEqual((r["result"], r["cursor"]), ("SCANNED", 1050))

    def test_leader_with_a_much_older_head_is_refused(self):
        w, reg = fresh()
        s = Sim(fin=1050).launch().install()
        bid = bond(w, reg, s)

        def hook():
            for c in s.all_mocks():
                c.finalized = 1050 + 1801
        stub.WEB.validator_hook = hook
        with self.assertRaises(Reverted):
            check(w, reg, bid)

    def test_leader_moving_the_first_block_is_refused(self):
        w, reg, s, bid = world(rug=False)

        def move(r):
            r["range"][0] = 1001
            r["facts"]["window"]["a"] = 1001
            return r
        stub.FORGE["mutate"] = move
        with self.assertRaises(Reverted):
            check(w, reg, bid)

    def test_leader_cannot_supply_cursor_span_or_bound(self):
        # extra keys change nothing: the validator's read takes cursor, span and low from storage
        w, reg, s, bid = world(rug=False)

        def extra(r):
            r.update({"cursor": 20000, "span": 1, "low": "0", "first": False})
            return r
        stub.FORGE["mutate"] = extra
        r = check(w, reg, bid)
        self.assertEqual((r["result"], r["cursor"]), ("HELD", 21000))

    def test_leader_forging_the_carried_bound_is_refused(self):
        w, reg = fresh()
        s = Sim(fin=1050).launch().install()
        bid = bond(w, reg, s)

        def forge(r):
            r["facts"]["window"]["low"] = str(10 ** 30)
            return r
        stub.FORGE["mutate"] = forge
        with self.assertRaises(Reverted):
            check(w, reg, bid)

    def test_claim_leader_pending_when_readable_is_refused(self):
        w, reg, s, bid = world()
        check(w, reg, bid)
        stub.FORGE["payload"] = {"reason": "RPC_UNREADABLE", "detail": "x"}
        with self.assertRaises(Reverted) as e:
            w.call(reg, "claim", bid, sender=HOLDERS[0])
        self.assertIn("UNDETERMINED", e.exception.msg)
        stub.FORGE["payload"] = None
        self.assertEqual(w.call(reg, "claim", bid, sender=HOLDERS[0])["share"], str(GEN // 5))

    def test_leader_widens_range_validator_disagrees(self):
        w, reg, s, bid = world(rug=False)

        def widen(r):
            r["range"][1] = r["range"][1] + 10 ** 6
            return r
        stub.FORGE["mutate"] = widen
        with self.assertRaises(Reverted):
            check(w, reg, bid)

    def test_validator_rpc_view_differs(self):
        w, reg, s, bid = world()

        def hook():
            for c in s.rpcs:
                c.bal[(s.pair, TEAM)] = [(1000, 1000 * GEN)]
        stub.WEB.validator_hook = hook
        with self.assertRaises(Reverted):
            check(w, reg, bid)

    def test_both_unreadable_agree_on_pending(self):
        w, reg, s, bid = world()
        stub.WEB.down.add("*")
        self.assertEqual(check(w, reg, bid)["result"], "PENDING")

    def test_validator_lagging_head_disagrees(self):
        w, reg, s, bid = world(rug=False)

        def hook():
            for c in s.rpcs:
                c.finalized = 1010
        stub.WEB.validator_hook = hook
        with self.assertRaises(Reverted):
            check(w, reg, bid)

    def test_claim_validator_disagrees_on_balance(self):
        w, reg, s, bid = world()
        until_verdict(w, reg, bid)

        def hook():
            for c in s.rpcs:
                c.bal[(s.token, HOLDERS[0])] = [(1000, 10 ** 30)]
        stub.WEB.validator_hook = hook
        with self.assertRaises(Reverted):
            w.call(reg, "claim", bid, sender=HOLDERS[0])
        stub.WEB.validator_hook = None
        s.install()
        self.assertEqual(int(w.call(reg, "claim", bid, sender=HOLDERS[0])["share"]), GEN // 5)

    def test_claim_rpc_down_is_pending_refusal(self):
        w, reg, s, bid = world()
        until_verdict(w, reg, bid)
        stub.WEB.down.add(urls(s.chain)[1])
        with self.assertRaises(Reverted) as e:
            w.call(reg, "claim", bid, sender=HOLDERS[0])
        self.assertIn("PENDING", e.exception.msg)
        self.assertEqual(get(w, reg, bid)["n_claims"], 0)

    def test_claim_rpcs_disagree(self):
        w, reg, s, bid = world()
        until_verdict(w, reg, bid)
        s.rpcs[1].bal[(s.token, HOLDERS[0])] = [(1000, 1)]
        with self.assertRaises(Reverted) as e:
            w.call(reg, "claim", bid, sender=HOLDERS[0])
        self.assertIn("RPC_DISAGREE", e.exception.msg)


def _gen():
    methods = ["eth_chainId", "eth_getBlockByNumber", "eth_getLogs", "eth_call"]
    for m in methods:
        for side in (0, 1):
            def t(self, m=m, side=side):
                w, reg, s, bid = world()
                target = s.states[side] if m == "eth_call" else s.rpcs[side]
                target.fail = lambda mm, p, m=m: {"code": -32000, "message": "x"} if mm == m else None
                r = check(w, reg, bid)
                self.assertEqual(r["result"], "PENDING")
                self.assertEqual(get(w, reg, bid)["status"], "ACTIVE")
            setattr(FailureMatrix, "test_%s_fails_on_rpc_%s" % (m, "ab"[side]), t)
    for m in ("eth_chainId", "eth_call", "eth_getCode"):
        for side in (0, 1):
            def t(self, m=m, side=side):
                w, reg, s, bid = world()
                until_verdict(w, reg, bid)
                s.states[side].fail = lambda mm, p, m=m: {"code": -32000, "message": "x"} if mm == m else None
                with self.assertRaises(Reverted):
                    w.call(reg, "claim", bid, sender=HOLDERS[0])
                self.assertEqual(get(w, reg, bid)["paid"], "0")
            setattr(FailureMatrix, "test_claim_%s_fails_on_rpc_%s" % (m, "ab"[side]), t)


class FailureMatrix(unittest.TestCase):
    pass


_gen()

if __name__ == "__main__":
    unittest.main()
