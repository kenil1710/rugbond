"""LaunchGate: bond-bound answers, copycats, never favorable on missing, pending or stale data."""
import unittest

import stub
from fixtures import (Sim, fresh, bond, check, until_verdict, get, Reverted, TEAM, TEAM2, HOLDERS, GEN, STRANGER,
                      NOW, A, urls, module)

LG_MAX = module("LaunchGate").MAX_TEAM_BONDS


def setup(rug=None, fin=None, sender=TEAM, **o):
    w, reg = fresh()
    gate = w.deploy("LaunchGate", reg)
    s = Sim(start=1000, fin=fin if fin is not None else 1100).launch()
    if rug:
        s.rug(rug)
    s.install()
    bid = bond(w, reg, s, sender=sender, end_time=s.ts(1000) + 3600, **o)
    return w, reg, gate, s, bid


def cf(w, gate, token, bid):
    return w.view(gate, "check_for", token, bid)


class CheckFor(unittest.TestCase):
    def test_no_read_yet_pending(self):
        w, reg, gate, s, bid = setup()
        r = cf(w, gate, s.token, bid)
        self.assertEqual((r["state"], r["safe"]), ("PENDING", False))

    def test_active_fresh_read_safe(self):
        w, reg, gate, s, bid = setup()
        check(w, reg, bid)
        r = cf(w, gate, s.token, bid)
        self.assertEqual((r["state"], r["safe"]), ("ACTIVE_HELD_SO_FAR", True))

    def test_stale_read_pending(self):
        w, reg, gate, s, bid = setup()
        check(w, reg, bid)
        w.advance(6 * 3600 + 3601)
        r = cf(w, gate, s.token, bid)
        self.assertEqual(r["state"], "PENDING")
        self.assertIn("stale", r["why"])

    def test_stale_boundary(self):
        w, reg, gate, s, bid = setup()
        check(w, reg, bid)
        cts = get(w, reg, bid)["cursor_ts"]
        w.set_time(cts + 6 * 3600)
        self.assertEqual(cf(w, gate, s.token, bid)["state"], "ACTIVE_HELD_SO_FAR")
        w.set_time(cts + 6 * 3600 + 1)
        self.assertEqual(cf(w, gate, s.token, bid)["state"], "PENDING")

    def test_last_check_pending_is_pending(self):
        w, reg, gate, s, bid = setup()
        check(w, reg, bid)
        s.install(fin=1200)
        stub.WEB.down.add("*")
        check(w, reg, bid)
        self.assertEqual(cf(w, gate, s.token, bid)["state"], "PENDING")

    def test_no_clock_is_pending(self):
        w, reg, gate, s, bid = setup()
        check(w, reg, bid)
        w.now_iso = ""
        stub.MESSAGE.raw = {}
        import world
        orig = world.World._msg

        def msg(self, sender, value, address):
            orig(self, sender, value, address)
            world.gl.message.raw = {}
        world.World._msg = msg
        try:
            self.assertEqual(cf(w, gate, s.token, bid)["state"], "PENDING")
        finally:
            world.World._msg = orig

    def test_held_final(self):
        w, reg = fresh()
        gate = w.deploy("LaunchGate", reg)
        s = Sim(fin=2700).launch().install()
        bid = bond(w, reg, s, end_time=s.ts(1000) + 1000)
        until_verdict(w, reg, bid)
        self.assertEqual(cf(w, gate, s.token, bid)["state"], "HELD_FINAL")
        w.call(reg, "settle", bid, sender=STRANGER)
        r = cf(w, gate, s.token, bid)
        self.assertEqual((r["state"], r["safe"]), ("HELD_FINAL", False))

    def test_rugged_paying_then_closed(self):
        w, reg, gate, s, bid = setup(rug=1050, fin=5000)
        until_verdict(w, reg, bid)
        self.assertEqual(cf(w, gate, s.token, bid)["state"], "RUGGED_PAYING")
        w.advance(601)
        self.assertEqual(cf(w, gate, s.token, bid)["state"], "RUGGED_CLOSED")
        w.call(reg, "settle", bid, sender=STRANGER)
        self.assertEqual(cf(w, gate, s.token, bid)["state"], "RUGGED_CLOSED")

    def test_unresolved_is_pending(self):
        w, reg, gate, s, bid = setup()
        w.set_time(get(w, reg, bid)["recovery_deadline"] + 1)
        w.call(reg, "settle", bid, sender=STRANGER)
        self.assertEqual(cf(w, gate, s.token, bid)["state"], "PENDING")

    def test_void_is_no_bond(self):
        w, reg = fresh()
        gate = w.deploy("LaunchGate", reg)
        s = Sim(fin=1100).launch()
        s.c.calls[(s.pair, "0xc45a0155")] = "0x" + "0" * 24 + A(77)[2:]
        s.install()
        bid = bond(w, reg, s, end_time=s.ts(1000) + 3600)
        check(w, reg, bid)
        self.assertEqual(cf(w, gate, s.token, bid)["state"], "NO_BOND")

    def test_rugged_replay_still_reported(self):
        w, reg, gate, s, bid = setup(rug=1050, fin=21000)
        until_verdict(w, reg, bid)
        self.assertTrue(get(w, reg, bid)["replay"])
        self.assertEqual(cf(w, gate, s.token, bid)["state"], "RUGGED_PAYING")

    def test_replay_is_no_bond(self):
        w, reg, gate, s, bid = setup(fin=21000)
        until_verdict(w, reg, bid)
        r = cf(w, gate, s.token, bid)
        self.assertEqual(r["state"], "NO_BOND")
        self.assertIn("replay", r["why"])

    def test_missing_bond(self):
        w, reg, gate, s, bid = setup()
        self.assertEqual(cf(w, gate, s.token, 99)["state"], "NO_BOND")
        self.assertEqual(cf(w, gate, s.token, 0)["state"], "NO_BOND")

    def test_wrong_token_no_bond(self):
        w, reg, gate, s, bid = setup()
        check(w, reg, bid)
        r = cf(w, gate, A(999), bid)
        self.assertEqual((r["state"], r["safe"]), ("NO_BOND", False))

    def test_bad_token_input(self):
        w, reg, gate, s, bid = setup()
        self.assertEqual(cf(w, gate, "nope", bid)["state"], "NO_BOND")

    def test_registry_unreadable(self):
        w, reg = fresh()
        gate = w.deploy("LaunchGate", A(12345))
        r = cf(w, gate, A(1), 1)
        self.assertEqual((r["state"], r["safe"]), ("PENDING", False))


