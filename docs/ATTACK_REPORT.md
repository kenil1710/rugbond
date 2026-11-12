# Attack round

Every attack below was tried against the contracts (offline suite on the deployed bytes, `test/test_attacks.py`
and the other `test/test_*.py`), the keeper (`test/keeper.test.mjs`) or the meaning of what the site and LaunchGate
say (`test/test_meaning.py`, `test/test_gate.py`). Severity is what the attack would do if it worked. Every High and
Medium finding was fixed before the contracts were deployed; the test that pins the fix is named. Three findings of
a later strict review of the deployed code (C1, C2, C3 below) were fixed in commits `f956833` and `9c8495e`, and all
four contracts were redeployed from `9c8495ebcd8d2d42843ee17d51ed0d6ca0afce46`.

| # | attack | severity | result | pinned by |
|---|---|---|---|---|
| 1 | Flash-held balance at R-1: borrow tokens and return them inside block R-1 | Medium | No effect: claims use the end-of-block balances at the start block and at R-1 | test_attacks a02 |
| 2 | A holder buys in R-1 (knowing the rug) | Medium | **Fixed**: paid on min(balance at the start block, balance at R-1), so a buy after the bond opened earns nothing | a01, test_claims bought_after_start_earns_nothing |
| 3 | Sybil splitting: one balance split over many wallets | Low | Pro rata: the split earns the same total (minus rounding); the dust floor stops dust wallets | a03, a04 |
| 4 | The team buys supply before the rug (the ETH it pays into the pool comes back with the LP it removes) and claims part of its own bond through fresh wallets | High | **Fixed**: claims use min(balance at the start block, balance at R-1), so supply bought after the bond opened earns nothing; and whatever a team sender (an excluded address other than the pair, the swap routers, 0x0, 0x...dEaD) sent a holder after the start block, up to R, is subtracted from what it is paid on (C1), read from two log RPCs | a05, a05b-a05h, test_claims TeamTransfers, Direct Mode team-transfer tests |
| 5 | The team adds exclusions after the fact, or amends terms | High | Impossible: no method changes terms; there is no cancel, top-up or amend | a06, test_create no_cancel_or_amend_method |
| 6 | Fake LP locker: LP moved to an unlisted "locker" | High | Caught: the move out of a listed holder breaks the floor at that block | a07 |
| 7 | A listed locker that releases the LP to the team | High | Caught: a listed holder's outflow is read like any other | a08 |
| 8 | LP moved to another listed team wallet | — | Still held (the floor is the listed holders' sum), as the rule says | a09 |
| 9 | Fake pair: an LP token whose balanceOf lies | High | VOID on the first check: the pair's factory must be listed and must map its tokens back to the pair | a10, a11, test_scan PairValidity |
| 10 | Rebasing token | Medium | The claim uses `balanceOf` at the start block and at R-1 (the lower one) and `totalSupply` at R-1, from two RPCs: a rebase up after the start does not raise a claim | a12 |
| 11 | Fee-on-transfer token | Low | Holders are paid on what they hold; fees sent to the token contract are excluded | a13 |
| 12 | Junk rug checks to grief or to extend windows | Medium | A check with nothing new is refused and records nothing; PENDING never extends the recovery deadline; only a check that moves the cursor does | a14, a15, test_pending pending_cannot_extend_recovery, test_scan Flood |
| 13 | Flooding the LP holders with outflows to slow the scan past the recovery deadline | Medium | **Fixed** (C2): see C2b below | test_scan Flood |
| 14 | Double claim, beneficiary switch after claiming | High | One claim per (bond, holder); a beneficiary is committed once and never after claiming | a16, test_claims Beneficiary |
| 15 | Someone else commits a beneficiary for a holder | High | Impossible: the commitment is keyed by msg.sender | test_claims someone_else_cannot_commit_for_holder |
| 16 | The team directs unclaimed GEN to itself (a second wallet named as the fund), or settle is redirected | High | **Fixed** (C2): see C2a below | a17, a17b, a18, a18b, a19, test_claims Redistribution |
| 17 | One RPC lies | High | Never a verdict: the two views must be identical (PENDING) | a20, test_pending RPC disagreement tests |
| 18 | A leader lies about a rug, hides one, claims "unreadable", or widens the range | High | Validators re-read and disagree; the transaction commits nothing. The forged "unreadable" with a range of its own choosing is C3 below | test_pending Consensus, Direct Mode tests |
| 19 | A contract holder claims | Medium | Refused (`CONTRACT_HOLDER`); EIP-7702 delegated EOAs (`0xef0100`+address) are EOAs and may claim | a21, test_claims eip7702 tests |
| 20 | Rug by sending LP to 0x0 instead of removing | High | Caught: an outflow like any other | a22 |
| 21 | Shares adding up past the bond (inconsistent snapshot) | High | Each share is capped by what is left | a25, test_claims Conservation |
| 22 | Claim for someone else's balance | High | The claimant is msg.sender; `claim` takes only the bond id | a26 |
| 23 | Copycat bond: the same token bonded by someone else, or a look-alike token | High | LaunchGate is bound: `check_for(token, bond_id)` answers NO_BOND for another token; `is_safe_for(token, team)` reads only that team's bonds | test_gate TeamBound |
| 24 | A team with more bonds than LaunchGate reads hides a rugged bond past the cap | Medium | **Fixed**: `is_safe_for` answers PENDING when the team has more bonds than it reads (it used to answer from the first 200) | test_gate team_with_more_bonds_than_the_gate_reads_is_pending |
| 25 | A replay (a promise made after the fact) used as a credential | Medium | LaunchGate answers NO_BOND for a replay that did not rug; a rugged replay is still reported | test_gate replay tests |
| 26 | Stale or missing reads shown as safe | High | `safe` only for a fresh agreed read of an ACTIVE bond whose last check was not PENDING; every other combination tested | test_meaning NeverFavorable |
| 27 | Keeper duplication: two keepers at once, a crash after submit, a stuck hash | Medium | Actions keyed by bond + cursor + checks so far; a stored hash is resumed, never resubmitted unless stale for 6 h; a second keeper sees the effect and submits nothing | keeper.test.mjs |
| 28 | Docs drifting from code | Medium | Every constant, RPC, state and reason in docs/RULES.md is checked against build/ | test_meaning DocsMatchCode |

## Strict review of the deployed code: C1, C2, C3

| # | finding | severity | fix | commit | pinned by |
|---|---|---|---|---|---|
| C1 | **Dusting holders out of their claims.** The rule refused any address that had received the token from a team sender after the start block. A team could send every holder a zero-value or 1 wei transfer and nobody could claim | High | **Fixed.** Nobody is disqualified for receiving. eligible = max(0, min(balance at the start block, balance at R-1) - the summed amount received from team senders after the start block up to R). A zero-value transfer subtracts nothing, dust subtracts the dust, a real team transfer subtracts itself, several are summed | `f956833` | test_claims TeamTransfers (zero-value dusting, small dust, real transfer subtracted, multiple transfers, transfer in the start block and in block R, routers and the pair are not team senders, one RPC hiding a transfer is PENDING); Direct Mode `test_team_transfer_is_subtracted_not_disqualifying`, `test_zero_value_and_dust_transfers_from_the_team_change_nothing`; demo steps claim_holder1/2/3 |
| C2a | **The team chose where unclaimed GEN went.** A bond named its victim fund; the only rule was "not the team", which a second wallet passes. UNRESOLVED bonds went to the same address | High | **Fixed.** `create_bond` has no destination argument and the terms have no such field. After the claim window the unclaimed part is redistributed pro rata to the holders who claimed: one round, exactly one `pay_bonus` per claim, a bonus is never redistributed again. Integer leftovers, a rugged bond nobody claimed and an UNRESOLVED bond go to the registry's fund: an address set in the constructor, written by no method, and never a party to a bond (`TEAM_IS_REGISTRY_FUND`, `REGISTRY_FUND_IN_TERMS`) | `f956833` | test_attacks a17 (a team's second wallet cannot be named anywhere), a17b, a18, a18b (no path pays a team wallet); test_claims Redistribution (math, rounding, order, once per claim, bounded by the number of claims, nobody-claimed path, fund fixed at deployment); keeper tests for the bonus round; demo steps settle_A_redistribute to conservation_A, copycat_unresolved, nobody_claimed_E |
| C2b | **A flood of LP transfers out could stop the scan.** One check read 6 outflow blocks and the recovery deadline was fixed at creation: enough transfers out of an LP holder and the bond ran into the deadline unread | High | **Fixed.** Each bond stores a cursor, a span and a lower bound of the holders' LP. A check takes at most 400 transfers (whole blocks) and goes on from the cursor next time; transfers that cannot have broken the promise are cleared by the bound without a balance read; the span halves when a read fails (so a stretch with more logs than an endpoint returns is still read) and doubles on progress. The recovery deadline moves with every check that moves the cursor: it only ends a bond no check has moved for a whole window | `f956833` | test_scan Flood (1,200 dust transfers to HELD and to the rug after them, 1,000 large transfers out and back, 1,000 transfers in one block, an endpoint that refuses large answers, a slow keeper past the first deadline, no progress for a whole window is still UNRESOLVED); demo step held_B (1,100 real LP transfers on Base Sepolia) |
| C3 | **Validators trusted the leader's range.** A validator re-read the range the leader named. A leader answering "unreadable" with range [0, 0] made every validator's re-read fail too ("nothing new"), and the false PENDING was accepted | High | **Fixed.** The cursor, span and bound come from storage; a validator derives the range itself. For a leader's failure nothing the leader sent is used: the validator reads the range it derived and agrees only if its own read fails as well (and to "nothing new" only if it finds nothing new). For a leader's facts, the leader's last block is taken only inside the validator's own range | `f956833` | test_pending Consensus (PENDING with [0, 0], no range, nine wrong ranges, forged NOTHING_NEW, unknown reasons, facts together with a reason: rolled back and the next honest leader decides; genuine outage: PENDING accepted whatever range was sent; outage on one side only: not PENDING; last block accepted only inside the derived range); Direct Mode `test_validator_rejects_pending_with_zero_range_when_readable`, `test_validator_accepts_pending_in_a_genuine_outage`, `test_validator_takes_the_last_block_only_inside_its_own_range` |
| C4 | Found while fixing C1: **a claim reads the team's transfers to the claimant.** More dust transfers to one holder than an endpoint returns in one answer made that holder's claim unreadable | Medium | **Fixed.** The transfers are summed, not listed; a log window an endpoint refuses is split in two until it fits (at most 64 requests per log RPC) | `9c8495e` | test_claims ClaimLogFlood |

