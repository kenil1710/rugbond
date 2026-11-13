# Attack round

Every attack below was tried against the contracts (offline suite on the deployed bytes, `test/test_attacks.py`
and the other `test/test_*.py`), the keeper (`test/keeper.test.mjs`) or the meaning of what the site and LaunchGate
say (`test/test_meaning.py`, `test/test_gate.py`). Severity is what the attack would do if it worked. Every High and
Medium finding was fixed before the contracts were deployed; the test that pins the fix is named. Three findings of
a later strict review of the deployed code (C1, C2, C3 below) were fixed in commits `f956833` and `9c8495e`; the
Medium finding of the review after that (R1: redistribution paid turnout) was fixed in `3e56213` by removing
redistribution, and all four contracts were redeployed from `db54703f42c228a86ad36b77326b7b2037153688`. No High or
Medium finding is open.

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
| 16 | The team directs unclaimed GEN to itself (a second wallet named as the fund), or settle is redirected | High | **Fixed** (C2): see C2a below | a17, a17b, a18, a18b, a19, test_claims Unclaimed |
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
| C2a | **The team chose where unclaimed GEN went.** A bond named its victim fund; the only rule was "not the team", which a second wallet passes. UNRESOLVED bonds went to the same address | High | **Fixed.** `create_bond` has no destination argument and the terms have no such field. After the claim window everything nobody claimed goes to the registry's fund in one `settle` (the first fix redistributed it to the claimants; R1 below removed that). A rugged bond nobody claimed and an UNRESOLVED bond go the same way. The fund is an address set in the constructor, written by no method, and never a party to a bond (`TEAM_IS_REGISTRY_FUND`, `REGISTRY_FUND_IN_TERMS`) | `f956833` | test_attacks a17 (a team's second wallet cannot be named anywhere), a17b, a18, a18b (no path pays a team wallet); test_claims Unclaimed (no bonus at any turnout, rounding, nobody-claimed path, fund fixed at deployment); demo steps settle_A_unclaimed_to_fund to conservation_A, copycat_unresolved, nobody_claimed_E |
| C2b | **A flood of LP transfers out could stop the scan.** One check read 6 outflow blocks and the recovery deadline was fixed at creation: enough transfers out of an LP holder and the bond ran into the deadline unread | High | **Fixed.** Each bond stores a cursor, a span and a lower bound of the holders' LP. A check takes at most 400 transfers (whole blocks) and goes on from the cursor next time; transfers that cannot have broken the promise are cleared by the bound without a balance read; the span halves when a read fails (so a stretch with more logs than an endpoint returns is still read) and doubles on progress. The recovery deadline moves with every check that moves the cursor: it only ends a bond no check has moved for a whole window | `f956833` | test_scan Flood (1,200 dust transfers to HELD and to the rug after them, 1,000 large transfers out and back, 1,000 transfers in one block, an endpoint that refuses large answers, a slow keeper past the first deadline, no progress for a whole window is still UNRESOLVED); demo step held_B (1,100 real LP transfers on Base Sepolia) |
| C3 | **Validators trusted the leader's range.** A validator re-read the range the leader named. A leader answering "unreadable" with range [0, 0] made every validator's re-read fail too ("nothing new"), and the false PENDING was accepted | High | **Fixed.** The cursor, span and bound come from storage; a validator derives the range itself. For a leader's failure nothing the leader sent is used: the validator reads the range it derived and agrees only if its own read fails as well (and to "nothing new" only if it finds nothing new). For a leader's facts, the leader's last block is taken only inside the validator's own range | `f956833` | test_pending Consensus (PENDING with [0, 0], no range, nine wrong ranges, forged NOTHING_NEW, unknown reasons, facts together with a reason: rolled back and the next honest leader decides; genuine outage: PENDING accepted whatever range was sent; outage on one side only: not PENDING; last block accepted only inside the derived range); Direct Mode `test_validator_rejects_pending_with_zero_range_when_readable`, `test_validator_accepts_pending_in_a_genuine_outage`, `test_validator_takes_the_last_block_only_inside_its_own_range` |
| C4 | Found while fixing C1: **a claim reads the team's transfers to the claimant.** More dust transfers to one holder than an endpoint returns in one answer made that holder's claim unreadable | Medium | **Fixed.** The transfers are summed, not listed; a log window an endpoint refuses is split in two until it fits (at most 64 requests per log RPC) | `9c8495e` | test_claims ClaimLogFlood |

## Second strict review, after the fixes

What a strict reviewer found in the code as deployed from `9c8495e`.

