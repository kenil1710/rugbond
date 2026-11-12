"""RugBond in GenLayer's Direct Mode (genlayer-test): the deployed bytes
(build/RugBond.py) run on the official SDK; the two RPCs are mocked by body.
Covers RUGGED and HELD verdicts, claims, validator agreement and disagreement,
forged leader results, RPC failures and disagreement between the RPCs."""
import json

from conftest import FUND, GEN, HOLDERS, PAIR, RPC_A, RPC_B, RPC_C, START, TEAM, TOKEN, Chain, warp


def test_rug_is_detected_at_the_first_block(direct_vm, net, contract, bond):
    net.a.rug(START + 300)
    r = contract.check(bond)
    assert r["result"] == "RUGGED", r
    assert r["rug_block"] == START + 300
    b = contract.get_bond(bond, 0)
    assert b["status"] == "RUGGED" and b["denominator"] == str(40_000 * GEN)


def test_held_when_the_floor_holds_to_the_end(direct_vm, net, contract, bond):
    r = contract.check(bond)
    assert r["result"] == "HELD", r
    assert contract.get_bond(bond, 0)["status"] == "HELD"


def test_holder_claims_its_share(direct_vm, net, contract, bond):
    net.a.rug(START + 300)
    contract.check(bond)
    direct_vm.sender = bytes.fromhex(HOLDERS[0][2:])
    r = contract.claim(bond)
    assert r["share"] == str(GEN // 4), r


def test_validator_agrees_on_the_same_data(direct_vm, net, contract, bond):
    net.a.rug(START + 300)
    contract.check(bond)
    assert direct_vm.run_validator() is True


def test_validator_disagrees_when_its_rpcs_answer_differently(direct_vm, net, contract, bond):
    net.a.rug(START + 300)
    contract.check(bond)
    net.a.logs[0]["transactionHash"] = "0x" + "7" * 64
    assert direct_vm.run_validator() is False


def test_validator_rejects_a_forged_rug(direct_vm, net, contract, bond):
    contract.check(bond)
    stored = direct_vm._captured_validators[-1][0]
    forged = json.loads(json.dumps(stored))
    forged["facts"]["window"]["rug"] = {"block": START, "ts": 1, "txs": [], "lp_after": "0", "supply": "1",
                                        "lp_before": "1", "excluded": [], "denom": "1"}
    assert direct_vm.run_validator(leader_result=forged) is False


def test_validator_rejects_a_leader_claiming_unreadable(direct_vm, net, contract, bond):
    contract.check(bond)
    stored = direct_vm._captured_validators[-1][0]
    assert direct_vm.run_validator(leader_result={"reason": "RPC_UNREADABLE", "detail": "x", "range": stored["range"]}) is False


def test_validator_rejects_a_leader_error(direct_vm, net, contract, bond):
    contract.check(bond)
    assert direct_vm.run_validator(leader_error=Exception("boom")) is False


def test_rpc_down_is_pending(direct_vm, net, contract, bond):
    net.down.add(RPC_B)
    r = contract.check(bond)
    assert r["result"] == "PENDING" and r["reason"] == "RPC_UNREADABLE", r
    b = contract.get_bond(bond, 0)
    assert b["status"] == "ACTIVE" and b["cursor"] == 0 and b["n_pending"] == 1


def test_rpcs_disagree_is_pending(direct_vm, net, contract, bond):
    net.b = Chain()
    net.a.rug(START + 300)
    r = contract.check(bond)
    assert r["result"] == "PENDING" and r["reason"] == "RPC_DISAGREE", r


def test_http_429_is_pending(direct_vm, net, contract, bond):
    net.a.status = 429
    r = contract.check(bond)
    assert r["result"] == "PENDING", r


def test_pending_then_verdict(direct_vm, net, contract, bond):
    net.down.add(RPC_A)
    assert contract.check(bond)["result"] == "PENDING"
    net.down.clear()
    net.a.rug(START + 10)
    assert contract.check(bond)["result"] == "RUGGED"


def test_claim_refused_for_contract_holder(direct_vm, net, contract, bond):
    net.a.rug(START + 300)
    net.a.code[HOLDERS[1]] = "0x6001600155"
    contract.check(bond)
    direct_vm.sender = bytes.fromhex(HOLDERS[1][2:])
    with direct_vm.expect_revert("CONTRACT_HOLDER"):
        contract.claim(bond)


def test_double_claim_refused(direct_vm, net, contract, bond):
    net.a.rug(START + 300)
    contract.check(bond)
    direct_vm.sender = bytes.fromhex(HOLDERS[2][2:])
    contract.claim(bond)
    with direct_vm.expect_revert("ALREADY_CLAIMED"):
        contract.claim(bond)


def test_claim_rpc_disagreement_refused_pending(direct_vm, net, contract, bond):
    net.a.rug(START + 300)
    contract.check(bond)
    net.b = Chain()
    net.b.rug(START + 300)
    net.b.set("x", "y", 0, 0)
    net.b.bal[(net.b.supply and list(net.b.supply)[0], HOLDERS[3])] = [(0, 1)]
    direct_vm.sender = bytes.fromhex(HOLDERS[3][2:])
    with direct_vm.expect_revert("PENDING"):
        contract.claim(bond)


def test_nobody_claimed_goes_to_the_registry_fund(direct_vm, net, contract, bond):
    net.a.rug(START + 300)
    contract.check(bond)
    warp(direct_vm, "2026-10-03T04:11:00Z")
    r = contract.settle(bond)
    assert r["status"] == "CLOSED" and r["amount"] == str(GEN) and r["to"] == FUND, r
    assert contract.get_config()["fund"] == FUND


def test_unclaimed_goes_to_the_fund_and_claimants_get_no_bonus(direct_vm, net, contract, bond):
    net.a.rug(START + 300)
    contract.check(bond)
    for h in HOLDERS[:2]:
        direct_vm.sender = bytes.fromhex(h[2:])
        assert contract.claim(bond)["share"] == str(GEN // 4)
    warp(direct_vm, "2026-10-03T04:11:00Z")
    r = contract.settle(bond)
    assert r["status"] == "CLOSED" and r["to"] == FUND and r["amount"] == str(GEN // 2), r
    with direct_vm.expect_revert("BOND_IS_CLOSED"):
        contract.settle(bond)
    for h in HOLDERS[:2]:
        c = contract.get_claim(bond, h)
        assert c["share"] == str(GEN // 4) and "bonus" not in c, c
    b = contract.get_bond(bond, 0)
    assert b["remaining"] == "0" and "victim_fund" not in b and b["fund"] == FUND


def test_team_transfer_is_subtracted_not_disqualifying(direct_vm, net, contract, bond):
    net.a.rug(START + 300)
    net.a.token_transfer(START + 100, TEAM, HOLDERS[3], 2_500 * GEN)
    net.a.token_transfer(START + 120, TEAM, HOLDERS[3], 500 * GEN)
    contract.check(bond)
    direct_vm.sender = bytes.fromhex(HOLDERS[3][2:])
    r = contract.claim(bond)
    assert r["from_team"] == str(3_000 * GEN) and r["balance"] == str(7_000 * GEN), r
    assert r["share"] == str(GEN * 7_000 // 40_000)


def test_zero_value_and_dust_transfers_from_the_team_change_nothing(direct_vm, net, contract, bond):
    net.a.rug(START + 300)
    for h in HOLDERS:
        net.a.token_transfer(START + 100, TEAM, h, 0)
    net.a.token_transfer(START + 101, TEAM, HOLDERS[1], 1)
    contract.check(bond)
    direct_vm.sender = bytes.fromhex(HOLDERS[0][2:])
    assert contract.claim(bond)["share"] == str(GEN // 4)
    direct_vm.sender = bytes.fromhex(HOLDERS[1][2:])
    r = contract.claim(bond)
    assert r["from_team"] == "1" and int(r["share"]) == GEN * (10_000 * GEN - 1) // (40_000 * GEN), r


# --- C3: a validator derives the range itself; a leader's failure counts only if the validator's own read fails

def test_validator_rejects_pending_with_zero_range_when_readable(direct_vm, net, contract, bond):
    net.a.rug(START + 300)
    contract.check(bond)
    for forged in ({"reason": "RPC_UNREADABLE", "detail": "x", "range": [0, 0]},
                   {"reason": "RPC_DISAGREE", "detail": "x", "range": [0, 0]},
                   {"reason": "RPC_UNREADABLE", "detail": "x"},
                   {"reason": "RPC_UNREADABLE", "detail": "x", "range": [START, START]},
                   {"reason": "RPC_UNREADABLE", "detail": "x", "range": [10 ** 9, 10 ** 9 + 5]},
                   {"reason": "NOTHING_NEW", "detail": "x", "range": [0, 0]},
                   {"reason": "ANYTHING", "detail": "x", "range": [0, 0]}):
        assert direct_vm.run_validator(leader_result=forged) is False, forged


def test_validator_accepts_pending_in_a_genuine_outage(direct_vm, net, contract, bond):
    net.down.add(RPC_A)
    r = contract.check(bond)
    assert r["result"] == "PENDING", r
    assert direct_vm.run_validator() is True
    # the leader's range plays no part: the validator's own read of the range it derives fails
    assert direct_vm.run_validator(leader_result={"reason": "RPC_UNREADABLE", "detail": "x", "range": [0, 0]}) is True
    net.down.clear()
    assert direct_vm.run_validator() is False
    assert direct_vm.run_validator(leader_result={"reason": "RPC_UNREADABLE", "detail": "x", "range": [0, 0]}) is False


def test_validator_takes_the_last_block_only_inside_its_own_range(direct_vm, net, contract, bond):
    contract.check(bond)
    stored = direct_vm._captured_validators[-1][0]
    assert stored["range"] == [START, START + 3000]
    for b in (START + 3001, START + 3000 - 1801, START, 0, 10 ** 9):
        forged = json.loads(json.dumps(stored))
        forged["range"][1] = b
        assert direct_vm.run_validator(leader_result=forged) is False, b
    forged = json.loads(json.dumps(stored))
    forged["range"][0] = START + 1
    assert direct_vm.run_validator(leader_result=forged) is False
    assert direct_vm.run_validator(leader_result=stored) is True


def test_span_halves_on_pending(direct_vm, net, contract, bond):
    net.down.add(RPC_A)
    assert contract.check(bond)["span"] == 20000
    assert contract.check(bond)["span"] == 10000
    net.down.clear()
    assert contract.check(bond)["result"] == "HELD"


def test_claim_paid_on_the_lower_balance(direct_vm, net, contract, bond):
    net.a.rug(START + 300)
    net.a.set(TOKEN, HOLDERS[0], START + 50, 4_000 * GEN)        # sold 6000 after the start
    contract.check(bond)
    direct_vm.sender = bytes.fromhex(HOLDERS[0][2:])
    r = contract.claim(bond)
    assert r["balance"] == str(4_000 * GEN) and r["start_balance"] == str(10_000 * GEN), r
