# v0.3.0
# { "Depends": "py-genlayer:babwp9t37jw9g4j2bccgn14g6x7x9s1f7dsmh7emvz735pz4zxa0" }
import genlayer as gl
from genlayer import *
from dataclasses import dataclass
import json
import typing

# RugBond - a token team (or a launchpad) bonds GEN behind a frozen liquidity
# promise on a Uniswap V2-style pool.
#
# The TEAM opens a BOND and locks GEN in it. The terms freeze at creation; there
# is no cancel and no amendment: the chain, the token, its V2 pair, the
# LP-holder addresses (team wallets and/or lockers), the promised minimum LP
# amount they hold together, the start block, the end time, the claim window,
# the victim-fund address (never the team), the extra excluded addresses
# (routers, other team wallets) and the dust floor.
#
# Anyone files a RUG CHECK. Validators read the next stretch of finalized
# blocks from TWO RPCs that must agree (contracts/shared/rpc.py read_check):
# every LP Transfer out of an LP holder, and the holders' summed LP balance at
# the end of each block that had one. Code applies the rule
# (contracts/shared/common.py judge_scan):
#
#   RUGGED  the summed balance was below the promised minimum at a block R
#           between the start block and the end time; R is the first such
#           block (the reads move forward block by block from the start).
#   HELD    the reads reached a block at or after the end time with no such
#           block.
#   PENDING a read failed or the RPCs disagree: never a verdict. The cursor
#           does not move; anyone checks again.
#   VOID    the pair is not a pool of the token that a listed factory knows.
#
# After RUGGED each token holder claims once, as msg.sender (the same key on
# both chains), optionally paying a beneficiary it committed on chain:
#
#   share = bond * min(balanceOf(holder, start block), balanceOf(holder, R-1))
#                // (totalSupply(R-1) - excluded balances at R-1)
#
# read from two archive RPCs that must agree. Contracts (code at the address),
# excluded addresses, and addresses that received the token directly from a
# team sender (an excluded address other than the pair and the routers) between
# the start block and R cannot claim; a share below the dust floor is refused.
# After the claim window anyone settles: what nobody claimed goes to the victim
# fund. HELD (or VOID): the bond goes back to the team. A bond still unread at
# its recovery deadline (fixed at creation: max(end time, creation) + recovery
# window) is UNRESOLVED and its bond goes to the victim fund. No model is asked
# anything; no owner can intervene.
#
# RULES
#   1. create_bond is the only payable method and never raises: a refusal
#      credits the value back to the sender (withdraw_credit). Studio keeps the
#      value of a call that fails, so raising there would strand it.
#   2. Every check runs before the first write; counters move only after.
#   3. GEN leaves only through _send: one external value message per call,
#      posted in the call that records the payout. The caller funds it.
#   4. Ledger: received = held + claims_paid + returned + to_victim_funds +
#      credits_paid + swept; held = open bond balances + credits owed. Anything
#      above held in the balance arrived outside create_bond; sweep_stray sends
#      it to the deployer.

VERSION = "1.0.0"

B_ACTIVE = "ACTIVE"
B_RUGGED = "RUGGED"
B_HELD = "HELD"
B_VOID = "VOID"
B_CLOSED = "CLOSED"            # RUGGED, claim window over, the rest sent to the victim fund
B_RETURNED = "RETURNED"        # HELD or VOID, the bond sent back to the team
B_UNRESOLVED = "UNRESOLVED"    # never read to a verdict by its recovery deadline, sent to the victim fund
STATUSES = (B_ACTIVE, B_RUGGED, B_HELD, B_VOID, B_CLOSED, B_RETURNED, B_UNRESOLVED)

COUNT_KEYS = ("bonds", "create_refused", "checks", "checks_scanned", "checks_pending", "rugged", "held", "void",
              "claims", "beneficiaries", "settles", "credit_withdrawals", "sweeps")

# mode -> (chains, min_claim_window_s, recovery_s, stale_s, sweep_delay_s)
#   min_claim_window_s  the shortest claim window a bond may set
#   recovery_s          after max(end time, creation), how long checks may still
#                       run before the bond is UNRESOLVED; fixed at creation, so
#                       PENDING checks cannot extend it
#   stale_s             LaunchGate: an ACTIVE bond whose last read block is older
#                       than this is PENDING, never "held so far" (Base Sepolia's
#                       finalized head trails its tip by about 4.4 hours)
#   sweep_delay_s       sweep_stray waits this long after the last send
MODES = {
    "CANONICAL": (("ethereum",), 3600, 7 * 86400, 6 * 3600, 172800),
    "DEMO": (("base-sepolia",), 60, 3600, 6 * 3600, 3600),
}
MAX_PERIOD_S = 366 * 86400      # end time at most this far after creation
MAX_CLAIM_WINDOW_S = 180 * 86400
MAX_NAME = 80
MIN_BOND = 10 ** 15             # 0.001 GEN
MAX_AMOUNT = 10 ** 30
MAX_UINT = (1 << 256) - 1
REPLAY_GRACE_S = 3600           # a start block older than creation by more than this marks a replay
PAGE_MAX = 50

# ==== shared helpers: contracts/shared/common.py, inlined by tools/build.py; edit there ====
# The runner rejects the str replace method; slice around find() instead.

# chain -> (chain id, (log RPC A, log RPC B), blocks one check reads, (state RPC A, state RPC B))
# Every read is made from TWO RPCs run by different operators and refused unless
# they answer identically: the LP Transfer logs from the two log RPCs, the
# balances, headers and pair calls (archive state) from the two state RPCs. A
# check builds view A from log A + state A and view B from log B + state B and
# compares them. Each endpoint is used for what it serves from GenVM with every
# validator reading at once (docs/FEASIBILITY.md). tools/lib/chains.mjs holds the
# same table.
CHAINS = {
    "ethereum": (1, ("https://gateway.tenderly.co/public/mainnet", "https://rpc.mevblocker.io"), 80000,
                 ("https://rpc.mevblocker.io", "https://eth-mainnet.public.blastapi.io")),
    "base-sepolia": (84532, ("https://base-sepolia.gateway.tenderly.co", "https://base-sepolia-rpc.publicnode.com"),
                     40000, ("https://base-sepolia-rpc.publicnode.com", "https://sepolia.base.org")),
}
# url -> (blocks per eth_getLogs request, calls per JSON-RPC batch, accepts a log
# range past its head). The two log RPCs may cut a range differently; the merged
# logs are what is compared.
RPC_LIMITS = {
    "https://gateway.tenderly.co/public/mainnet": (80000, 3, True),
    "https://rpc.mevblocker.io": (10000, 12, True),
    "https://eth-mainnet.public.blastapi.io": (10, 12, True),
    "https://base-sepolia.gateway.tenderly.co": (40000, 3, False),
    "https://base-sepolia-rpc.publicnode.com": (40000, 12, False),
    "https://sepolia.base.org": (200, 6, False),
}
# Swap routers per chain: tokens a buyer receives from a router came from the pair,
# so a router is never a "team" sender for the received-from-excluded rule (they
# stay excluded from claiming and from the snapshot when a bond lists them).
ROUTERS = {
    "ethereum": ("0x7a250d5630b4cf539739df2c5dacb4c659f2488d", "0xd9e1ce17f2641f24ae83637ab66a2cca9c378b9f",
                 "0x3fc91a3afd70395cd496c647d5a6cc9d4b2b7fad", "0x66a9893cc07d91d95644aedd05d03f95e1dba8af"),
    "base-sepolia": ("0x1689e7b1f10000ae47ebfe339a4f69decd19f602", "0x492e6456d9528771018deb9e87ef7750ef184104"),
}
TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
ZERO = "0x" + "0" * 40
DEAD = "0x000000000000000000000000000000000000dead"
RPC_TRIES = 4
MAX_PROBES = 6          # blocks with an LP transfer out of the holders whose summed balance one check reads
MAX_HOLDERS = 8         # LP-holder addresses per bond
MAX_EXCLUDED = 24       # extra excluded addresses per bond (besides team, pair, token, LP holders, zero, dead)

V_SCANNED = "SCANNED"
V_RUGGED = "RUGGED"
V_HELD = "HELD"
V_PENDING = "PENDING"