class TeamBound(unittest.TestCase):
    def test_is_safe_for_team(self):
        w, reg, gate, s, bid = setup()
        check(w, reg, bid)
        r = w.view(gate, "is_safe_for", s.token, TEAM)
        self.assertEqual((r["state"], r["safe"]), ("ACTIVE_HELD_SO_FAR", True))

    def test_copycat_bond_by_other_team_not_read(self):
        w, reg, gate, s, bid = setup()
        b2 = bond(w, reg, s, sender=TEAM2, end_time=s.ts(1000) + 3600)
        check(w, reg, b2)
        r = w.view(gate, "is_safe_for", s.token, TEAM)
        self.assertEqual((r["state"], r["safe"]), ("PENDING", False))
        r2 = w.view(gate, "is_safe_for", s.token, TEAM2)
        self.assertTrue(r2["safe"])

    def test_copycat_cannot_help_real_team(self):
        w, reg = fresh()
        gate = w.deploy("LaunchGate", reg)
        s = Sim(fin=1100).launch().install()
        b2 = bond(w, reg, s, sender=TEAM2, end_time=s.ts(1000) + 3600)
        check(w, reg, b2)
        r = w.view(gate, "is_safe_for", s.token, TEAM)
        self.assertEqual(r["state"], "NO_BOND")

    def test_copycat_look_alike_token(self):
        w, reg, gate, s, bid = setup()
        fake = Sim(token=A(888), pair=A(889), fin=1100).launch().install()
        b2 = bond(w, reg, fake, end_time=fake.ts(1000) + 3600)
        check(w, reg, b2)
        self.assertEqual(cf(w, gate, s.token, b2)["state"], "NO_BOND")

    def test_worst_state_wins(self):
        w, reg = fresh()
        gate = w.deploy("LaunchGate", reg)
        s = Sim(fin=5000).launch()
        s.rug(1050)
        s.install()
        b1 = bond(w, reg, s, end_time=s.ts(1000) + 3600)
        until_verdict(w, reg, b1)
        s2 = Sim(start=4000, fin=5000, token=s.token, pair=A(52)).launch().install()
        b2 = bond(w, reg, s2, end_time=s2.ts(4000) + 3600)
        r = w.view(gate, "is_safe_for", s.token, TEAM)
        self.assertEqual(r["state"], "RUGGED_PAYING")
        self.assertFalse(r["safe"])

    def test_no_bonds_no_bond(self):
        w, reg = fresh()
        gate = w.deploy("LaunchGate", reg)
        r = w.view(gate, "is_safe_for", A(1), TEAM)
        self.assertEqual((r["state"], r["safe"]), ("NO_BOND", False))

    def test_team_with_more_bonds_than_the_gate_reads_is_pending(self):
        w, reg = fresh()
        gate = w.deploy("LaunchGate", reg)
        other = Sim(token=A(700), pair=A(701))
        for i in range(LG_MAX):
            bond(w, reg, other, value=10 ** 15)
        s = Sim(fin=1100).launch().install()
        bid = bond(w, reg, s, end_time=s.ts(1000) + 3600)
        check(w, reg, bid)
        r = w.view(gate, "is_safe_for", s.token, TEAM)
        self.assertEqual((r["state"], r["safe"]), ("PENDING", False))

    def test_team_pagination_over_50(self):
        w, reg = fresh()
        gate = w.deploy("LaunchGate", reg)
        other = Sim(token=A(700), pair=A(701))
        for i in range(55):
            bond(w, reg, other, value=10 ** 15)
        s = Sim(fin=1100).launch().install()
        bid = bond(w, reg, s, end_time=s.ts(1000) + 3600)
        check(w, reg, bid)
        r = w.view(gate, "is_safe_for", s.token, TEAM)
        self.assertTrue(r["safe"])


