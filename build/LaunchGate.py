# v0.3.0
# { "Depends": "py-genlayer:babwp9t37jw9g4j2bccgn14g6x7x9s1f7dsmh7emvz735pz4zxa0" }
import genlayer as gl
from genlayer import *
from dataclasses import dataclass
import json
import typing

# LaunchGate - what a consumer (a launchpad listing, a DEX front-end badge, a
# lending market accepting a token as collateral) asks before trusting a
# token's liquidity promise.
#
# Anyone can open a bond on the registry for any token, so every question is
# bound: check_for(token, bond_id) reads exactly that bond and answers NO_BOND
# unless its token is the named token; is_safe_for(token, team) reads only the
# bonds that `team` itself posted (the registry's team index) for that token.
# A copycat bond - the same token bonded by someone else, or a look-alike token
# - is never read.
#
#   NO_BOND            no such bond, another token, a VOID bond (its pair is not
#                      a pool of the token), or a replay that did not rug (its
#                      start block is older than the bond: a promise made after
#                      the fact proves nothing favorable)
#   ACTIVE_HELD_SO_FAR ACTIVE, at least one agreed read, the last check not
#                      PENDING, and the last block read is at most stale_s old
#   HELD_FINAL         the promise held to its end time (HELD or RETURNED)
#   RUGGED_PAYING      RUGGED, the claim window open
#   RUGGED_CLOSED      RUGGED after the claim window, REDISTRIBUTING or CLOSED
#   PENDING            anything else: no read yet, the last check PENDING, stale
#                      reads, no clock, UNRESOLVED, an unreadable registry
#
# `safe` is true only for ACTIVE_HELD_SO_FAR: a live promise read recently.
# Never favorable on missing, pending or stale data.

VERSION = "1.1.0"
G_NO_BOND = "NO_BOND"
G_ACTIVE = "ACTIVE_HELD_SO_FAR"
G_HELD = "HELD_FINAL"
G_PAYING = "RUGGED_PAYING"
G_CLOSED = "RUGGED_CLOSED"
G_PENDING = "PENDING"
GATE_STATES = (G_NO_BOND, G_ACTIVE, G_HELD, G_PAYING, G_CLOSED, G_PENDING)
# is_safe_for over several bonds of one team and token: the worst state wins
SEVERITY = (G_PAYING, G_CLOSED, G_PENDING, G_ACTIVE, G_HELD, G_NO_BOND)
PAGE_MAX = 50
MAX_TEAM_BONDS = 200

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
# so a router is never a "team" sender for the received-from-team rule (they
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
MAX_PROBE_CALLS = 48    # balanceOf calls one check spends on probes: probe_budget() blocks x the LP holders
MAX_LOGS = 400          # LP transfers one check takes in (whole blocks); the rest waits for the next check
# How far below min(the window's last block, a validator's own finalized head) a
# leader's last block may be: about an hour of blocks, for a leader whose
# finalized head trailed the validator's.
FIN_SLACK = {"ethereum": 300, "base-sepolia": 1800}
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

def scan_range(t: dict, cursor: int, fin: int, span: int) -> list:
    """The blocks one check reads: [a, b], a = the block after the bond's
    persisted cursor (the start block on the first check), b = a + the bond's
    persisted span - 1, cut at the finalized head. a > b: nothing new is
    finalized. Everything but the finalized head comes from contract state."""
    a = cursor + 1 if cursor >= int(t["start_block"]) else int(t["start_block"])
    b = a + span - 1
    if b > fin:
        b = fin
    return [a, b]


def probe_budget(n_holders: int) -> int:
    """Blocks whose summed LP balance one check reads."""
    n = MAX_PROBE_CALLS // (n_holders if n_holders > 0 else 1)
    return n if n > 1 else 2


def next_span(span: int, most: int, read_ok: bool) -> int:
    """The bond's span after a check: halved (never below one block) after a
    read that failed, so a stretch with more LP transfers than an endpoint
    returns in one answer is still read, block by block if it must be; doubled
    (up to the chain's span) after a read that moved the cursor."""
    if read_ok:
        n = span * 2
        return n if n < most else most
    n = span // 2
    return n if n > 1 else 1


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
    if int(facts.get("low", "-1")) < floor:
        # the lower bound carried to the next check must itself hold the floor
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


