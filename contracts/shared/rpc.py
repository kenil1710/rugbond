# ==== shared rpc reads: contracts/shared/rpc.py, inlined by tools/build.py; edit there ====

# Pools count only if the pair's factory() is listed here AND that factory maps
# the pair's two tokens back to the pair (getPair, or getPool(a, b, false) for
# Aerodrome volatile pools). A look-alike LP token whose balanceOf says
# whatever its deployer wants fails the second check.
FACTORIES = {
    "ethereum": {"0x5c69bee701ef814a2b6a3edd4b1652cb9cc5aa6f": "getPair",       # Uniswap V2
                 "0xc0aee478e3658e2610c5f7a4a2e1777ce9e4f2ac": "getPair"},      # SushiSwap
    "base-sepolia": {"0x7ae58f10f7849ca6f5fb71b7f45cb416c9204b1e": "getPair"},  # Uniswap V2 (official testnet)
}


class ReadFailed(Exception):
    """An endpoint did not answer, or answered something that is not a
    JSON-RPC result. Nothing is guessed."""


def _status(res: typing.Any) -> int:
    s = getattr(res, "status_code", None)
    if s is None:
        s = getattr(res, "status", None)
    return 0 if s is None else int(s)


def _raw(res: typing.Any) -> bytes:
    b = getattr(res, "body", None)
    if b is None:
        return b""
    if isinstance(b, bytes):
        return b
    return str(b).encode("utf-8")


def rpc_url_allowed(url: str) -> bool:
    for ch in CHAINS:
        if url in CHAINS[ch][1]:
            return True
    return False


def parse_batch(doc: typing.Any, n: int) -> list:
    """A JSON-RPC batch answer -> results in call order. Any error raises."""
    if isinstance(doc, dict):
        doc = [doc]
    if not isinstance(doc, list):
        raise ReadFailed("batch")
    by_id = {}
    for item in doc:
        if isinstance(item, dict) and isinstance(item.get("id"), int) and not isinstance(item.get("id"), bool):
            by_id[item["id"]] = item
    out = []
    for i in range(n):
        item = by_id.get(i)
        if item is None:
            raise ReadFailed("missing id")
        if "error" in item and item["error"] is not None:
            raise ReadFailed("rpc error")
        if "result" not in item:
            raise ReadFailed("no result")
        out.append(item["result"])
    return out


def rpc_send(url: str, calls: list, per: int) -> list:
    """One endpoint, every call, in JSON-RPC batches of `per` calls. A batch is
    retried (up to RPC_TRIES) on a transport failure, a 429 or 5xx, or an
    answer that is not a usable batch."""
    if not rpc_url_allowed(url):
        raise ReadFailed("rpc not allowed")
    out = []
    i = 0
    while i < len(calls):
        chunk = calls[i:i + per]
        body = json.dumps([{"jsonrpc": "2.0", "id": j, "method": chunk[j][0], "params": chunk[j][1]}
                           for j in range(len(chunk))])
        got = None
        why = ""
        for _ in range(RPC_TRIES):
            try:
                res = gl.nondet.web.request(url, method="POST", body=body,
                                            headers={"Content-Type": "application/json"})
            except Exception:
                why = "transport"
                continue
            st = _status(res)
            if st != 200:
                why = "http " + str(st)
                if st != 429 and st < 500:
                    break
                continue
            try:
                got = parse_batch(json.loads(_raw(res).decode("utf-8", errors="replace")), len(chunk))
                break
            except ReadFailed as e:
                why = str(e)
            except Exception:
                why = "json"
        if got is None:
            raise ReadFailed(_host(url) + " " + why)
        out = out + got
        i += per
    return out


def _host(url: str) -> str:
    rest = url[url.find("//") + 2:] if url.find("//") >= 0 else url
    cut = rest.find("/")
    return rest if cut < 0 else rest[:cut]


