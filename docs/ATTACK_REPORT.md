# Attack round

Every attack below was tried against the contracts (offline suite on the deployed bytes, `test/test_attacks.py`
and the other `test/test_*.py`), the keeper (`test/keeper.test.mjs`) or the meaning of what the site and LaunchGate
say (`test/test_meaning.py`, `test/test_gate.py`). Severity is what the attack would do if it worked. Every High and
Medium finding was fixed before the contracts were deployed; the test that pins the fix is named.

| # | attack | severity | result | pinned by |
|---|---|---|---|---|
| 1 | Flash-held balance at R-1: borrow tokens and return them inside block R-1 | Medium | No effect: claims use the end-of-block balances at the start block and at R-1 | test_attacks a02 |
| 2 | A holder buys in R-1 (knowing the rug) | Medium | **Fixed**: paid on min(balance at the start block, balance at R-1), so a buy after the bond opened earns nothing | a01, test_claims bought_after_start_earns_nothing |
| 3 | Sybil splitting: one balance split over many wallets | Low | Pro rata: the split earns the same total (minus rounding); the dust floor stops dust wallets | a03, a04 |
| 4 | The team buys supply before the rug (the ETH it pays into the pool comes back with the LP it removes) and claims part of its own bond through fresh wallets | High | **Fixed** (it was accepted by the first rule): claims use min(balance at the start block, balance at R-1), so supply bought after the bond opened earns nothing; and an address that received the token directly from a team sender (an excluded address other than the pair, the swap routers, 0x0, 0x...dEaD) between the start block and R cannot claim, read from two log RPCs. Wallets funded before the start block are holders at the start like anyone else; launchpads that know them list them as excluded | a05, a05b-a05h, test_claims, Direct Mode received-from-team and lower-balance tests |
| 5 | The team adds exclusions after the fact, or amends terms | High | Impossible: no method changes terms; there is no cancel, top-up or amend | a06, test_create no_cancel_or_amend_method |
| 6 | Fake LP locker: LP moved to an unlisted "locker" | High | Caught: the move out of a listed holder breaks the floor at that block | a07 |
| 7 | A listed locker that releases the LP to the team | High | Caught: a listed holder's outflow is read like any other | a08 |
| 8 | LP moved to another listed team wallet | — | Still held (the floor is the listed holders' sum), as the rule says | a09 |
| 9 | Fake pair: an LP token whose balanceOf lies | High | VOID on the first check: the pair's factory must be listed and must map its tokens back to the pair | a10, a11, test_scan PairValidity |
| 10 | Rebasing token | Medium | The claim uses `balanceOf` at the start block and at R-1 (the lower one) and `totalSupply` at R-1, from two RPCs: a rebase up after the start does not raise a claim | a12 |
| 11 | Fee-on-transfer token | Low | Holders are paid on what they hold; fees sent to the token contract are excluded | a13 |
| 12 | Junk rug checks to grief or to extend windows | Medium | A check with nothing new is refused and records nothing; the recovery deadline is fixed at creation; PENDING never extends it | a14, a15, test_pending pending_cannot_extend_recovery |
| 13 | Flooding the LP holders with tiny outflows to slow the scan past the recovery deadline | Medium | Each check reads 6 outflow blocks; a bond still unread at its recovery deadline goes to the victim fund, so the flood only hurts the team | a23, a24 |
| 14 | Double claim, beneficiary switch after claiming | High | One claim per (bond, holder); a beneficiary is committed once and never after claiming | a16, test_claims Beneficiary |
| 15 | Someone else commits a beneficiary for a holder | High | Impossible: the commitment is keyed by msg.sender | test_claims someone_else_cannot_commit_for_holder |
| 16 | Victim fund set to the team, or settle redirected | High | Refused at creation (`VICTIM_FUND_IS_TEAM`, also LP holders and excluded addresses); settle destinations are fixed | a17, a18, a19 |
| 17 | One RPC lies | High | Never a verdict: the two views must be identical (PENDING) | a20, test_pending RPC disagreement tests |
| 18 | A leader lies about a rug, hides one, claims "unreadable", or widens the range | High | Validators re-read and disagree; the transaction commits nothing | test_pending Consensus, Direct Mode tests |
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

## Documented

- **Wallets funded before the start block.** A wallet holding tokens at the start block is a holder like any other,
  whoever funded it; a launchpad that knows the team's wallets lists them as excluded at creation. Tokens that pass
  through an unlisted intermediary (team -> unlisted wallet -> claimant) are not traced beyond one hop.
- **Other rug methods** (hidden mints, blacklists, sell taxes, honeypots) are outside the rule: RugBond reads the
  liquidity promise only (README, Scope).
- **Base mainnet** is not a supported chain on the canonical registry: from Studio's validators only one public
  endpoint answers Base eth_getLogs (docs/FEASIBILITY.md), and the rule needs two.
