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
#   share = bond * balanceOf(holder, R-1) // (totalSupply(R-1) - excluded balances at R-1)
#
# read from two archive RPCs that must agree. Contracts (code at the address)
# and excluded addresses cannot claim; a share below the dust floor is refused.
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
#                       than this is PENDING, never "held so far"
#   sweep_delay_s       sweep_stray waits this long after the last send
MODES = {
    "CANONICAL": (("ethereum", "base"), 3600, 7 * 86400, 6 * 3600, 172800),
    "DEMO": (("base-sepolia",), 60, 3600, 1800, 3600),
}
MAX_PERIOD_S = 366 * 86400      # end time at most this far after creation
MAX_CLAIM_WINDOW_S = 180 * 86400
MAX_NAME = 80
MIN_BOND = 10 ** 15             # 0.001 GEN
MAX_AMOUNT = 10 ** 30
MAX_UINT = (1 << 256) - 1
REPLAY_GRACE_S = 3600           # a start block older than creation by more than this marks a replay
PAGE_MAX = 50

# INLINE:common
# INLINE:rpc


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
        ch = t["chain"]
        tok = t["token"]
        rb = int(b.rug_block)

        def leader() -> dict:
            return read_holder(ch, tok, who, rb)

        def validator(res: gl.vm.Result) -> bool:
            if not isinstance(res, gl.vm.Return) or not isinstance(res.calldata, dict):
                return False
            mine = read_holder(ch, tok, who, rb)
            if "reason" in res.calldata:
                return "reason" in mine
            return _canon(mine) == _canon(res.calldata)

        r = gl.vm.run_nondet(leader, validator)
        if not isinstance(r, dict) or "reason" in r or "balance" not in r:
            why = str(r.get("reason", "RPC_UNREADABLE")) if isinstance(r, dict) else "RPC_UNREADABLE"
            raise gl.vm.UserError("PENDING: " + why + "_TRY_AGAIN")
        if r.get("code") is not False:
            raise gl.vm.UserError("REFUSED: CONTRACT_HOLDER")
        bal = int(r["balance"])
        if bal <= 0:
            raise gl.vm.UserError("REFUSED: NO_BALANCE_AT_R_MINUS_1")
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
                "chains": {k: {"chain_id": CHAINS[k][0], "rpcs": list(CHAINS[k][1]), "log_window": CHAINS[k][2],
                               "windows_per_check": CHAINS[k][3], "batch": CHAINS[k][4],
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
