"""Scenario builder for the offline suite.

Sim is one EVM chain built by applying events block by block (LP mints and
transfers, token transfers, code at addresses); install() copies it to BOTH
RPCs of the chain so a test can then break or tamper with one of them.
bond() opens a bond on a registry with sensible frozen terms that any test can
override.
"""
import copy
import hashlib

import stub
from world import module, new_world, Reverted  # noqa: F401

TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
ZERO = "0x" + "0" * 40
DEAD = "0x000000000000000000000000000000000000dead"
GEN = 10 ** 18
NOW = 1791374400                      # 2026-10-07T12:00:00Z, the world's default clock
CHAIN_IDS = {"ethereum": 1, "base": 8453, "base-sepolia": 84532}
BLOCK_TIME = {"ethereum": 12, "base": 2, "base-sepolia": 2}
FACTORY = {"ethereum": "0x5c69bee701ef814a2b6a3edd4b1652cb9cc5aa6f", "base": "0x8909dc15e40173ff4699343b6eb8132c65e18ec6",
           "base-sepolia": "0x7ae58f10f7849ca6f5fb71b7f45cb416c9204b1e"}
AERODROME = "0x420dd381b31aef6683db6b902084cb0ffece40da"


def A(n):
    """A deterministic address."""
    return "0x" + hashlib.sha256(b"addr%d" % n).hexdigest()[:40]


def H(x):
    return "0x" + hashlib.sha256(str(x).encode()).hexdigest()


def W(n):
    return "0x" + "%064x" % (n % (1 << 256))


def T(a):
    return "0x" + "0" * 24 + a[2:]


TEAM, TEAM2, LOCKER, FUND, ROUTER, STRANGER = A(1), A(2), A(3), A(4), A(5), A(6)
HOLDERS = [A(100 + i) for i in range(20)]
BOT = A(90)            # a contract holder
WETH = A(91)


