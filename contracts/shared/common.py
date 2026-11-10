# ==== shared helpers: contracts/shared/common.py, inlined by tools/build.py; edit there ====
# The runner rejects the str replace method; slice around find() instead.

# chain -> (chain id, (RPC A, RPC B), log window in blocks, windows per check, calls per JSON-RPC batch)
# Every read is made on BOTH RPCs of the chain and refused unless they answer
# identically. Each pair is run by two different operators and serves archive
# state (eth_call at old blocks) and eth_getLogs filtered by address and topic
# over the window, from GenVM with every validator reading at once
# (docs/FEASIBILITY.md). tools/lib/chains.mjs holds the same table.
CHAINS = {
    "ethereum": (1, ("https://gateway.tenderly.co/public/mainnet", "https://rpc.mevblocker.io"), 10000, 8, 12),
    "base": (8453, ("https://base.gateway.tenderly.co", "https://base.rpc.thirdweb.com"), 1000, 8, 3),
    "base-sepolia": (84532, ("https://base-sepolia.gateway.tenderly.co", "https://base-sepolia-rpc.publicnode.com"),
                     10000, 4, 12),
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
    start block on the first check), b = a + window * windows - 1, cut at the
    finalized head. a > b: nothing new is finalized."""
    ch = CHAINS[t["chain"]]
    a = cursor + 1 if cursor >= int(t["start_block"]) else int(t["start_block"])
    b = a + ch[2] * ch[3] - 1
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


def snapshot_denominator(supply: int, excluded: list) -> int:
    """totalSupply(R-1) minus the excluded addresses' balances at R-1 (never below 0)."""
    d = supply
    for e in excluded:
        d -= int(e[1])
    return d if d > 0 else 0