| # | finding | severity | fix | commit | pinned by |
|---|---|---|---|---|---|
| R1 | **Redistribution paid turnout.** Unclaimed GEN was shared among the claimants (bonus = pool x share / claimed shares): the fewer holders claimed, the more each claimant got. A team holding part of the float in an unlisted wallet from before the start block, with the shortest claim window and an early claim, recovered more of its bond than its share of the float | Medium | **Fixed.** Redistribution is removed: no `pay_bonus`, no REDISTRIBUTING status, no bonus fields. A claimant receives bond x eligible / claimable supply and nothing else, at any turnout; one `settle` after the claim window sends everything nobody claimed to the registry's fund | `3e56213` | test_claims Unclaimed: low_turnout_gives_no_bonus, turnout_never_changes_a_share, team_pre_start_float_gets_only_its_own_share, nobody_claimed_whole_bond_to_the_fund, rounding_goes_to_the_fund, no_redistribution_in_the_code; Direct Mode test_unclaimed_goes_to_the_fund_and_claimants_get_no_bonus; demo steps settle_A_unclaimed_to_fund, no_bonus_A |
| R7 | **A comment in the deployed bytes called the leader slack "about an hour of blocks"** on both chains; on Base Sepolia (0.2 s blocks) 1,800 blocks are about six minutes | Low | **Fixed.** The comment states both figures; the constants are unchanged | `3e56213` | docs/RULES.md states the same figures (test_meaning DocsMatchCode checks the constants) |
| R9 | **The site showed a finalized transaction as canceled.** Its table of numeric transaction statuses was off by one against the SDK's, so a status read as the number 7 (finalized) was shown as a failure although the settle had been written and paid. Found by the end to end run on the live site | Low (display only) | **Fixed.** The status name is used when present and the numbers follow the SDK's table | `a796430` | the end to end run on the live site |

The other notes of that review (R2 to R6, R8) describe where the rule ends, not defects; they are listed with the
scope boundaries below.

## Third strict review, of the code deployed from `db54703`

The same review once more, on the registries without redistribution. **No High, Medium or Low finding.** What was
checked:

| question | answer | pinned by |
|---|---|---|
| Can turnout, an early claim or a short claim window pay any claimant more than bond x eligible / claimable supply? | No. `claim` computes one share from the stored bond amount and denominator and pays it once; no later payment to a claimant exists in the code | test_claims Unclaimed: low_turnout_gives_no_bonus, turnout_never_changes_a_share, no_redistribution_in_the_code; the demo's no_bonus_A |
| Can a team, a settler or a claimant choose where unclaimed GEN goes? | No. `settle` takes a bond id only and pays the team (HELD, VOID) or the fund stored by the constructor | test_claims Unclaimed: settler_cannot_redirect, fund_is_fixed_at_deployment, bad_fund_refused_at_deployment |
| Does every wei leave? | received = held + claims + returned + to the fund + credits paid + swept; rounding stays in the bond and goes to the fund with the rest | test_claims Conservation, Unclaimed.test_rounding_goes_to_the_fund; conservation_A and balance_zero_end in the demo |
| Is there a status with no exit after REDISTRIBUTING was removed? | No: ACTIVE, RUGGED, HELD and VOID each settle once into UNRESOLVED, CLOSED or RETURNED; LaunchGate reads an unknown status as PENDING, never as safe | test_claims Settle, test_gate |
| Do validators still take nothing from the leader? | Unchanged from C3: range, span and lower bound come from storage; a leader's failure is accepted only if the validator's own read fails | Direct Mode validator tests |

One observation from this round's demo, not a defect: the run was interrupted for hours (the machine driving it
slept, and Studio Dev stopped answering for a while), and two demo bonds whose liquidity was never pulled went
without a check for their whole recovery window (1 hour on the demo registry). They settled as UNRESOLVED to the
registry's fund, exactly as the rule says, and LaunchGate stopped calling their team safe by team. The demo records
it (docs/DEMO.md, `lapsed_D_7`; docs/e2e/summary.json, `lapsed`). It is the boundary R3 below, seen live.

## Scope boundaries

- **Wallets funded before the start block.** A wallet holding tokens at the start block is a holder like any other,
  whoever funded it, and is paid its own share and never more (turnout does not change a share). A launchpad that
  knows the team's wallets lists them as excluded at creation. Tokens that pass through an unlisted intermediary
  (team -> unlisted wallet -> claimant) are not traced beyond one hop; they still earn nothing unless the claimant
  also held that much at the start block.
- **The registry's fund is chosen once, by whoever deploys the registry** (R2). No team and no bond can change it;
  `get_config` publishes it. On these testnet deployments it is a throwaway address; a production registry would be
  deployed with a public, jointly held one.
- **A bond needs a check inside its recovery window** (R3). A bond whose cursor no check has moved for the whole
  window (7 days on the canonical registry) is UNRESOLVED and goes to the registry's fund: not to holders even if its
  liquidity was pulled, and not back to the team even if the promise held. Anyone can file a check, the team
  included, and the keeper files them hourly.
- **A claim is never paid on a guess** (R4). More team transfers to one holder in a single block than an endpoint
  returns leave that holder's claim PENDING, never a wrong share
  (`test_more_dust_in_one_block_than_an_endpoint_returns_is_pending_not_a_wrong_share`); it takes thousands of
  transfers to one holder in one block.
- **A block is scanned whole** (R5). A block with more than 400 LP transfers out is taken in one check, so that
  check's stored facts grow with the block, bounded by the chain's block gas limit
  (`test_1000_transfers_in_one_block_are_one_check`).
- **A leader may end a check short** (R6), by at most 300 blocks on Ethereum and 1,800 on Base Sepolia. That is
  progress only, never a verdict: the next check goes on from there.
- **The feasibility study compared GenVM's reads with the first read code** (R8). For the code now deployed,
  docs/SEEDS.md compares every check GenVM stored on the canonical registry with this machine's read of the same
  range.
- **Other rug methods** (hidden mints, blacklists, sell taxes, honeypots) are outside the rule: RugBond reads the
  liquidity promise only (README, Scope).
- **Base mainnet** is not a supported chain on the canonical registry: from Studio's validators only one public
  endpoint answers Base eth_getLogs (docs/FEASIBILITY.md), and the rule needs two.
