"""Direct Mode (genlayer-test) helpers: a mock Base Sepolia answering the
contract's JSON-RPC batches by their body, wired into the official VM through
its web handler, and one launch-then-rug history."""
import hashlib
import json
import sys

import pytest

RPC_A = "https://base-sepolia.gateway.tenderly.co"
RPC_B = "https://base-sepolia-rpc.publicnode.com"
TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
FACTORY = "0x7ae58f10f7849ca6f5fb71b7f45cb416c9204b1e"
GEN = 10 ** 18
START = 1000
NOW_TS = 1_791_000_000
# genlayer-test's Direct Mode (latest release, 0.29.2) runs contracts on the genvm v0.2 SDK; the contract is written for
# Studio's v0.6 runner (GenVM manager v0.6, SDK spellings below) and pins it by a hash no published test release
# carries. So Direct Mode runs the deployed bytes (build/RugBond.py) with only these spellings changed in a temporary
# copy (ADAPT); every rule, read and check is the deployed code:
ADAPT = [
    ('"Depends": "py-genlayer:', None),
    ("@gl.storage.allow\n", "@gl.storage.allow_storage\n"),
    ("gl.contract.Contract", "gl.Contract"),
    ("gl.message.raw", "gl.message_raw"),
    ('gl.evm.Account(Address(who)).emit_call(u256(amount), b"")',
     "gl.get_contract_at(Address(who)).emit_transfer(value=u256(amount))"),
]
SDK_VERSION = "v0.2.16"


def addr(n):
    return "0x" + hashlib.sha256(b"d%d" % n).hexdigest()[:40]


TEAM, TOKEN, PAIR, WETH, VICTIM_FUND, ROUTER = (addr(i) for i in range(1, 7))
HOLDERS = [addr(100 + i) for i in range(4)]
W = lambda n: "0x" + "%064x" % n
T = lambda a: "0x" + "0" * 24 + a[2:]


class Chain:
    """Base Sepolia as one RPC sees it: LP and token balances by block, LP Transfer logs, timestamps."""

    def __init__(self, fin=START + 3000):
        self.fin = fin
        self.status = 200
        self.bal = {}
        self.supply = {TOKEN: [(0, 1_000_000 * GEN)], PAIR: [(0, 1000 * GEN)]}
        self.logs = []
        self.code = {}
        self.n = 0
        self.set(PAIR, TEAM, START, 1000 * GEN)
        self.set(TOKEN, PAIR, START, 500_000 * GEN)
        self.set(TOKEN, TEAM, START, 460_000 * GEN)
        for h in HOLDERS:
            self.set(TOKEN, h, START + 1, 10_000 * GEN)
        t0, t1 = sorted([TOKEN, WETH])
        self.calls = {(PAIR, "0x0dfe1681"): T(t0), (PAIR, "0xd21220a7"): T(t1), (PAIR, "0xc45a0155"): T(FACTORY),
                      (FACTORY, "0xe6a43905" + "0" * 24 + t0[2:] + "0" * 24 + t1[2:]): T(PAIR)}

    def set(self, tok, who, blk, v):
        self.bal.setdefault((tok, who), []).append((blk, v))

    def at(self, hist, n):
        v = 0
        for b, x in hist:
            if b <= n:
                v = x
        return v

    def rug(self, blk):
        self.set(PAIR, TEAM, blk, 0)
        self.n += 1
        self.logs.append({"address": PAIR, "topics": [TRANSFER, T(TEAM), T(PAIR)], "data": W(1000 * GEN),
                          "blockNumber": hex(blk), "logIndex": hex(self.n), "removed": False,
                          "transactionHash": "0x" + hashlib.sha256(b"rug%d" % blk).hexdigest()})

    def ts(self, n):
        return NOW_TS - (self.fin - n) * 2

    def answer(self, req):
        m, p, i = req["method"], req["params"], req["id"]
        r = None
        if m == "eth_chainId":
            r = hex(84532)
        elif m == "eth_getBlockByNumber":
            n = self.fin if p[0] == "finalized" else int(p[0], 16)
            r = {"number": hex(n), "timestamp": hex(self.ts(n))}
        elif m == "eth_getCode":
            r = self.code.get(p[0], "0x")
        elif m == "eth_getLogs":
            f = p[0]
            lo, hi = int(f["fromBlock"], 16), int(f["toBlock"], 16)
            want = f["topics"][1]
            r = [l for l in self.logs if lo <= int(l["blockNumber"], 16) <= hi and l["address"] == f["address"]
                 and l["topics"][1] in want]
        elif m == "eth_call":
            to, data = p[0]["to"], p[0]["data"]
            n = self.fin if p[1] == "latest" else int(p[1], 16)
            if data.startswith("0x70a08231"):
                r = W(self.at(self.bal.get((to, "0x" + data[-40:]), []), n))
            elif data == "0x18160ddd":
                r = W(self.at(self.supply[to], n))
            else:
                r = self.calls.get((to, data))
                if r is None:
                    return {"jsonrpc": "2.0", "id": i, "error": {"code": 3, "message": "execution reverted"}}
        return {"jsonrpc": "2.0", "id": i, "result": r}