def _as_int(v: typing.Any, default: int = -1) -> int:
    if isinstance(v, bool):
        return default
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        t = v.strip()
        if t != "" and t.isdigit() and len(t) <= 78:
            return int(t)
    return default


def _is_hex(s: typing.Any, n: int = -1) -> bool:
    if not isinstance(s, str) or (n >= 0 and len(s) != n):
        return False
    for ch in s:
        if ch not in "0123456789abcdef":
            return False
    return True


def _addr(v: typing.Any) -> str:
    """A lowercase 0x address, or "" if v is not one."""
    t = str(v).strip().lower()
    if len(t) != 42 or not t.startswith("0x"):
        return ""
    return t if _is_hex(t[2:], 40) else ""


def _hash32(v: typing.Any) -> str:
    t = str(v).strip().lower()
    if len(t) != 66 or not t.startswith("0x") or not _is_hex(t[2:], 64):
        return ""
    return t


def _hex_int(v: typing.Any) -> int:
    """0x-prefixed hex quantity -> int, or -1."""
    if not isinstance(v, str):
        return -1
    t = v.strip().lower()
    if not t.startswith("0x") or len(t) < 3 or len(t) > 66 or not _is_hex(t[2:]):
        return -1
    return int(t[2:], 16)


def _word_addr(v: typing.Any) -> str:
    """A 32-byte word (a topic) holding an address -> the address, or ""."""
    t = _hash32(v)
    if t == "" or t[2:26] != "0" * 24:
        return ""
    return "0x" + t[26:]


def _word_uint(v: typing.Any) -> int:
    """An eth_call answer that is exactly one 32-byte word -> the uint, or -1."""
    t = _hash32(v)
    return -1 if t == "" else int(t[2:], 16)


def _pad(a: str) -> str:
    return "0x" + "0" * 24 + a[2:]


