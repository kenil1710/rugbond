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
        s.rpcs[0].fail = lambda m, p: {"code": 3, "message": "reverted"} if m == "eth_call" else None
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
                s.rpcs[side].fail = lambda mm, p, m=m: {"code": -32000, "message": "x"} if mm == m else None
                r = check(w, reg, bid)
                self.assertEqual(r["result"], "PENDING")
                self.assertEqual(get(w, reg, bid)["status"], "ACTIVE")
            setattr(FailureMatrix, "test_%s_fails_on_rpc_%s" % (m, "ab"[side]), t)
    for m in ("eth_chainId", "eth_call", "eth_getCode"):
        for side in (0, 1):
            def t(self, m=m, side=side):
                w, reg, s, bid = world()
                until_verdict(w, reg, bid)
                s.rpcs[side].fail = lambda mm, p, m=m: {"code": -32000, "message": "x"} if mm == m else None
                with self.assertRaises(Reverted):
                    w.call(reg, "claim", bid, sender=HOLDERS[0])
                self.assertEqual(get(w, reg, bid)["paid"], "0")
            setattr(FailureMatrix, "test_claim_%s_fails_on_rpc_%s" % (m, "ab"[side]), t)


class FailureMatrix(unittest.TestCase):
    pass


_gen()

if __name__ == "__main__":
    unittest.main()