def _bal_call(token: str, who: str, blk: int) -> list:
    return ["eth_call", [{"to": token, "data": "0x70a08231" + "0" * 24 + who[2:]}, hex(blk)]]


def _uint(v: typing.Any) -> int:
    n = _word_uint(v)
    if n < 0:
        raise ReadFailed("not a uint")
    return n


def read_head(url: str, chain: str) -> int:
    """The finalized block number on one endpoint (its chain id checked)."""
    ch = CHAINS[chain]
    a = rpc_send(url, [["eth_chainId", []], ["eth_getBlockByNumber", ["finalized", False]]], RPC_LIMITS[url][1])
    if _hex_int(a[0]) != ch[0]:
        raise ReadFailed("wrong chain id")
    fin = _hex_int(a[1].get("number")) if isinstance(a[1], dict) else -1
    if fin < 0:
        raise ReadFailed("no finalized head")
    return fin


def _ts(h: typing.Any, n: int) -> int:
    if not isinstance(h, dict) or _hex_int(h.get("number")) != n:
        raise ReadFailed("header")
    t = _hex_int(h.get("timestamp"))
    if t <= 0:
        raise ReadFailed("timestamp")
    return t


def read_pair(url: str, chain: str, t: dict) -> dict:
    """Is the bond's pair a genuine V2-style pool of the bond's token? token0,
    token1, factory() of the pair, then the factory's own mapping back."""
    per = RPC_LIMITS[url][1]
    p = t["pair"]
    a = rpc_send(url, [["eth_call", [{"to": p, "data": "0x0dfe1681"}, "latest"]],
                       ["eth_call", [{"to": p, "data": "0xd21220a7"}, "latest"]],
                       ["eth_call", [{"to": p, "data": "0xc45a0155"}, "latest"]]], per)
    t0 = _word_addr(a[0])
    t1 = _word_addr(a[1])
    fac = _word_addr(a[2])
    out = {"token0": t0, "token1": t1, "factory": fac, "ok": False, "why": ""}
    if t0 == "" or t1 == "" or fac == "":
        out["why"] = "NOT_A_PAIR"
        return out
    if t["token"] != t0 and t["token"] != t1:
        out["why"] = "TOKEN_NOT_IN_PAIR"
        return out
    how = FACTORIES.get(chain, {}).get(fac, "")
    if how == "":
        out["why"] = "UNKNOWN_FACTORY"
        return out
    data = ("0xe6a43905" if how == "getPair" else "0x79bc57d5") + "0" * 24 + t0[2:] + "0" * 24 + t1[2:]
    if how == "getPool":
        data = data + "0" * 64          # stable = false: volatile pools only
    b = rpc_send(url, [["eth_call", [{"to": fac, "data": data}, "latest"]]], per)
    if _word_addr(b[0]) != p:
        out["why"] = "FACTORY_DOES_NOT_KNOW_PAIR"
        return out
    out["ok"] = True
    return out