def _canon(obj: typing.Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def _days_from_civil(y: int, m: int, d: int) -> int:
    y -= 1 if m <= 2 else 0
    era = (y if y >= 0 else y - 399) // 400
    yoe = y - era * 400
    doy = (153 * (m + (-3 if m > 2 else 9)) + 2) // 5 + d - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def _civil_from_days(z: int) -> tuple:
    z += 719468
    era = (z if z >= 0 else z - 146096) // 146097
    doe = z - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    y = yoe + era * 400
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    d = doy - (153 * mp + 2) // 5 + 1
    m = mp + 3 if mp < 10 else mp - 9
    return (y + (1 if m <= 2 else 0), m, d)


def _epoch_from_iso(value: typing.Any) -> int:
    """Seconds since the epoch from gl.message.raw["datetime"]
    ("2026-10-07T12:00:00Z" or with fractional seconds), identical on every
    validator. 0 if unreadable."""
    if not isinstance(value, str) or len(value) < 19:
        return 0
    try:
        year = int(value[0:4])
        month = int(value[5:7])
        day = int(value[8:10])
        hour = int(value[11:13])
        minute = int(value[14:16])
        second = int(value[17:19])
    except Exception:
        return 0
    if month < 1 or month > 12 or day < 1 or day > 31 or hour > 23 or minute > 59 or second > 60:
        return 0
    return _days_from_civil(year, month, day) * 86400 + hour * 3600 + minute * 60 + second


def clean_text(text: typing.Any, n: int) -> str:
    """Printable ASCII only, no markup characters, whitespace collapsed, at most n chars."""
    out = ""
    for ch in str(text):
        if " " <= ch <= "~" and ch not in "<>\"'`\\":
            out += ch
    return " ".join(out.split())[:n]


def _parse_list(raw: typing.Any) -> typing.Any:
    try:
        v = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return None
    return v if isinstance(v, list) else None


def addr_list(raw: typing.Any, most: int) -> typing.Any:
    """A JSON list of addresses -> sorted distinct lowercase addresses, or a reason string."""
    v = _parse_list(raw)
    if v is None:
        return "BAD_JSON"
    if len(v) > most:
        return "TOO_MANY"
    out = []
    for x in v:
        a = _addr(x)
        if a == "":
            return "BAD_ADDRESS"
        if a not in out:
            out.append(a)
    return sorted(out)


# =============================================================================
# the rule (pure: the offline suite calls it on every shape)
# =============================================================================

def scan_range(t: dict, cursor: int, fin: int) -> list:
    """The blocks one check reads: [a, b], a = the block after the cursor (the
    start block on the first check), b = a + the chain's check span - 1, cut at the
    finalized head. a > b: nothing new is finalized."""
    ch = CHAINS[t["chain"]]
    a = cursor + 1 if cursor >= int(t["start_block"]) else int(t["start_block"])
    b = a + ch[2] - 1
    if b > fin:
        b = fin
    return [a, b]


def judge_scan(t: dict, facts: dict) -> dict:
    """One agreed read of blocks [a, b] -> the verdict.
      RUGGED   the summed LP balance of the LP holders was below min_lp at the
               end of block R (the first block of [a, b] where it was: the
               start block itself, or a block with an LP Transfer out of a
               holder), and R's timestamp is at or before end_time.
      HELD     no such block, and the read reached a block whose timestamp is
               at or after end_time (block timestamps strictly increase, so
               every block at or before end_time has been read), or the first
               such block is after end_time.
      SCANNED  no such block yet; the cursor moves to b.
    The probes are in block order and stop at the first below the floor."""
    floor = int(t["min_lp"])
    end = int(t["end_time"])
    r = facts.get("rug")
    if isinstance(r, dict):
        if int(r["ts"]) <= end:
            return {"verdict": V_RUGGED, "cursor": int(r["block"]), "block": int(r["block"])}
        return {"verdict": V_HELD, "cursor": int(r["block"]) - 1, "block": 0}
    for p in facts.get("probes", []):
        if int(p[1]) < floor:
            # a probe below the floor with no rug record is a malformed read
            return {"verdict": V_PENDING, "cursor": -1, "block": 0}
    if int(facts["end_ts"]) >= end:
        return {"verdict": V_HELD, "cursor": int(facts["b"]), "block": 0}
    return {"verdict": V_SCANNED, "cursor": int(facts["b"]), "block": 0}


def share_of(bond_amount: int, balance: int, denom: int) -> int:
    """A holder's share of the bond: bond * balance // denom (integer math,
    rounded down). 0 when the denominator is not positive."""
    if denom <= 0 or balance <= 0 or bond_amount <= 0:
        return 0
    s = (bond_amount * balance) // denom
    return s if s < bond_amount else bond_amount


def team_senders(t: dict) -> list:
    """The addresses whose DIRECT token transfers to a claimant between the start
    block and R disqualify it: every excluded address except the pair (buys come
    from the pair), 0x0 (mints), 0x...dEaD and the chain's swap routers."""
    out = []
    for a in t["excluded_all"]:
        if a == t["pair"] or a == ZERO or a == DEAD or a in ROUTERS.get(t["chain"], ()):
            continue
        out.append(a)
    return sorted(out)


def claim_balance(start_balance: int, r_balance: int) -> int:
    """The balance a claim is paid on: the smaller of the holder's balance at the
    end of the bond's start block and at R-1. Tokens bought after the bond
    opened earn nothing."""
    return start_balance if start_balance < r_balance else r_balance


def snapshot_denominator(supply: int, excluded: list) -> int:
    """totalSupply(R-1) minus the excluded addresses' balances at R-1 (never below 0)."""
    d = supply
    for e in excluded:
        d -= int(e[1])
    return d if d > 0 else 0
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
        if url in CHAINS[ch][1] or url in CHAINS[ch][3]:
            return True
    return False


def parse_batch(doc: typing.Any, n: int, soft: int = -1) -> list:
    """A JSON-RPC batch answer -> results in call order. Any error raises,
    except at index `soft`, which then reads None."""
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
            if i == soft:
                out.append(None)
                continue
            raise ReadFailed("rpc error")
        if "result" not in item:
            raise ReadFailed("no result")
        out.append(item["result"])
    return out


def rpc_send(url: str, calls: list, per: int, soft: int = -1) -> list:
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
                got = parse_batch(json.loads(_raw(res).decode("utf-8", errors="replace")), len(chunk),
                                  soft - i if 0 <= soft - i < len(chunk) else -1)
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


def _ts(h: typing.Any, n: int) -> int:
    if not isinstance(h, dict) or _hex_int(h.get("number")) != n:
        raise ReadFailed("header")
    t = _hex_int(h.get("timestamp"))
    if t <= 0:
        raise ReadFailed("timestamp")
    return t


def _parse_logs(parts: list, t: dict, a: int, b: int) -> list:
    pair = t["pair"]
    holders = t["lp_holders"]
    logs = []
    for part in parts:
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
            if frm not in holders or to == "" or amt < 0 or blk < a or li < 0 or txh == "":
                raise ReadFailed("log fields")
            if blk <= b:
                logs.append([blk, li, txh, frm, to, str(amt)])
    return sorted(logs, key=lambda x: x[0] * 1000000 + x[1])


def _logs_call(t: dict, w: int, z: int) -> list:
    return ["eth_getLogs", [{"address": t["pair"], "topics": [TRANSFER, [_pad(h) for h in t["lp_holders"]]],
                             "fromBlock": hex(w), "toBlock": hex(z)}]]


def read_open(url: str, chain: str, t: dict, a: int) -> dict:
    """Request 1 on one endpoint: chain id, finalized head and the first log
    window from block a. An endpoint that refuses ranges past its head is asked
    up to its "finalized" block; if that range is too long for it, the logs are
    read in windows afterwards (logs None, to = a - 1). Blocks past the check's
    range are dropped later."""
    lim = RPC_LIMITS[url]
    top = a + CHAINS[chain][2] - 1
    z = a + lim[0] - 1
    if z > top:
        z = top
    call = _logs_call(t, a, z)
    if not lim[2]:
        call[1][0]["toBlock"] = "finalized"
    r = rpc_send(url, [["eth_chainId", []], ["eth_getBlockByNumber", ["finalized", False]], call], 3, 2)
    if _hex_int(r[0]) != CHAINS[chain][0]:
        raise ReadFailed("wrong chain id")
    fin = _hex_int(r[1].get("number")) if isinstance(r[1], dict) else -1
    if fin < 0:
        raise ReadFailed("no finalized head")
    if r[2] is None:
        return {"fin": fin, "logs": [], "to": a - 1}
    return {"fin": fin, "logs": r[2], "to": z if lim[2] else (fin if fin < top else top)}


def read_window(url: str, surl: str, chain: str, t: dict, a: int, b: int, opened: dict, first: bool) -> dict:
    """Blocks [a, b] of one bond as ONE view: logs from the log endpoint `url`,
    state from the state endpoint `surl` (both views are read; the caller
    compares), in as few requests as each endpoint allows: the opening request
    (read_open), the rest of the log windows, one batch of state, and one more
    when there is a rug or a pair to check. -> {"window": ..., "pair": ...}
      logs    every LP Transfer out of an LP holder in [a, b] (eth_getLogs on
              the pair, topic1 = any holder): [block, log index, tx, from, to, amount]
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
    per = RPC_LIMITS[surl][1]
    pair = t["pair"]
    holders = t["lp_holders"]
    start = int(t["start_block"])
    floor = int(t["min_lp"])
    parts = [opened["logs"]]
    w = int(opened["to"]) + 1
    more = []
    while w <= b:
        z = w + span - 1
        if z > b:
            z = b
        more.append(_logs_call(t, w, z))
        w = z + 1
    if len(more) > 0:
        parts = parts + rpc_send(url, more, 1)
    logs = _parse_logs(parts, t, a, b)
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
    sc = [["eth_getBlockByNumber", [hex(b), False]]]
    if a == start:
        sc.append(["eth_getBlockByNumber", [hex(start), False]])
    if first:
        sc.append(["eth_call", [{"to": pair, "data": "0x0dfe1681"}, "latest"]])
        sc.append(["eth_call", [{"to": pair, "data": "0xd21220a7"}, "latest"]])
        sc.append(["eth_call", [{"to": pair, "data": "0xc45a0155"}, "latest"]])
    k0 = len(sc)
    for blk in pb:
        for h in holders:
            sc.append(_bal_call(pair, h, blk))
    vals = rpc_send(surl, sc, per)
    end_ts = _ts(vals[0], b)
    start_ts = _ts(vals[1], start) if a == start else 0
    pr = None
    if first:
        j = 2 if a == start else 1
        pr = {"token0": _word_addr(vals[j]), "token1": _word_addr(vals[j + 1]), "factory": _word_addr(vals[j + 2]),
              "ok": False, "why": ""}
    probes = []
    rug_at = -1
    k = k0
    for blk in pb:
        tot = 0
        for h in holders:
            tot += _uint(vals[k])
            k += 1
        probes.append([blk, str(tot)])
        if tot < floor:
            rug_at = blk
            break
    third = []
    how = ""
    if pr is not None:
        if pr["token0"] == "" or pr["token1"] == "" or pr["factory"] == "":
            pr["why"] = "NOT_A_PAIR"
        elif t["token"] != pr["token0"] and t["token"] != pr["token1"]:
            pr["why"] = "TOKEN_NOT_IN_PAIR"
        else:
            how = FACTORIES.get(chain, {}).get(pr["factory"], "")
            if how == "":
                pr["why"] = "UNKNOWN_FACTORY"
            else:
                data = ("0xe6a43905" if how == "getPair" else "0x79bc57d5") + "0" * 24 + pr["token0"][2:] + "0" * 24 + \
                    pr["token1"][2:]
                if how == "getPool":
                    data = data + "0" * 64          # stable = false: volatile pools only
                third.append(["eth_call", [{"to": pr["factory"], "data": data}, "latest"]])
    out = {"a": a, "b": b, "logs": logs, "probes": probes, "rug": None, "end_ts": end_ts, "start_ts": start_ts}
    snap = rug_at >= 0
    if snap:
        third.append(["eth_getBlockByNumber", [hex(rug_at), False]])
        third.append(["eth_call", [{"to": t["token"], "data": "0x18160ddd"}, hex(rug_at - 1)]])
        for h in holders:
            third.append(_bal_call(pair, h, rug_at - 1))
        for e in t["excluded_all"]:
            third.append(_bal_call(t["token"], e, rug_at - 1))
    got = rpc_send(surl, third, per) if len(third) > 0 else []
    i = 0
    if how != "":
        pr["ok"] = _word_addr(got[0]) == pair
        if not pr["ok"]:
            pr["why"] = "FACTORY_DOES_NOT_KNOW_PAIR"
        i = 1
    if snap:
        out["b"] = rug_at
        keep = []
        for lg in logs:
            if lg[0] <= rug_at:
                keep.append(lg)
        out["logs"] = keep
        ts = _ts(got[i], rug_at)
        out["end_ts"] = ts
        txs = []
        for lg in keep:
            if lg[0] == rug_at and lg[2] not in txs:
                txs.append(lg[2])
        rug = {"block": rug_at, "ts": ts, "txs": sorted(txs), "lp_after": probes[len(probes) - 1][1]}
        if ts <= int(t["end_time"]):
            supply = _uint(got[i + 1])
            lpb = 0
            for n in range(len(holders)):
                lpb += _uint(got[i + 2 + n])
            ex = []
            for n in range(len(t["excluded_all"])):
                ex.append([t["excluded_all"][n], str(_uint(got[i + 2 + len(holders) + n]))])
            rug["supply"] = str(supply)
            rug["lp_before"] = str(lpb)
            rug["excluded"] = ex
            rug["denom"] = str(snapshot_denominator(supply, ex))
        out["rug"] = rug
    view = {"window": out}
    if pr is not None:
        view["pair"] = pr
    return view


def read_check(chain: str, t: dict, cursor: int, first: bool, b_fixed: int) -> dict:
    """One rug check read from BOTH RPCs of the chain ->
    {"facts": ..., "range": [a, b]} when they agree, else {"reason": ..., "detail": ...}
    (RPC_UNREADABLE, RPC_DISAGREE, NOTHING_NEW). b_fixed < 0: the leader picks b
    (cut at the lower of the two finalized heads); else a validator re-reads the
    leader's range and needs b at or below both its finalized heads."""
    views = []
    rng = [0, 0]
    try:
        urls = CHAINS[chain][1]
        a = cursor + 1 if cursor >= int(t["start_block"]) else int(t["start_block"])
        opened = []
        for url in urls:
            opened.append(read_open(url, chain, t, a))
        fin = opened[0]["fin"] if opened[0]["fin"] < opened[1]["fin"] else opened[1]["fin"]
        rng = scan_range(t, cursor, fin)
        if b_fixed >= 0:
            top = rng[0] + CHAINS[chain][2] - 1
            if b_fixed > fin or b_fixed > top:
                return {"reason": "RPC_DISAGREE", "detail": "range not finalized here", "range": rng}
            rng[1] = b_fixed
        if rng[0] > rng[1]:
            return {"reason": "NOTHING_NEW", "detail": "no new finalized block", "range": rng}
        surls = CHAINS[chain][3]
        for n in range(len(urls)):
            views.append(read_window(urls[n], surls[n], chain, t, rng[0], rng[1], opened[n], first))
    except ReadFailed as e:
        return {"reason": "RPC_UNREADABLE", "detail": str(e)[:60], "range": rng}
    except Exception:
        return {"reason": "RPC_UNREADABLE", "detail": "unexpected answer", "range": rng}
    if _canon(views[0]) != _canon(views[1]):
        return {"reason": "RPC_DISAGREE", "detail": "the two RPCs answer differently", "range": rng}
    return {"facts": views[0], "range": rng}


def read_claim(chain: str, t: dict, holder: str, rug_block: int) -> dict:
    """What a claim needs, as two views (log RPC n + state RPC n) that must be
    identical -> {"start_balance", "balance", "code", "delegated", "from_team"}
    or {"reason": ..., "detail": ...}.
      start_balance  balanceOf(holder) at the end of the start block
      balance        balanceOf(holder) at R-1
      code           the address has code now (an EIP-7702 delegation is not code)
      from_team      Transfer logs of the token TO the holder FROM a team sender
                     (team_senders) in [start block, R]: [block, tx, from], up to 5"""
    ch = CHAINS[chain]
    start = int(t["start_block"])
    senders = team_senders(t)
    views = []
    try:
        for n in range(2):
            url = ch[1][n]
            surl = ch[3][n]
            st = rpc_send(surl, [["eth_chainId", []], _bal_call(t["token"], holder, start),
                                 _bal_call(t["token"], holder, rug_block - 1), ["eth_getCode", [holder, "latest"]]],
                          RPC_LIMITS[surl][1])
            if _hex_int(st[0]) != ch[0]:
                raise ReadFailed("wrong chain id")
            code = str(st[3]).strip().lower()
            if not code.startswith("0x"):
                raise ReadFailed("code")
            delegated = len(code) == 48 and code.startswith("0xef0100")
            hits = []
            if len(senders) > 0:
                calls = []
                w = start
                span = RPC_LIMITS[url][0]
                while w <= rug_block:
                    z = w + span - 1
                    if z > rug_block:
                        z = rug_block
                    calls.append(["eth_getLogs", [{"address": t["token"], "topics": [TRANSFER, [_pad(x) for x in senders],
                                                                                    _pad(holder)],
                                                   "fromBlock": hex(w), "toBlock": hex(z)}]])
                    w = z + 1
                parts = rpc_send(url, calls, 1)
                for part in parts:
                    if not isinstance(part, list):
                        raise ReadFailed("logs")
                    for lg in part:
                        if not isinstance(lg, dict) or lg.get("removed") is True:
                            raise ReadFailed("log")
                        tp = lg.get("topics", [])
                        if _addr(lg.get("address", "")) != t["token"] or not isinstance(tp, list) or len(tp) != 3 \
                                or str(tp[0]).lower() != TRANSFER:
                            continue
                        frm = _word_addr(tp[1])
                        blk = _hex_int(lg.get("blockNumber"))
                        txh = _hash32(lg.get("transactionHash", ""))
                        if frm not in senders or _word_addr(tp[2]) != holder or blk < start or blk > rug_block or txh == "":
                            raise ReadFailed("log fields")
                        hits.append([blk, txh, frm])
            hits = sorted(hits, key=lambda x: (x[0], x[1], x[2]))
            views.append({"start_balance": _uint(st[1]), "balance": _uint(st[2]), "code": len(code) > 2 and not delegated,
                          "delegated": delegated, "from_team": hits[0:5]})
    except ReadFailed as e:
        return {"reason": "RPC_UNREADABLE", "detail": str(e)[:60]}
    except Exception:
        return {"reason": "RPC_UNREADABLE", "detail": "unexpected answer"}
    if _canon(views[0]) != _canon(views[1]):
        return {"reason": "RPC_DISAGREE", "detail": "the two RPCs answer differently"}
    return views[0]
# ==== end shared rpc ====


def parse_terms(mode_chains: tuple, chain: typing.Any, token: typing.Any, pair: typing.Any, lp_holders_json: typing.Any,
                min_lp: typing.Any, start_block: typing.Any, end_time: typing.Any, claim_window_s: typing.Any,
                victim_fund: typing.Any, excluded_json: typing.Any, dust_floor: typing.Any, team: str,
                now: int, min_claim: int) -> typing.Any:
    """The frozen terms -> a dict, or a reason string."""
    ch = str(chain).strip().lower()
    if ch not in CHAINS or ch not in mode_chains:
        return "UNSUPPORTED_CHAIN"
    tok = _addr(token)
    pr = _addr(pair)
    if tok == "" or pr == "" or tok == ZERO or pr == ZERO:
        return "BAD_TOKEN_OR_PAIR"
    if tok == pr:
        return "TOKEN_IS_PAIR"
    holders = addr_list(lp_holders_json, MAX_HOLDERS)
    if isinstance(holders, str):
        return "LP_HOLDERS_" + holders
    if len(holders) == 0:
        return "LP_HOLDERS_EMPTY"
    if pr in holders or tok in holders:
        return "LP_HOLDER_IS_PAIR_OR_TOKEN"
    mlp = _as_int(min_lp, -1)
    if mlp <= 0 or mlp > MAX_UINT:
        return "MIN_LP_INVALID"
    sb = _as_int(start_block, -1)
    if sb <= 0 or sb > 10 ** 12:
        return "START_BLOCK_INVALID"
    et = _as_int(end_time, -1)
    if et <= 0 or et > now + MAX_PERIOD_S:
        return "END_TIME_INVALID"
    cw = _as_int(claim_window_s, -1)
    if cw < min_claim or cw > MAX_CLAIM_WINDOW_S:
        return "CLAIM_WINDOW_INVALID"
    vf = _addr(victim_fund)
    if vf == "" or vf == ZERO or vf == DEAD:
        return "VICTIM_FUND_INVALID"
    if vf == team:
        return "VICTIM_FUND_IS_TEAM"
    if vf in holders:
        return "VICTIM_FUND_IS_LP_HOLDER"
    extra = addr_list(excluded_json, MAX_EXCLUDED)
    if isinstance(extra, str):
        return "EXCLUDED_" + extra
    if vf in extra:
        return "VICTIM_FUND_IS_EXCLUDED"
    dust = _as_int(dust_floor, -1)
    if dust < 0 or dust > MAX_AMOUNT:
        return "DUST_FLOOR_INVALID"
    every = [team, pr, tok, ZERO, DEAD]
    for h in holders:
        every.append(h)
    for e in extra:
        every.append(e)
    ex_all = []
    for e in every:
        if e not in ex_all:
            ex_all.append(e)
    return {"chain": ch, "token": tok, "pair": pr, "lp_holders": holders, "min_lp": str(mlp), "start_block": sb,
            "end_time": et, "claim_window_s": cw, "victim_fund": vf, "excluded": extra,
            "excluded_all": sorted(ex_all), "dust_floor": str(dust)}


# =============================================================================
# storage
# =============================================================================

@gl.storage.allow
@dataclass
class Bond:
    bond_id: u64
    team: str
    name: str
    terms_json: str
    amount: u256
    created_at: u64
    recovery_deadline: u64
    status: str
    cursor: u64
    cursor_ts: u64
    scanned_at: u64
    n_checks: u64
    n_pending: u64
    last_result: str
    last_reason: str
    last_check_at: u64
    pair_json: str
    start_ts: u64
    replay: bool
    rug_block: u64
    rug_ts: u64
    rug_json: str
    denom: u256
    rugged_at: u64
    claim_deadline: u64
    paid: u256
    n_claims: u64
    settled_amount: u256
    settled_to: str
    settled_at: u64
    settled_by: str
    verdict_at: u64


@gl.storage.allow
@dataclass
class Check:
    check_id: u64
    bond_id: u64
    by: str
    at: u64
    result: str
    reason: str
    detail: str
    a: u64
    b: u64
    n_logs: u64
    probes_json: str
    logs_json: str


@gl.storage.allow
@dataclass
class Claim:
    bond_id: u64
    holder: str
    payee: str
    balance: u256
    share: u256
    claimed_at: u64
    claim_no: u64


class RugBond(gl.contract.Contract):
    mode: str
    deployer: str
    min_claim_window_s: u64
    recovery_s: u64
    stale_s: u64
    sweep_delay_s: u64
    last_send_at: u64
    n_bonds: u64
    n_checks: u64
    bonds: gl.storage.TreeMap[u64, Bond]
    checks: gl.storage.TreeMap[u64, Check]
    bond_checks: gl.storage.TreeMap[str, u64]
    claims: gl.storage.TreeMap[str, Claim]
    bond_claims: gl.storage.TreeMap[str, str]
    holder_n: gl.storage.TreeMap[str, u64]
    holder_bonds: gl.storage.TreeMap[str, u64]
    beneficiary: gl.storage.TreeMap[str, str]
    token_n: gl.storage.TreeMap[str, u64]
    token_bonds: gl.storage.TreeMap[str, u64]
    team_n: gl.storage.TreeMap[str, u64]
    team_bonds: gl.storage.TreeMap[str, u64]
    credits: gl.storage.TreeMap[str, u256]
    counts: gl.storage.TreeMap[str, u64]
    received_total: u256
    open_total: u256
    claims_paid_total: u256
    returned_total: u256
    victim_total: u256
    credit_owed_total: u256
    credit_paid_total: u256
    stray_swept_total: u256

    def __init__(self, mode: str) -> None:
        m = str(mode).strip().upper()
        if m not in MODES:
            raise gl.vm.UserError("mode must be CANONICAL or DEMO")
        p = MODES[m]
        self.mode = m
        self.deployer = gl.message.sender_address.as_hex.lower()
        self.min_claim_window_s = u64(p[1])
        self.recovery_s = u64(p[2])
        self.stale_s = u64(p[3])
        self.sweep_delay_s = u64(p[4])
        self.n_bonds = u64(0)
        self.n_checks = u64(0)

    # --- helpers --------------------------------------------------------------

    def _now(self) -> int:
        return _epoch_from_iso(gl.message.raw.get("datetime", ""))

    def _sender(self) -> str:
        return gl.message.sender_address.as_hex.lower()

    def _bump(self, key: str, n: int = 1) -> None:
        self.counts[key] = u64(int(self.counts.get(key, u64(0))) + n)

    def _bond(self, bond_id: typing.Any) -> typing.Any:
        bid = _as_int(bond_id, 0)
        if bid <= 0:
            return None
        return self.bonds.get(u64(bid))

    def _held(self) -> int:
        return int(self.open_total) + int(self.credit_owed_total)

    def _refuse(self, value: int, reason: str) -> dict:
        """A payable refusal: the value is credited back to the sender, never kept, never raised on."""
        if value > 0:
            who = self._sender()
            self.credits[who] = u256(int(self.credits.get(who, u256(0))) + value)
            self.credit_owed_total = u256(int(self.credit_owed_total) + value)
            self.received_total = u256(int(self.received_total) + value)
        self._bump("create_refused")
        return {"ok": False, "reason": reason, "credited": str(value)}

    def _send(self, who: str, amount: int) -> None:
        """The only way GEN leaves: an external value message (EthSend) to
        `who`, applied when this transaction finalizes and paid for by the
        caller's message allocation. Studio Dev skips an internal
        emit_transfer (declared budget 0) and credits the value back, so it is
        never used. Posted in the same call that records the payout: if it
        cannot be posted, the call fails and nothing is recorded."""
        self.last_send_at = u64(self._now())
        gl.evm.Account(Address(who)).emit_call(u256(amount), b"")

    def _remaining(self, b: Bond) -> int:
        return int(b.amount) - int(b.paid) - int(b.settled_amount)

    # --- bonds ------------------------------------------------------------------

    @gl.public.write.payable
    def create_bond(self, name: str, chain: str, token: str, pair: str, lp_holders_json: str, min_lp: typing.Any,
                    start_block: typing.Any, end_time: typing.Any, claim_window_s: typing.Any, victim_fund: str,
                    excluded_json: str, dust_floor: typing.Any) -> typing.Any:
        """Open a bond and lock msg.value in it. The sender is the team. Never raises."""
        value = int(gl.message.value)
        now = self._now()
        if now <= 0:
            return self._refuse(value, "NO_CLOCK")
        if value < MIN_BOND:
            return self._refuse(value, "BOND_BELOW_MINIMUM")
        if value > MAX_AMOUNT:
            return self._refuse(value, "BOND_TOO_LARGE")
        nm = clean_text(name, MAX_NAME)
        if nm == "":
            return self._refuse(value, "NAME_REQUIRED")
        team = self._sender()
        t = parse_terms(MODES[self.mode][0], chain, token, pair, lp_holders_json, min_lp, start_block, end_time,
                        claim_window_s, victim_fund, excluded_json, dust_floor, team, now,
                        int(self.min_claim_window_s))
        if isinstance(t, str):
            return self._refuse(value, t)
        base = int(t["end_time"]) if int(t["end_time"]) > now else now
        # --- writes
        bid = int(self.n_bonds) + 1
        self.n_bonds = u64(bid)
        self.bonds[u64(bid)] = Bond(
            bond_id=u64(bid), team=team, name=nm, terms_json=_canon(t), amount=u256(value), created_at=u64(now),
            recovery_deadline=u64(base + int(self.recovery_s)), status=B_ACTIVE, cursor=u64(0), cursor_ts=u64(0),
            scanned_at=u64(0), n_checks=u64(0), n_pending=u64(0), last_result="", last_reason="",
            last_check_at=u64(0), pair_json="{}", start_ts=u64(0), replay=False, rug_block=u64(0), rug_ts=u64(0),
            rug_json="{}", denom=u256(0), rugged_at=u64(0), claim_deadline=u64(0), paid=u256(0), n_claims=u64(0),
            settled_amount=u256(0), settled_to="", settled_at=u64(0), settled_by="", verdict_at=u64(0))
        tk = t["chain"] + ":" + t["token"]
        n = int(self.token_n.get(tk, u64(0)))
        self.token_bonds[tk + ":" + str(n)] = u64(bid)
        self.token_n[tk] = u64(n + 1)
        n = int(self.team_n.get(team, u64(0)))
        self.team_bonds[team + ":" + str(n)] = u64(bid)
        self.team_n[team] = u64(n + 1)
        self.received_total = u256(int(self.received_total) + value)
        self.open_total = u256(int(self.open_total) + value)
        self._bump("bonds")
        return {"ok": True, "bond_id": bid, "amount": str(value), "recovery_deadline": base + int(self.recovery_s)}

    @gl.public.write
    def check(self, bond_id: int) -> typing.Any:
        """A rug check (anyone): read the next finalized blocks of the bond from
        both RPCs and apply the rule. PENDING moves nothing but the counters."""
        now = self._now()
        if now <= 0:
            raise gl.vm.UserError("REFUSED: NO_CLOCK")
        b = self._bond(bond_id)
        if b is None:
            raise gl.vm.UserError("REFUSED: NO_SUCH_BOND")
        if b.status != B_ACTIVE:
            raise gl.vm.UserError("REFUSED: BOND_IS_" + b.status)
        if now > int(b.recovery_deadline):
            raise gl.vm.UserError("REFUSED: RECOVERY_WINDOW_OVER_SETTLE_IT")
        t = json.loads(b.terms_json)
        cursor = int(b.cursor)
        first = cursor == 0
        ch = t["chain"]

        def leader() -> dict:
            return read_check(ch, t, cursor, first, -1)

        def validator(res: gl.vm.Result) -> bool:
            try:
                return agree(res)
            except Exception:
                return False

        def agree(res: gl.vm.Result) -> bool:
            if not isinstance(res, gl.vm.Return):
                return False
            got = res.calldata
            if not isinstance(got, dict):
                return False
            rng = got.get("range")
            if not isinstance(rng, list) or len(rng) != 2:
                # no range: the leader could not even read the heads
                return "reason" in got and "reason" in read_check(ch, t, cursor, first, -1)
            mine = read_check(ch, t, cursor, first, int(rng[1]))
            if "reason" in got:
                # the leader could not read: agree only if this validator cannot either
                return "reason" in mine
            if "facts" not in mine:
                return False
            return _canon(mine["facts"]) == _canon(got["facts"]) and _canon(mine["range"]) == _canon(rng)

        r = gl.vm.run_nondet(leader, validator)
        if not isinstance(r, dict) or ("reason" not in r and not isinstance(r.get("facts"), dict)):
            r = {"reason": "RPC_UNREADABLE", "detail": "no answer"}
        if r.get("reason", "") == "NOTHING_NEW":
            raise gl.vm.UserError("REFUSED: NOTHING_NEW_FINALIZED")
        who = self._sender()
        result = V_PENDING
        reason = str(r.get("reason", ""))
        detail = clean_text(r.get("detail", ""), 120)
        f = r.get("facts")
        w = None
        j = None
        pr = None
        if isinstance(f, dict):
            w = f["window"]
            if first:
                pr = f["pair"]
                if pr.get("ok") is not True:
                    result = B_VOID
                    reason = str(pr.get("why", "NOT_A_PAIR"))
            if result != B_VOID:
                j = judge_scan(t, w)
                result = j["verdict"]
                if result == V_PENDING:
                    reason = "MALFORMED_READ"
        # --- writes
        cid = int(self.n_checks) + 1
        self.n_checks = u64(cid)
        nb = int(b.n_checks)
        self.bond_checks[str(int(b.bond_id)) + ":" + str(nb)] = u64(cid)
        b.n_checks = u64(nb + 1)
        b.last_result = result
        b.last_reason = reason
        b.last_check_at = u64(now)
        self._bump("checks")
        lo = 0
        hi = 0
        logs = []
        probes = []
        if w is not None:
            lo = int(w["a"])
            hi = int(w["b"])
            logs = w["logs"]
            probes = w["probes"]
        self.checks[u64(cid)] = Check(check_id=u64(cid), bond_id=b.bond_id, by=who, at=u64(now), result=result,
                                      reason=reason, detail=detail, a=u64(lo), b=u64(hi), n_logs=u64(len(logs)),
                                      probes_json=_canon(probes), logs_json=_canon(logs[0:20]))
        if pr is not None:
            b.pair_json = _canon(pr)
        if result == V_PENDING:
            b.n_pending = u64(int(b.n_pending) + 1)
            self._bump("checks_pending")
            return {"ok": True, "check_id": cid, "result": result, "reason": reason, "detail": detail}
        if result == B_VOID:
            b.status = B_VOID
            b.verdict_at = u64(now)
            self._bump("void")
            return {"ok": True, "check_id": cid, "result": result, "reason": reason}
        if first:
            b.start_ts = u64(int(w["start_ts"]))
            b.replay = int(w["start_ts"]) + REPLAY_GRACE_S < int(b.created_at)
        b.scanned_at = u64(now)
        if result == V_RUGGED:
            rug = w["rug"]
            b.status = B_RUGGED
            b.cursor = u64(int(rug["block"]))
            b.cursor_ts = u64(int(rug["ts"]))
            b.rug_block = u64(int(rug["block"]))
            b.rug_ts = u64(int(rug["ts"]))
            b.rug_json = _canon(rug)
            b.denom = u256(int(rug["denom"]))
            b.rugged_at = u64(now)
            b.verdict_at = u64(now)
            b.claim_deadline = u64(now + int(t["claim_window_s"]))
            self._bump("rugged")
            return {"ok": True, "check_id": cid, "result": result, "rug_block": int(rug["block"]),
                    "claim_deadline": now + int(t["claim_window_s"]), "denominator": str(rug["denom"])}
        b.cursor = u64(int(j["cursor"]))
        b.cursor_ts = u64(int(w["end_ts"]))
        if result == V_HELD:
            b.status = B_HELD
            b.verdict_at = u64(now)
            self._bump("held")
        else:
            self._bump("checks_scanned")
        return {"ok": True, "check_id": cid, "result": result, "cursor": int(j["cursor"]), "cursor_ts": int(w["end_ts"])}

    @gl.public.write
    def commit_beneficiary(self, bond_id: int, beneficiary: str) -> typing.Any:
        """A holder names, once, the address its share is paid to (before claiming)."""
        b = self._bond(bond_id)
        if b is None:
            raise gl.vm.UserError("REFUSED: NO_SUCH_BOND")
        ben = _addr(beneficiary)
        if ben == "" or ben == ZERO or ben == DEAD:
            raise gl.vm.UserError("REFUSED: BAD_BENEFICIARY")
        who = self._sender()
        k = str(int(b.bond_id)) + ":" + who
        if self.beneficiary.get(k, "") != "":
            raise gl.vm.UserError("REFUSED: BENEFICIARY_ALREADY_COMMITTED")
        if self.claims.get(k) is not None:
            raise gl.vm.UserError("REFUSED: ALREADY_CLAIMED")
        if b.status not in (B_ACTIVE, B_RUGGED):
            raise gl.vm.UserError("REFUSED: BOND_IS_" + b.status)
        # --- writes
        self.beneficiary[k] = ben
        self._bump("beneficiaries")
        return {"ok": True, "bond_id": int(b.bond_id), "holder": who, "beneficiary": ben}

    @gl.public.write
    def claim(self, bond_id: int) -> typing.Any:
        """A holder's share of a RUGGED bond, paid to its committed beneficiary or to itself."""
        now = self._now()
        if now <= 0:
            raise gl.vm.UserError("REFUSED: NO_CLOCK")
        b = self._bond(bond_id)
        if b is None:
            raise gl.vm.UserError("REFUSED: NO_SUCH_BOND")
        if b.status != B_RUGGED:
            raise gl.vm.UserError("REFUSED: BOND_IS_" + b.status)
        if now > int(b.claim_deadline):
            raise gl.vm.UserError("REFUSED: CLAIM_WINDOW_OVER")
        who = self._sender()
        t = json.loads(b.terms_json)
        if who in t["excluded_all"]:
            raise gl.vm.UserError("REFUSED: EXCLUDED_ADDRESS")
        k = str(int(b.bond_id)) + ":" + who
        if self.claims.get(k) is not None:
            raise gl.vm.UserError("REFUSED: ALREADY_CLAIMED")
        if int(b.denom) <= 0:
            raise gl.vm.UserError("REFUSED: NO_CLAIMABLE_SUPPLY")
        rb = int(b.rug_block)

        def leader() -> dict:
            return read_claim(t["chain"], t, who, rb)

        def validator(res: gl.vm.Result) -> bool:
            if not isinstance(res, gl.vm.Return) or not isinstance(res.calldata, dict):
                return False
            mine = read_claim(t["chain"], t, who, rb)
            if "reason" in res.calldata:
                return "reason" in mine
            return _canon(mine) == _canon(res.calldata)

        r = gl.vm.run_nondet(leader, validator)
        if not isinstance(r, dict) or "reason" in r or "balance" not in r:
            why = str(r.get("reason", "RPC_UNREADABLE")) if isinstance(r, dict) else "RPC_UNREADABLE"
            raise gl.vm.UserError("PENDING: " + why + "_TRY_AGAIN")
        if r.get("code") is not False:
            raise gl.vm.UserError("REFUSED: CONTRACT_HOLDER")
        if len(r.get("from_team", [])) > 0:
            raise gl.vm.UserError("REFUSED: RECEIVED_FROM_EXCLUDED_ADDRESS")
        bal = claim_balance(int(r["start_balance"]), int(r["balance"]))
        if bal <= 0:
            raise gl.vm.UserError("REFUSED: NO_BALANCE_AT_START_AND_R_MINUS_1")
        share = share_of(int(b.amount), bal, int(b.denom))
        dust = int(t["dust_floor"])
        if share <= 0 or share < dust:
            raise gl.vm.UserError("REFUSED: SHARE_BELOW_DUST_FLOOR")
        left = self._remaining(b)
        if share > left:
            share = left
        if share <= 0:
            raise gl.vm.UserError("REFUSED: NOTHING_LEFT")
        if int(self.balance) < share:
            raise gl.vm.UserError("REFUSED: CONTRACT_BALANCE_BELOW_SHARE")
        payee = self.beneficiary.get(k, "")
        if payee == "":
            payee = who
        # --- writes
        no = int(b.n_claims)
        self.claims[k] = Claim(bond_id=b.bond_id, holder=who, payee=payee, balance=u256(bal), share=u256(share),
                               claimed_at=u64(now), claim_no=u64(no))
        self.bond_claims[str(int(b.bond_id)) + ":" + str(no)] = who
        b.n_claims = u64(no + 1)
        b.paid = u256(int(b.paid) + share)
        hn = int(self.holder_n.get(who, u64(0)))
        self.holder_bonds[who + ":" + str(hn)] = b.bond_id
        self.holder_n[who] = u64(hn + 1)
        self.open_total = u256(int(self.open_total) - share)
        self.claims_paid_total = u256(int(self.claims_paid_total) + share)
        self._bump("claims")
        self._send(payee, share)
        return {"ok": True, "bond_id": int(b.bond_id), "holder": who, "payee": payee, "balance": str(bal),
                "start_balance": str(int(r["start_balance"])), "r_balance": str(int(r["balance"])),
                "share": str(share), "denominator": str(int(b.denom))}

    def _due(self, b: Bond, now: int) -> str:
        """What settle would do now: RETURN (to the team), VICTIM_FUND, or ""."""
        if b.status in (B_HELD, B_VOID):
            return "RETURN"
        if b.status == B_RUGGED and now > int(b.claim_deadline):
            return "VICTIM_FUND"
        if b.status == B_ACTIVE and now > int(b.recovery_deadline):
            return "VICTIM_FUND"
        return ""

    @gl.public.write
    def settle(self, bond_id: int) -> typing.Any:
        """Anyone: HELD or VOID -> the bond back to the team; RUGGED after the
        claim window -> what nobody claimed to the victim fund; ACTIVE after the
        recovery deadline -> UNRESOLVED, the bond to the victim fund."""
        now = self._now()
        if now <= 0:
            raise gl.vm.UserError("REFUSED: NO_CLOCK")
        b = self._bond(bond_id)
        if b is None:
            raise gl.vm.UserError("REFUSED: NO_SUCH_BOND")
        due = self._due(b, now)
        if due == "":
            if b.status == B_RUGGED:
                raise gl.vm.UserError("REFUSED: CLAIM_WINDOW_OPEN_UNTIL_" + str(int(b.claim_deadline)))
            if b.status == B_ACTIVE:
                raise gl.vm.UserError("REFUSED: ACTIVE_UNTIL_VERDICT_OR_" + str(int(b.recovery_deadline)))
            raise gl.vm.UserError("REFUSED: BOND_IS_" + b.status)
        t = json.loads(b.terms_json)
        left = self._remaining(b)
        if left > 0 and int(self.balance) < left:
            raise gl.vm.UserError("REFUSED: CONTRACT_BALANCE_BELOW_BOND")
        to = b.team if due == "RETURN" else t["victim_fund"]
        # --- writes
        if b.status == B_RUGGED:
            b.status = B_CLOSED
        elif b.status == B_ACTIVE:
            b.status = B_UNRESOLVED
        else:
            b.status = B_RETURNED
        b.settled_amount = u256(left)
        b.settled_to = to
        b.settled_at = u64(now)
        b.settled_by = self._sender()
        self.open_total = u256(int(self.open_total) - left)
        if due == "RETURN":
            self.returned_total = u256(int(self.returned_total) + left)
        else:
            self.victim_total = u256(int(self.victim_total) + left)
        self._bump("settles")
        if left > 0:
            self._send(to, left)
        return {"ok": True, "bond_id": int(b.bond_id), "status": b.status, "to": to, "amount": str(left)}

    @gl.public.write
    def withdraw_credit(self) -> typing.Any:
        """Value a refused create_bond credited back to the caller."""
        who = self._sender()
        amt = int(self.credits.get(who, u256(0)))
        if amt <= 0:
            raise gl.vm.UserError("REFUSED: NOTHING_TO_WITHDRAW")
        if int(self.balance) < amt:
            raise gl.vm.UserError("REFUSED: CONTRACT_BALANCE_BELOW_CREDIT")
        # --- writes
        self.credits[who] = u256(0)
        self.credit_owed_total = u256(int(self.credit_owed_total) - amt)
        self.credit_paid_total = u256(int(self.credit_paid_total) + amt)
        self._bump("credit_withdrawals")
        self._send(who, amt)
        return {"ok": True, "withdrawn": str(amt)}

    @gl.public.write
    def sweep_stray(self) -> typing.Any:
        """GEN in the balance above what the ledger holds arrived outside
        create_bond (the runtime keeps value sent with a failing or non-payable
        call). It belongs to no bond; anyone may send it to the deployer."""
        now = self._now()
        if now <= 0:
            raise gl.vm.UserError("REFUSED: NO_CLOCK")
        if now < int(self.last_send_at) + int(self.sweep_delay_s):
            raise gl.vm.UserError("REFUSED: SENDS_MAY_BE_PENDING_UNTIL_" +
                                  str(int(self.last_send_at) + int(self.sweep_delay_s)))
        stray = int(self.balance) - self._held()
        if stray <= 0:
            raise gl.vm.UserError("REFUSED: NO_STRAY_BALANCE")
        # --- writes
        self.stray_swept_total = u256(int(self.stray_swept_total) + stray)
        self._bump("sweeps")
        self._send(self.deployer, stray)
        return {"ok": True, "swept": str(stray), "to": self.deployer}

    # --- views (storage only; `now` is the caller's clock, used only for `due`) --

    def _bond_view(self, b: Bond, now: int) -> dict:
        t = json.loads(b.terms_json)
        return {"bond_id": int(b.bond_id), "team": b.team, "name": b.name, "chain": t["chain"], "token": t["token"],
                "pair": t["pair"], "lp_holders": t["lp_holders"], "min_lp": t["min_lp"],
                "start_block": int(t["start_block"]), "end_time": int(t["end_time"]),
                "claim_window_s": int(t["claim_window_s"]), "victim_fund": t["victim_fund"],
                "excluded": t["excluded"], "excluded_all": t["excluded_all"], "dust_floor": t["dust_floor"],
                "amount": str(int(b.amount)), "created_at": int(b.created_at),
                "recovery_deadline": int(b.recovery_deadline), "status": b.status, "cursor": int(b.cursor),
                "cursor_ts": int(b.cursor_ts), "scanned_at": int(b.scanned_at), "n_checks": int(b.n_checks),
                "n_pending": int(b.n_pending), "last_result": b.last_result, "last_reason": b.last_reason,
                "last_check_at": int(b.last_check_at), "pair_check": json.loads(b.pair_json),
                "start_ts": int(b.start_ts), "replay": bool(b.replay), "rug_block": int(b.rug_block),
                "rug_ts": int(b.rug_ts), "rug": json.loads(b.rug_json), "denominator": str(int(b.denom)),
                "rugged_at": int(b.rugged_at), "claim_deadline": int(b.claim_deadline), "paid": str(int(b.paid)),
                "n_claims": int(b.n_claims), "remaining": str(self._remaining(b)),
                "settled_amount": str(int(b.settled_amount)), "settled_to": b.settled_to,
                "settled_at": int(b.settled_at), "settled_by": b.settled_by, "verdict_at": int(b.verdict_at),
                "due": self._due(b, now) if now > 0 else "",
                "checkable": b.status == B_ACTIVE and (now <= 0 or now <= int(b.recovery_deadline))}

    def _page(self, offset: typing.Any, limit: typing.Any) -> list:
        return [max(_as_int(offset, 0), 0), min(max(_as_int(limit, PAGE_MAX), 1), PAGE_MAX)]

    @gl.public.view
    def get_bond(self, bond_id: int, now: int) -> typing.Any:
        b = self._bond(bond_id)
        if b is None:
            return {"found": False, "bond_id": _as_int(bond_id, 0)}
        out = self._bond_view(b, _as_int(now, 0))
        out["found"] = True
        return out

    @gl.public.view
    def list_bonds(self, offset: int, limit: int, now: int) -> typing.Any:
        """Bonds offset+1 .. offset+limit (ids 1..n), oldest first."""
        pg = self._page(offset, limit)
        n = int(self.n_bonds)
        items = []
        i = pg[0] + 1
        while i <= n and len(items) < pg[1]:
            b = self.bonds.get(u64(i))
            if b is not None:
                items.append(self._bond_view(b, _as_int(now, 0)))
            i += 1
        return {"total": n, "offset": pg[0], "limit": pg[1], "items": items,
                "next_offset": pg[0] + len(items) if pg[0] + len(items) < n else -1}

    def _index_page(self, ids_key: str, n: int, pg: list, now: int) -> dict:
        items = []
        i = pg[0]
        while i < n and len(items) < pg[1]:
            bid = self.token_bonds.get(ids_key + ":" + str(i)) if ids_key.find(":0x") >= 0 \
                else self.team_bonds.get(ids_key + ":" + str(i))
            b = self.bonds.get(bid) if bid is not None else None
            if b is not None:
                items.append(self._bond_view(b, now))
            i += 1
        return {"total": n, "offset": pg[0], "limit": pg[1], "items": items,
                "next_offset": pg[0] + pg[1] if pg[0] + pg[1] < n else -1}

    @gl.public.view
    def bonds_by_token(self, chain: str, token: str, offset: int, limit: int, now: int) -> typing.Any:
        k = str(chain).strip().lower() + ":" + _addr(token)
        return self._index_page(k, int(self.token_n.get(k, u64(0))), self._page(offset, limit), _as_int(now, 0))

    @gl.public.view
    def bonds_by_team(self, team: str, offset: int, limit: int, now: int) -> typing.Any:
        k = _addr(team)
        return self._index_page(k, int(self.team_n.get(k, u64(0))), self._page(offset, limit), _as_int(now, 0))

    def _check_view(self, c: Check) -> dict:
        return {"check_id": int(c.check_id), "bond_id": int(c.bond_id), "by": c.by, "at": int(c.at),
                "result": c.result, "reason": c.reason, "detail": c.detail, "a": int(c.a), "b": int(c.b),
                "n_logs": int(c.n_logs), "probes": json.loads(c.probes_json), "logs": json.loads(c.logs_json)}

    @gl.public.view
    def list_checks(self, bond_id: int, offset: int, limit: int) -> typing.Any:
        b = self._bond(bond_id)
        pg = self._page(offset, limit)
        n = int(b.n_checks) if b is not None else 0
        items = []
        i = pg[0]
        while i < n and len(items) < pg[1]:
            cid = self.bond_checks.get(str(int(b.bond_id)) + ":" + str(i))
            c = self.checks.get(cid) if cid is not None else None
            if c is not None:
                items.append(self._check_view(c))
            i += 1
        return {"bond_id": _as_int(bond_id, 0), "total": n, "offset": pg[0], "limit": pg[1], "items": items,
                "next_offset": pg[0] + pg[1] if pg[0] + pg[1] < n else -1}

    @gl.public.view
    def get_check(self, check_id: int) -> typing.Any:
        c = self.checks.get(u64(max(_as_int(check_id, 0), 0)))
        if c is None:
            return {"found": False}
        out = self._check_view(c)
        out["found"] = True
        return out

    def _claim_view(self, c: Claim) -> dict:
        return {"bond_id": int(c.bond_id), "holder": c.holder, "payee": c.payee, "balance": str(int(c.balance)),
                "share": str(int(c.share)), "claimed_at": int(c.claimed_at), "claim_no": int(c.claim_no)}

    @gl.public.view
    def list_claims(self, bond_id: int, offset: int, limit: int) -> typing.Any:
        b = self._bond(bond_id)
        pg = self._page(offset, limit)
        n = int(b.n_claims) if b is not None else 0
        items = []
        i = pg[0]
        while i < n and len(items) < pg[1]:
            h = self.bond_claims.get(str(int(b.bond_id)) + ":" + str(i))
            c = self.claims.get(str(int(b.bond_id)) + ":" + h) if h is not None else None
            if c is not None:
                items.append(self._claim_view(c))
            i += 1
        return {"bond_id": _as_int(bond_id, 0), "total": n, "offset": pg[0], "limit": pg[1], "items": items,
                "next_offset": pg[0] + pg[1] if pg[0] + pg[1] < n else -1}

    @gl.public.view
    def get_claim(self, bond_id: int, holder: str) -> typing.Any:
        k = str(_as_int(bond_id, 0)) + ":" + _addr(holder)
        c = self.claims.get(k)
        out = {"found": c is not None, "bond_id": _as_int(bond_id, 0), "holder": _addr(holder),
               "beneficiary": self.beneficiary.get(k, "")}
        if c is not None:
            out.update(self._claim_view(c))
        return out

    @gl.public.view
    def holder_claims(self, holder: str, offset: int, limit: int) -> typing.Any:
        h = _addr(holder)
        pg = self._page(offset, limit)
        n = int(self.holder_n.get(h, u64(0)))
        items = []
        i = pg[0]
        while i < n and len(items) < pg[1]:
            bid = self.holder_bonds.get(h + ":" + str(i))
            c = self.claims.get(str(int(bid)) + ":" + h) if bid is not None else None
            if c is not None:
                items.append(self._claim_view(c))
            i += 1
        return {"holder": h, "total": n, "offset": pg[0], "limit": pg[1], "items": items,
                "next_offset": pg[0] + pg[1] if pg[0] + pg[1] < n else -1}

    @gl.public.view
    def get_credit(self, who: str) -> typing.Any:
        return {"address": _addr(who), "credit": str(int(self.credits.get(_addr(who), u256(0))))}

    @gl.public.view
    def get_config(self) -> typing.Any:
        return {"version": VERSION, "contract": "RugBond", "mode": self.mode, "deployer": self.deployer,
                "chains_allowed": list(MODES[self.mode][0]), "min_claim_window_s": int(self.min_claim_window_s),
                "max_claim_window_s": MAX_CLAIM_WINDOW_S, "recovery_s": int(self.recovery_s),
                "stale_s": int(self.stale_s), "sweep_delay_s": int(self.sweep_delay_s),
                "last_send_at": int(self.last_send_at), "max_period_s": MAX_PERIOD_S, "min_bond": str(MIN_BOND),
                "max_holders": MAX_HOLDERS, "max_excluded": MAX_EXCLUDED, "max_probes": MAX_PROBES,
                "replay_grace_s": REPLAY_GRACE_S, "page_max": PAGE_MAX, "statuses": list(STATUSES),
                "chains": {k: {"chain_id": CHAINS[k][0], "log_rpcs": list(CHAINS[k][1]), "blocks_per_check": CHAINS[k][2],
                               "state_rpcs": list(CHAINS[k][3]),
                               "rpc_limits": {u: {"log_window": RPC_LIMITS[u][0], "batch": RPC_LIMITS[u][1],
                                                  "range_past_head": RPC_LIMITS[u][2]}
                                              for u in CHAINS[k][1] + CHAINS[k][3]},
                               "factories": FACTORIES.get(k, {})} for k in CHAINS}}

    @gl.public.view
    def get_stats(self) -> typing.Any:
        c = {}
        for k in COUNT_KEYS:
            c[k] = int(self.counts.get(k, u64(0)))
        return {"bonds": int(self.n_bonds), "checks": int(self.n_checks), "counts": c,
                "received_total": str(int(self.received_total)), "open_total": str(int(self.open_total)),
                "claims_paid_total": str(int(self.claims_paid_total)), "returned_total": str(int(self.returned_total)),
                "victim_total": str(int(self.victim_total)), "credit_owed_total": str(int(self.credit_owed_total)),
                "credit_paid_total": str(int(self.credit_paid_total)),
                "stray_swept_total": str(int(self.stray_swept_total)), "held": str(self._held()),
                "balance": str(int(self.balance))}