## Second strict review, after the fixes

What a strict reviewer finds in the code as deployed from `9c8495e`. None of these moves GEN to a team wallet that
the rule does not already treat as a holder, and none produces a wrong verdict.

| # | finding | severity | status |
|---|---|---|---|
| R1 | **Redistribution pays turnout.** A claimant's bonus is pool x share / claimed shares: the fewer holders claim, the more each claimant gets. A wallet that held the token at the start block claims like any other, whoever is behind it (the boundary below), and with low turnout its take grows with everyone else's. A team that holds part of the float in an unlisted wallet from before the start, sets the shortest claim window and claims early recovers more of its bond than its share of the float | Medium | Follows from the redistribution rule itself. What narrows it today: the launchpad lists the team's wallets as excluded and sets the claim window; the minimum window is 1 hour on the canonical registry. Two changes would narrow it further, each a rule change and a redeploy: cap a bonus at the claimant's own share (the rest to the registry's fund), or raise the minimum claim window |
| R2 | **The registry's fund is its deployer's choice.** The team no longer chooses; whoever deploys a registry does, once | Low | On these testnet deployments it is a throwaway address. `get_config` publishes it; a production registry would be deployed with a public, jointly held address |
| R3 | **A bond nobody checks for a whole recovery window is UNRESOLVED**, even if its liquidity was pulled: the bond goes to the registry's fund, not to holders. The demo's copycat bond took this path | Low | Anyone can file a check; the keeper runs hourly; the window is 7 days on the canonical registry |
| R4 | **More team dust to one holder in a single block than an endpoint returns** leaves that holder's claim PENDING (never a wrong share) | Low | Pinned as PENDING by `test_more_dust_in_one_block_than_an_endpoint_returns_is_pending_not_a_wrong_share`; it takes thousands of transfers in one block per holder |
| R5 | **A block with more than 400 LP transfers is taken whole**, so that one check's stored facts grow with the block | Low | Bounded by the chain's block gas limit; pinned by `test_1000_transfers_in_one_block_are_one_check` |
| R6 | **A leader can end a check up to the slack short** (300 blocks on Ethereum, 1,800 on Base Sepolia) of what a validator would read | Low | Progress only, never a verdict: the next check goes on from there |
| R7 | **A comment in the deployed bytes calls the slack "about an hour of blocks".** Base Sepolia now produces a block every 0.2 s, so 1,800 blocks are about six minutes there. A round straddling a jump of the finalized head larger than that is not agreed and is run again | Low | docs/RULES.md states the measured figure; the constant is the rule |
| R8 | **The feasibility study's GenVM comparison (39/39) was made with the first read code** | Low | docs/SEEDS.md compares every check GenVM stored on the current registry with this machine's read of the same range |

## Scope boundaries

- **Wallets funded before the start block.** A wallet holding tokens at the start block is a holder like any other,
  whoever funded it; a launchpad that knows the team's wallets lists them as excluded at creation. Tokens that pass
  through an unlisted intermediary (team -> unlisted wallet -> claimant) are not traced beyond one hop; they still
  earn nothing unless the claimant also held that much at the start block.
- **Other rug methods** (hidden mints, blacklists, sell taxes, honeypots) are outside the rule: RugBond reads the
  liquidity promise only (README, Scope).
- **Base mainnet** is not a supported chain on the canonical registry: from Studio's validators only one public
  endpoint answers Base eth_getLogs (docs/FEASIBILITY.md), and the rule needs two.