def read_window(url: str, chain: str, t: dict, a: int, b: int) -> dict:
    """Blocks [a, b] of one bond from ONE endpoint (both are read; the caller
    compares). -> {a, b, logs, probes, rug, end_ts, pair}
      logs    every LP Transfer out of an LP holder in [a, b] (eth_getLogs on
              the pair, topic1 = any holder, one call per log window):
              [block, log index, tx, from, to, amount]
      probes  [block, summed LP balance of the holders at the end of that block]
              for the start block (first check) and each block with such a
              transfer, in order, up to MAX_PROBES, stopping at the first below
              min_lp. More blocks than that: b is cut before the first unread one.
      rug     that first block below min_lp: its timestamp, the transfers in it,
              and the token snapshot at R-1 (totalSupply and every excluded
              address's balance), or None
      end_ts  the timestamp of b (of R when there is a rug)
      start_ts the start block's timestamp on the first check (else 0)
    Any transport or JSON-RPC failure raises ReadFailed."""
    span = RPC_LIMITS[url][0]
    per = RPC_LIMITS[url][1]
    pair = t["pair"]
    holders = t["lp_holders"]
    start = int(t["start_block"])
    floor = int(t["min_lp"])
    topics = [TRANSFER, [_pad(h) for h in holders]]
    calls = []
    w = a
    while w <= b:
        z = w + span - 1
        if z > b:
            z = b
        calls.append(["eth_getLogs", [{"address": pair, "topics": topics, "fromBlock": hex(w), "toBlock": hex(z)}]])
        w = z + 1
    got = rpc_send(url, calls, 1)          # one eth_getLogs per request: both gateways meter batched log queries
    logs = []
    for part in got:
        if not isinstance(part, list):
            raise ReadFailed("logs")
        for lg in part:
            if not isinstance(lg, dict) or lg.get("removed") is True:
                raise ReadFailed("log")
            tp = lg.get("topics", [])
            if _addr(lg.get("address", "")) != pair or not isinstance(tp, list) or len(tp) != 3 \
                    or str(tp[0]).lower() != TRANSFER:
                continue
            frm = _word_addr(tp[1])
            to = _word_addr(tp[2])
            amt = _word_uint(lg.get("data", ""))
            blk = _hex_int(lg.get("blockNumber"))
            li = _hex_int(lg.get("logIndex"))
            txh = _hash32(lg.get("transactionHash", ""))
            if frm not in holders or to == "" or amt < 0 or blk < a or blk > b or li < 0 or txh == "":
                raise ReadFailed("log fields")
            logs.append([blk, li, txh, frm, to, str(amt)])
    logs = sorted(logs, key=lambda x: x[0] * 1000000 + x[1])
    pb = []
    if a == start:
        pb.append(start)
    for lg in logs:
        if lg[0] not in pb:
            pb.append(lg[0])
    if len(pb) > MAX_PROBES:
        b = pb[MAX_PROBES] - 1
        pb = pb[0:MAX_PROBES]
        keep = []
        for lg in logs:
            if lg[0] <= b:
                keep.append(lg)
        logs = keep
    probes = []
    rug_at = -1
    if len(pb) > 0:
        sc = []
        for blk in pb:
            for h in holders:
                sc.append(_bal_call(pair, h, blk))
        vals = rpc_send(url, sc, per)
        k = 0
        for blk in pb:
            s = 0
            for h in holders:
                s += _uint(vals[k])
                k += 1
            probes.append([blk, str(s)])
            if s < floor:
                rug_at = blk
                break
    out = {"a": a, "b": b, "logs": logs, "probes": probes, "rug": None, "end_ts": 0, "start_ts": 0}
    if a == start:
        hs = rpc_send(url, [["eth_getBlockByNumber", [hex(start), False]]], per)
        out["start_ts"] = _ts(hs[0], start)
    if rug_at < 0:
        hb = rpc_send(url, [["eth_getBlockByNumber", [hex(b), False]]], per)
        out["end_ts"] = _ts(hb[0], b)
        return out
    out["b"] = rug_at
    keep = []
    for lg in logs:
        if lg[0] <= rug_at:
            keep.append(lg)
    out["logs"] = keep
    hr = rpc_send(url, [["eth_getBlockByNumber", [hex(rug_at), False]]], per)
    ts = _ts(hr[0], rug_at)
    out["end_ts"] = ts
    txs = []
    for lg in keep:
        if lg[0] == rug_at and lg[2] not in txs:
            txs.append(lg[2])
    rug = {"block": rug_at, "ts": ts, "txs": sorted(txs), "lp_after": probes[len(probes) - 1][1]}
    if ts <= int(t["end_time"]):
        sc = [["eth_call", [{"to": t["token"], "data": "0x18160ddd"}, hex(rug_at - 1)]]]
        for h in holders:
            sc.append(_bal_call(pair, h, rug_at - 1))
        for e in t["excluded_all"]:
            sc.append(_bal_call(t["token"], e, rug_at - 1))
        vals = rpc_send(url, sc, per)
        supply = _uint(vals[0])
        lpb = 0
        for i in range(len(holders)):
            lpb += _uint(vals[1 + i])
        ex = []
        for i in range(len(t["excluded_all"])):
            ex.append([t["excluded_all"][i], str(_uint(vals[1 + len(holders) + i]))])
        rug["supply"] = str(supply)
        rug["lp_before"] = str(lpb)
        rug["excluded"] = ex
        rug["denom"] = str(snapshot_denominator(supply, ex))
    out["rug"] = rug
    return out