def bonus_of(pool: int, share: int, base: int) -> int:
    """A claimant's part of what nobody claimed: pool * its share // the sum of
    all claimed shares (integer math, rounded down)."""
    if pool <= 0 or share <= 0 or base <= 0:
        return 0
    x = (pool * share) // base
    return x if x < pool else pool


def team_senders(t: dict) -> list:
    """The addresses whose DIRECT token transfers to a claimant after the start
    block, up to R, are subtracted from its eligible balance: every excluded
    address except the pair (buys come from the pair), 0x0 (mints), 0x...dEaD
    and the chain's swap routers."""
    out = []
    for a in t["excluded_all"]:
        if a == t["pair"] or a == ZERO or a == DEAD or a in ROUTERS.get(t["chain"], ()):
            continue
        out.append(a)
    return sorted(out)


def claim_balance(start_balance: int, r_balance: int, from_team: int) -> int:
    """The balance a claim is paid on: the smaller of the holder's balance at the
    end of the bond's start block and at R-1, minus everything the holder
    received directly from team senders after the start block up to R, never
    below 0. Tokens bought after the bond opened earn nothing; tokens the team
    handed over earn nothing; a zero-value or dust transfer from the team takes
    away its own amount and nothing else."""
    m = start_balance if start_balance < r_balance else r_balance
    m -= from_team if from_team > 0 else 0
    return m if m > 0 else 0


def snapshot_denominator(supply: int, excluded: list) -> int:
    """totalSupply(R-1) minus the excluded addresses' balances at R-1 (never below 0)."""
    d = supply
    for e in excluded:
        d -= int(e[1])
    return d if d > 0 else 0


def _num(v: typing.Any) -> int:
    """A non-negative integer from a registry field (int or decimal string), or -1."""
    if isinstance(v, bool):
        return -1
    if isinstance(v, int):
        return v if v >= 0 else -1
    return _as_int(v, -1)


def _obj(raw: typing.Any) -> typing.Any:
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return None
    return raw


def gate_state(raw: typing.Any, token: str, now: int, stale_s: int) -> dict:
    """The registry's get_bond answer -> {state, safe, why, ...}. Pure."""
    out = {"state": G_PENDING, "safe": False, "why": "", "bond_id": 0, "token": token, "team": "",
           "status": "", "chain": "", "amount": "0", "cursor_ts": 0, "rug_block": 0, "claim_deadline": 0}
    v = _obj(raw)
    if token == "":
        out["state"] = G_NO_BOND
        out["why"] = "not a token address"
        return out
    if not isinstance(v, dict):
        out["why"] = "registry answer is not an object"
        return out
    if v.get("found") is not True:
        out["state"] = G_NO_BOND
        out["why"] = "no such bond"
        return out
    bid = _num(v.get("bond_id"))
    st = v.get("status")
    tok = _addr(v.get("token", ""))
    team = _addr(v.get("team", ""))
    cts = _num(v.get("cursor_ts"))
    ncheck = _num(v.get("n_checks"))
    cd = _num(v.get("claim_deadline"))
    if bid <= 0 or not isinstance(st, str) or tok == "" or team == "" or cts < 0 or ncheck < 0 or cd < 0 \
            or not isinstance(v.get("replay"), bool) or not isinstance(v.get("last_result"), str):
        out["why"] = "registry answer is malformed"
        return out
    out.update({"bond_id": bid, "team": team, "status": st, "chain": str(v.get("chain", "")),
                "amount": str(v.get("amount", "0")), "cursor_ts": cts, "rug_block": _num(v.get("rug_block")),
                "claim_deadline": cd})
    if tok != token:
        out["state"] = G_NO_BOND
        out["why"] = "the bond is for another token"
        return out
    if st == "VOID":
        out["state"] = G_NO_BOND
        out["why"] = "the bond's pair is not a pool of the token"
        return out
    if st in ("CLOSED", "REDISTRIBUTING"):
        out["state"] = G_CLOSED
        return out
    if st == "RUGGED":
        if now > 0 and now > cd:
            out["state"] = G_CLOSED
        else:
            out["state"] = G_PAYING
        return out
    if v.get("replay") is True:
        # a promise made after the fact proves nothing favorable (a rug is still reported above)
        out["state"] = G_NO_BOND
        out["why"] = "replay: the start block is older than the bond"
        return out
    if st in ("HELD", "RETURNED"):
        out["state"] = G_HELD
        return out
    if st != "ACTIVE":
        out["why"] = "status " + st
        return out
    if ncheck == 0 or cts == 0:
        out["why"] = "no agreed read yet"
        return out
    if v.get("last_result") == "PENDING":
        out["why"] = "the last check was PENDING"
        return out
    if now <= 0:
        out["why"] = "no clock"
        return out
    if now - cts > stale_s:
        out["why"] = "stale: the last block read is older than " + str(stale_s) + "s"
        return out
    out["state"] = G_ACTIVE
    out["safe"] = True
    return out


