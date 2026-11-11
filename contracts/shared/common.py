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