def read_check(chain: str, t: dict, cursor: int, first: bool, b_fixed: int) -> dict:
    """One rug check read from BOTH RPCs of the chain ->
    {"facts": ...} when they agree, else {"reason": ..., "detail": ...}
    (RPC_UNREADABLE, RPC_DISAGREE, NOTHING_NEW). b_fixed < 0: the leader picks b
    (cut at the lower of the two finalized heads); else a validator re-reads the
    leader's range and needs b at or below both its finalized heads."""
    views = []
    try:
        heads = []
        for url in CHAINS[chain][1]:
            heads.append(read_head(url, chain))
        fin = heads[0] if heads[0] < heads[1] else heads[1]
        rng = scan_range(t, cursor, fin)
        if b_fixed >= 0:
            top = rng[0] + CHAINS[chain][2] - 1
            if b_fixed > fin or b_fixed > top:
                return {"reason": "RPC_DISAGREE", "detail": "range not finalized here", "range": rng}
            rng[1] = b_fixed
        if rng[0] > rng[1]:
            return {"reason": "NOTHING_NEW", "detail": "no new finalized block", "range": rng}
        for url in CHAINS[chain][1]:
            v = {"window": read_window(url, chain, t, rng[0], rng[1])}
            if first:
                v["pair"] = read_pair(url, chain, t)
            views.append(v)
    except ReadFailed as e:
        return {"reason": "RPC_UNREADABLE", "detail": str(e)[:60]}
    except Exception:
        return {"reason": "RPC_UNREADABLE", "detail": "unexpected answer"}
    if _canon(views[0]) != _canon(views[1]):
        return {"reason": "RPC_DISAGREE", "detail": "the two RPCs answer differently", "range": rng}
    return {"facts": views[0], "range": rng}


def read_holder(chain: str, token: str, holder: str, rug_block: int) -> dict:
    """A claimant's token balance at R-1 and whether it has code now, from BOTH
    RPCs -> {"balance": n, "code": bool} or {"reason": ..., "detail": ...}."""
    ch = CHAINS[chain]
    views = []
    try:
        for url in ch[1]:
            a = rpc_send(url, [["eth_chainId", []], _bal_call(token, holder, rug_block - 1),
                               ["eth_getCode", [holder, "latest"]]], RPC_LIMITS[url][1])
            if _hex_int(a[0]) != ch[0]:
                raise ReadFailed("wrong chain id")
            code = str(a[2]).strip().lower()
            if not code.startswith("0x"):
                raise ReadFailed("code")
            # EIP-7702: an EOA delegating to a contract carries 0xef0100 + address (23 bytes);
            # it still has its own key and can sign, so it is not a contract here.
            delegated = len(code) == 48 and code.startswith("0xef0100")
            views.append({"balance": _uint(a[1]), "code": len(code) > 2 and not delegated, "delegated": delegated})
    except ReadFailed as e:
        return {"reason": "RPC_UNREADABLE", "detail": str(e)[:60]}
    except Exception:
        return {"reason": "RPC_UNREADABLE", "detail": "unexpected answer"}
    if _canon(views[0]) != _canon(views[1]):
        return {"reason": "RPC_DISAGREE", "detail": "the two RPCs answer differently"}
    return views[0]
# ==== end shared rpc ====