class Net:
    """Both RPC URLs; each can be its own chain, down, or failing."""

    def __init__(self):
        self.a = Chain()
        self.b = self.a
        self.down = set()

    def handler(self, data):
        url = data.get("url", "")
        if url in self.down:
            return {"ok": {"response": {"status": 503, "headers": {}, "body": b"down"}}}
        ch = self.a if url == RPC_A else self.b if url == RPC_B else None
        if ch is None:
            return {"ok": {"response": {"status": 404, "headers": {}, "body": b""}}}
        body = data.get("body")
        req = json.loads(body.decode() if isinstance(body, (bytes, bytearray)) else body)
        out = [ch.answer(r) for r in req] if isinstance(req, list) else ch.answer(req)
        return {"ok": {"response": {"status": ch.status, "headers": {}, "body": json.dumps(out).encode()}}}


def warp(vm, iso):
    """vm.warp, and the v0.2 SDK's message_raw (which the contract's clock reads) moved with it."""
    vm.warp(iso)
    gl = sys.modules.get("genlayer.gl")
    if gl is not None and isinstance(getattr(gl, "message_raw", None), dict):
        gl.message_raw["datetime"] = iso


def fund_contract(vm, amount):
    key = vm._contract_address
    vm._balances[key] = vm._balances.get(key, 0) + amount


@pytest.fixture
def net(direct_vm):
    n = Net()
    direct_vm._live_web_handler = n.handler
    return n


NOW_ISO = "2026-10-03T04:00:00Z"     # NOW_TS


@pytest.fixture
def contract(direct_vm, direct_deploy, direct_owner, tmp_path):
    text = open("build/RugBond.py").read()
    lines = text.split("\n")
    assert lines[0] == "# v0.3.0" and ADAPT[0][0] in lines[1]
    lines[1] = '# { "Depends": "py-genlayer:latest" }'
    text = "\n".join(lines)
    for old, new in ADAPT[1:]:
        assert old in text, old
        text = text.replace(old, new)
    path = tmp_path / "RugBond.py"
    path.write_text(text)
    direct_vm.sender = direct_owner
    direct_vm.warp(NOW_ISO)
    c = direct_deploy(str(path), "DEMO", sdk_version=SDK_VERSION)
    warp(direct_vm, NOW_ISO)
    return c


@pytest.fixture
def bond(direct_vm, contract, direct_alice, net):
    direct_vm.sender = direct_alice
    direct_vm.value = GEN
    r = contract.create_bond("direct", "base-sepolia", TOKEN, PAIR, json.dumps([TEAM]), 900 * GEN, START,
                             net.a.ts(START) + 3600, 600, VICTIM_FUND, json.dumps([ROUTER]), 0)
    direct_vm.value = 0
    assert r["ok"] is True, r
    fund_contract(direct_vm, GEN)
    return r["bond_id"]
