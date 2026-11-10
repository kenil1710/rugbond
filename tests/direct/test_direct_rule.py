"""RugBond in GenLayer's Direct Mode (genlayer-test): the deployed bytes
(build/RugBond.py) run on the official SDK; the two RPCs are mocked by body.
Covers RUGGED and HELD verdicts, claims, validator agreement and disagreement,
forged leader results, RPC failures and disagreement between the RPCs."""
import json

from conftest import GEN, HOLDERS, PAIR, RPC_A, RPC_B, RPC_C, START, TEAM, Chain, warp


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


def test_settle_after_window_to_victim_fund(direct_vm, net, contract, bond):
    net.a.rug(START + 300)
    contract.check(bond)
    warp(direct_vm, "2026-10-03T04:11:00Z")
    r = contract.settle(bond)
    assert r["status"] == "CLOSED" and r["amount"] == str(GEN), r
