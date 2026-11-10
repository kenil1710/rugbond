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
#   RUGGED_CLOSED      RUGGED after the claim window, or CLOSED
#   PENDING            anything else: no read yet, the last check PENDING, stale
#                      reads, no clock, UNRESOLVED, an unreadable registry
#
# `safe` is true only for ACTIVE_HELD_SO_FAR: a live promise read recently.
# Never favorable on missing, pending or stale data.

VERSION = "1.0.0"
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

# INLINE:common


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
    if st == "CLOSED":
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
                if not isinstance(nxt, int) or isinstance(nxt, bool) or nxt <= off:
                    break
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