class Attest(unittest.TestCase):
    def test_attest_stores(self):
        w, reg, gate, s, bid = setup()
        check(w, reg, bid)
        r = w.call(gate, "attest", s.token, bid, sender=STRANGER)
        self.assertEqual(r["state"], "ACTIVE_HELD_SO_FAR")
        pg = w.view(gate, "get_attestations", 0, 10)
        self.assertEqual(pg["items"][0]["bond_id"], bid)

    def test_attest_team(self):
        w, reg, gate, s, bid = setup()
        r = w.call(gate, "attest_team", s.token, TEAM, sender=STRANGER)
        self.assertEqual(r["state"], "PENDING")


class PureGate(unittest.TestCase):
    """gate_state on hand-made registry answers: every malformed one is PENDING/NO_BOND, never safe."""

    def base(self, **o):
        v = {"found": True, "bond_id": 1, "status": "ACTIVE", "token": A(1), "team": A(2), "cursor_ts": NOW,
             "n_checks": 1, "claim_deadline": 0, "replay": False, "last_result": "SCANNED", "chain": "base",
             "amount": "1", "rug_block": 0}
        v.update(o)
        return v

    def gs(self, v, now=NOW):
        return module("LaunchGate").gate_state(v, A(1), now, 3600)


def _gen():
    bad = [("bond_id", 0), ("bond_id", "x"), ("status", None), ("token", "bad"), ("team", ""), ("cursor_ts", -1),
           ("n_checks", True), ("claim_deadline", "z"), ("replay", "no"), ("last_result", 5)]
    for k, v in bad:
        def t(self, k=k, v=v):
            r = self.gs(self.base(**{k: v}))
            self.assertFalse(r["safe"])
            self.assertIn(r["state"], ("PENDING", "NO_BOND"))
        setattr(PureGate, "test_malformed_%s_%s" % (k, str(v).replace("-", "m")), t)
    for st, want in (("ACTIVE", "ACTIVE_HELD_SO_FAR"), ("HELD", "HELD_FINAL"), ("RETURNED", "HELD_FINAL"),
                     ("RUGGED", "RUGGED_PAYING"), ("CLOSED", "RUGGED_CLOSED"), ("REDISTRIBUTING", "PENDING"), ("VOID", "NO_BOND"),
                     ("UNRESOLVED", "PENDING"), ("WEIRD", "PENDING")):
        def t(self, st=st, want=want):
            r = self.gs(self.base(status=st, claim_deadline=NOW + 10))
            self.assertEqual(r["state"], want)
            self.assertEqual(r["safe"], want == "ACTIVE_HELD_SO_FAR")
        setattr(PureGate, "test_status_%s" % st.lower(), t)
    for raw in (None, "not json", 5, [], {"found": False}, {"found": "yes"}):
        def t(self, raw=raw):
            r = self.gs(raw)
            self.assertFalse(r["safe"])
        setattr(PureGate, "test_raw_%s" % type(raw).__name__ + str(abs(hash(str(raw))) % 1000), t)
    for age, want in ((0, True), (3600, True), (3601, False), (10 ** 6, False)):
        def t(self, age=age, want=want):
            self.assertEqual(self.gs(self.base(cursor_ts=NOW - age))["safe"], want)
        setattr(PureGate, "test_age_%d" % age, t)


_gen()

if __name__ == "__main__":
    unittest.main()