def worst(states: list) -> str:
    if len(states) == 0:
        return G_NO_BOND
    best = len(SEVERITY)
    for s in states:
        i = SEVERITY.index(s) if s in SEVERITY else 2
        if i < best:
            best = i
    return SEVERITY[best]


@gl.storage.allow
@dataclass
class Attestation:
    attestation_id: u64
    query: str
    token: str
    bond_id: u64
    team: str
    state: str
    safe: bool
    read_json: str
    attested_at: u64
    attested_by: str


class LaunchGate(gl.contract.Contract):
    registry: Address
    n_attest: u64
    attestations: gl.storage.TreeMap[u64, Attestation]

    def __init__(self, registry: str) -> None:
        r = _addr(registry)
        if r == "":
            raise gl.vm.UserError("registry must be an address")
        self.registry = Address(r)
        self.n_attest = u64(0)

    def _now(self) -> int:
        try:
            return _epoch_from_iso(gl.message.raw.get("datetime", ""))
        except Exception:
            return 0

    def _stale(self, reg: typing.Any) -> int:
        cfg = _obj(reg.get_config())
        s = _num(cfg.get("stale_s")) if isinstance(cfg, dict) else -1
        if s <= 0:
            raise gl.vm.UserError("stale_s unreadable")
        return s

    def _check(self, token: typing.Any, bond_id: typing.Any) -> dict:
        tok = _addr(token)
        bid = _as_int(bond_id, 0)
        now = self._now()
        try:
            reg = gl.contract.get_at(self.registry).view()
            stale = self._stale(reg)
            raw = reg.get_bond(bid, now) if bid > 0 else {"found": False}
        except Exception:
            out = gate_state(None, tok, now, 1)
            out["why"] = "registry unreadable"
            return out
        return gate_state(raw, tok, now, stale)

    def _team(self, token: typing.Any, team: typing.Any) -> dict:
        tok = _addr(token)
        tm = _addr(team)
        now = self._now()
        out = {"state": G_NO_BOND, "safe": False, "why": "", "token": tok, "team": tm, "bonds": []}
        if tok == "" or tm == "":
            out["why"] = "token and team must be addresses"
            return out
        try:
            reg = gl.contract.get_at(self.registry).view()
            stale = self._stale(reg)
            states = []
            off = 0
            while off >= 0 and off < MAX_TEAM_BONDS:
                pg = _obj(reg.bonds_by_team(tm, off, PAGE_MAX, now))
                if not isinstance(pg, dict) or not isinstance(pg.get("items"), list):
                    raise gl.vm.UserError("page")
                for it in pg["items"]:
                    if not isinstance(it, dict):
                        raise gl.vm.UserError("item")
                    if _addr(it.get("token", "")) != tok or _addr(it.get("team", "")) != tm:
                        continue
                    one = dict(it)
                    one["found"] = True
                    g = gate_state(one, tok, now, stale)
                    out["bonds"].append({"bond_id": g["bond_id"], "state": g["state"], "why": g["why"]})
                    if g["state"] != G_NO_BOND:
                        states.append(g["state"])
                nxt = pg.get("next_offset")
                if not isinstance(nxt, int) or isinstance(nxt, bool) or nxt < 0:
                    break
                if nxt <= off or nxt >= MAX_TEAM_BONDS:
                    # more bonds than the gate reads (or a malformed page): an unread one could be rugged
                    out["state"] = G_PENDING
                    out["why"] = "the team has more bonds than the gate reads"
                    return out
                off = nxt
        except Exception:
            out["state"] = G_PENDING
            out["why"] = "registry unreadable"
            out["bonds"] = []
            return out
        out["state"] = worst(states)
        out["safe"] = out["state"] == G_ACTIVE
        if len(states) == 0:
            out["why"] = "no bond of this team for this token"
        return out

    @gl.public.view
    def check_for(self, token: str, bond_id: int) -> typing.Any:
        """The named bond's state for the named token, read now."""
        return self._check(token, bond_id)

    @gl.public.view
    def is_safe_for(self, token: str, team: str) -> typing.Any:
        """Every bond `team` posted for `token`, the worst state among them; safe only if ACTIVE_HELD_SO_FAR."""
        return self._team(token, team)

    @gl.public.write
    def attest(self, token: str, bond_id: int) -> typing.Any:
        """Store check_for as read now (anyone; it only reads the registry)."""
        now = self._now()
        if now <= 0:
            raise gl.vm.UserError("REFUSED: NO_CLOCK")
        st = self._check(token, bond_id)
        return self._store("check_for", st, _addr(token), int(st["bond_id"]), str(st.get("team", "")), now)

    @gl.public.write
    def attest_team(self, token: str, team: str) -> typing.Any:
        now = self._now()
        if now <= 0:
            raise gl.vm.UserError("REFUSED: NO_CLOCK")
        st = self._team(token, team)
        return self._store("is_safe_for", st, _addr(token), 0, _addr(team), now)

    def _store(self, q: str, st: dict, tok: str, bid: int, team: str, now: int) -> dict:
        # --- writes
        aid = int(self.n_attest) + 1
        self.attestations[u64(aid)] = Attestation(attestation_id=u64(aid), query=q, token=tok, bond_id=u64(bid),
                                                  team=team, state=st["state"], safe=bool(st["safe"]),
                                                  read_json=_canon(st), attested_at=u64(now),
                                                  attested_by=gl.message.sender_address.as_hex.lower())
        self.n_attest = u64(aid)
        return {"ok": True, "attestation_id": aid, "state": st["state"], "safe": bool(st["safe"])}

    def _att_view(self, a: Attestation) -> dict:
        return {"attestation_id": int(a.attestation_id), "query": a.query, "token": a.token,
                "bond_id": int(a.bond_id), "team": a.team, "state": a.state, "safe": bool(a.safe),
                "read": json.loads(a.read_json), "attested_at": int(a.attested_at), "attested_by": a.attested_by}

    @gl.public.view
    def get_attestations(self, offset: int, limit: int) -> typing.Any:
        off = max(_as_int(offset, 0), 0)
        lim = min(max(_as_int(limit, PAGE_MAX), 1), PAGE_MAX)
        n = int(self.n_attest)
        items = []
        i = off + 1
        while i <= n and len(items) < lim:
            a = self.attestations.get(u64(i))
            if a is not None:
                items.append(self._att_view(a))
            i += 1
        return {"total": n, "offset": off, "limit": lim, "items": items,
                "next_offset": off + len(items) if off + len(items) < n else -1}

    @gl.public.view
    def get_config(self) -> typing.Any:
        return {"version": VERSION, "contract": "LaunchGate", "registry": self.registry.as_hex.lower(),
                "states": list(GATE_STATES), "severity": list(SEVERITY), "max_team_bonds": MAX_TEAM_BONDS,
                "binding": "check_for(token, bond_id) and is_safe_for(token, team)", "attestations": int(self.n_attest)}