class Sim:
    """One chain. Blocks start at START; the finalized head is FIN (movable)."""

    def __init__(self, chain="base-sepolia", start=1000, fin=None, now=NOW, token=None, pair=None, factory=None):
        self.chain = chain
        self.start = start
        self.token = token or A(50)
        self.pair = pair or A(51)
        self.factory = factory or FACTORY[chain]
        bt = BLOCK_TIME[chain]
        self.fin = fin if fin is not None else start + 20000
        self.c = stub.MockChain(CHAIN_IDS[chain], self.fin, genesis_ts=now - self.fin * bt, block_time=bt)
        self.c.supply[self.token] = [(0, 0)]
        self.c.supply[self.pair] = [(0, 0)]
        self.c.code[self.token] = "0x6001"
        self.c.code[self.pair] = "0x6002"
        self.c.code[BOT] = "0x6003"
        t0, t1 = sorted([self.token, WETH])
        self.c.calls[(self.pair, "0x0dfe1681")] = T(t0)
        self.c.calls[(self.pair, "0xd21220a7")] = T(t1)
        self.c.calls[(self.pair, "0xc45a0155")] = T(self.factory)
        sel = "0x79bc57d5" if self.factory == AERODROME else "0xe6a43905"
        data = sel + "0" * 24 + t0[2:] + "0" * 24 + t1[2:] + ("0" * 64 if self.factory == AERODROME else "")
        self.c.calls[(self.factory, data)] = T(self.pair)
        self.n = 0

    def ts(self, n):
        return self.c.ts(n)

    def block_at(self, ts):
        """The last block whose timestamp is <= ts."""
        return (ts - self.c.genesis_ts) // self.c.block_time

    def _bal(self, token, who):
        h = self.c.bal.get((token, who), [])
        return h[-1][1] if h else 0

    def _set(self, token, who, block, v):
        h = self.c.bal.setdefault((token, who), [])
        if h and h[-1][0] == block:
            h[-1] = (block, v)
        else:
            assert not h or h[-1][0] < block, "events must be applied in block order per account"
            h.append((block, v))

    def transfer(self, token, block, frm, to, amount, log=True):
        if frm == ZERO:
            s = self.c.supply[token]
            v = (s[-1][1] if s else 0) + amount
            if s and s[-1][0] == block:
                s[-1] = (block, v)
            else:
                s.append((block, v))
        else:
            assert self._bal(token, frm) >= amount, "insufficient balance"
            self._set(token, frm, block, self._bal(token, frm) - amount)
        if to == ZERO:
            s = self.c.supply[token]
            s.append((block, s[-1][1] - amount)) if s[-1][0] != block else s.__setitem__(-1, (block, s[-1][1] - amount))
        else:
            self._set(token, to, block, self._bal(token, to) + amount)
        if log:
            self.n += 1
            self.c.logs.append({"address": token, "topics": [TRANSFER, T(frm), T(to)], "data": W(amount),
                                "blockNumber": hex(block), "logIndex": hex(self.n % 500), "transactionHash": H(("tx", self.n)),
                                "removed": False})
            self.c.logs.sort(key=lambda lg: (int(lg["blockNumber"], 16), int(lg["logIndex"], 16)))
        return self

    def lp(self, block, frm, to, amount):
        return self.transfer(self.pair, block, frm, to, amount)

    def tok(self, block, frm, to, amount):
        return self.transfer(self.token, block, frm, to, amount)

    def launch(self, lp=1000 * GEN, supply=1_000_000 * GEN, holders=None, holder_amount=10_000 * GEN, team=TEAM):
        """A standard launch at `start`: the team mints LP, the pair holds most of the
        supply, the team keeps some, and each holder buys `holder_amount`."""
        b = self.start
        self.lp(b, ZERO, ZERO, 1000)                      # MINIMUM_LIQUIDITY to address(0)
        self.lp(b, ZERO, team, lp)
        self.tok(b, ZERO, self.pair, supply // 2)
        self.tok(b, ZERO, team, supply // 2)
        # the pair's tokens back the buys below (its balance is not the pool's reserve here)
        for h in (holders if holders is not None else HOLDERS[:5]):
            self.buy(b, h, holder_amount)            # holders buy from the pair in the start block
        return self

    def buy(self, block, who, amount):
        """A swap: the pair sends tokens to the buyer."""
        return self.tok(block, self.pair, who, amount)

    def rug(self, block, frm=TEAM, amount=None):
        """removeLiquidity: the LP goes to the pair and is burned there."""
        amt = self._bal(self.pair, frm) if amount is None else amount
        self.lp(block, frm, self.pair, amt)
        self.lp(block, self.pair, ZERO, amt)
        return self

    def install(self, fin=None):
        """One mock per endpoint URL: rpcs[0] answers log RPC A, rpcs[1] log RPC B; states[i] answers state RPC i
        (an endpoint that is both a log and a state RPC is one mock, as it is one server)."""
        if fin is not None:
            self.fin = fin
        self.c.finalized = self.fin
        chains = module("RugBond").CHAINS
        by_url = {}
        if self.chain in chains:
            for url in list(chains[self.chain][1]) + list(chains[self.chain][3]):
                if url not in by_url:
                    by_url[url] = copy.deepcopy(self.c)
                    stub.WEB.chains[url] = by_url[url]
            self.rpcs = [by_url[u] for u in chains[self.chain][1]]
            self.states = [by_url[u] for u in chains[self.chain][3]]
        return self

    def all_mocks(self):
        out = []
        for c in self.rpcs + self.states:
            if c not in out:
                out.append(c)
        return out


def urls(chain):
    return module("RugBond").CHAINS[chain][1]


def surls(chain):
    return module("RugBond").CHAINS[chain][3]


def fresh(mode="DEMO", now=NOW):
    stub.WEB.reset()
    stub.TRANSFERS.clear()
    stub.FORGE["payload"] = None
    stub.FORGE["mutate"] = None
    w = new_world()
    w.set_time(now)
    reg = w.deploy("RugBond", mode, FUND)
    return w, reg


def terms(sim, **o):
    t = dict(name="Test token", chain=sim.chain, token=sim.token, pair=sim.pair, lp_holders=[TEAM], min_lp=900 * GEN,
             start_block=sim.start, end_time=sim.ts(sim.start) + 3600, claim_window_s=600,
             excluded=[ROUTER], dust_floor=0)
    t.update(o)
    return t


def create(w, reg, t, value=GEN, sender=TEAM):
    import json
    return w.call(reg, "create_bond", t["name"], t["chain"], t["token"], t["pair"], json.dumps(t["lp_holders"]),
                  t["min_lp"], t["start_block"], t["end_time"], t["claim_window_s"],
                  json.dumps(t["excluded"]), t["dust_floor"], sender=sender, value=value)


def bond(w, reg, sim, value=GEN, sender=TEAM, **o):
    r = create(w, reg, terms(sim, **o), value=value, sender=sender)
    assert r["ok"], r
    return r["bond_id"]


def check(w, reg, bid, sender=STRANGER):
    return w.call(reg, "check", bid, sender=sender)


def until_verdict(w, reg, bid, n=50):
    out = []
    for _ in range(n):
        r = check(w, reg, bid)
        out.append(r)
        if r["result"] != "SCANNED":
            return out
    return out


def close(w, reg, bid, sender=STRANGER):
    """Everything after the claim window: one settle. -> its result."""
    return w.call(reg, "settle", bid, sender=sender)


def get(w, reg, bid):
    return w.view(reg, "get_bond", bid, w.now())
