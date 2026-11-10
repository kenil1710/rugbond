# RugBond rules

Every rule below is what `contracts/RugBond.py` and `contracts/LaunchGate.py` do (with the shared code in
`contracts/shared/common.py` and `contracts/shared/rpc.py`). The site's /docs page is this file;
`test/test_meaning.py` checks every constant and state name here against the deployed bytes in `build/`.

## 1. The bond

A team (or a launchpad) calls `create_bond` with GEN attached; the sender is the **team**. The terms are frozen at
creation; there is no cancel, no top-up and no amendment.

| term | rule |
|---|---|
| chain | `ethereum` on the canonical registry, `base-sepolia` on the demo registry |
| token, pair | addresses, different from each other; the pair must be a Uniswap V2-style pool of the token (checked on the first rug check) |
| LP holders | 1 to 8 addresses (team wallets and/or lockers), not the pair or the token |
| min LP | the promised minimum LP amount the LP holders hold **together** (summed), > 0 |
| start block | > 0 |
| end time | unix seconds, at most 366 days after creation |
| bond | msg.value, at least 0.001 GEN |
| claim window | seconds; at least 3600 (canonical) or 60 (demo), at most 180 days |
| victim fund | receives what holders do not claim; never the team, an LP holder, an excluded address, zero or 0x...dEaD |
| excluded | up to 24 extra addresses (routers, other team wallets); always excluded as well: the team, the pair, the token, every LP holder, 0x0 and 0x...dEaD |
| dust floor | a share below it is refused |

A refused `create_bond` never raises: the value is credited back to the sender (`withdraw_credit`). Reasons:
`NO_CLOCK`, `BOND_BELOW_MINIMUM`, `BOND_TOO_LARGE`, `NAME_REQUIRED`, `UNSUPPORTED_CHAIN`, `BAD_TOKEN_OR_PAIR`,
`TOKEN_IS_PAIR`, `LP_HOLDERS_*`, `LP_HOLDER_IS_PAIR_OR_TOKEN`, `MIN_LP_INVALID`, `START_BLOCK_INVALID`,
`END_TIME_INVALID`, `CLAIM_WINDOW_INVALID`, `VICTIM_FUND_INVALID`, `VICTIM_FUND_IS_TEAM`, `VICTIM_FUND_IS_LP_HOLDER`,
`EXCLUDED_*`, `VICTIM_FUND_IS_EXCLUDED`, `DUST_FLOOR_INVALID`.

The **recovery deadline** is fixed at creation: max(end time, creation time) + 7 days (canonical) or 1 hour (demo).

## 2. The rug check

Anyone calls `check(bond_id)`. Each call reads the next stretch of finalized blocks, from the block after the
cursor (the start block on the first check): 80,000 blocks on Ethereum, 40,000 on Base Sepolia, cut at the lower of
the two RPCs' `finalized` heads. Every validator reads the same range from **both** RPCs of the chain:

- every LP Transfer **out of** an LP holder (eth_getLogs on the pair, topic1 = any LP holder);
- the LP holders' summed `balanceOf` at the end of the start block (first check) and of each block with such a
  transfer, in block order, at most 6 such blocks per check (more: the range is cut before the 7th);
- the timestamp of the last block read;
- on the first check, `token0()`, `token1()`, `factory()` of the pair and the factory's own `getPair(token0, token1)`.

The two RPCs must answer identically, and every validator must read what the leader read.

- **RUGGED** if the summed balance was below min LP at the end of a block R between the start block and the end
  time. R is the first such block: the checks move forward block by block from the start, and within a check the
  blocks are read in order and the first below the floor is R. A floor broken before the start block means R = the
  start block. The rug check also stores R's timestamp, the transactions with LP transfers out in R, the LP balance
  before (R-1) and after (R), and the token snapshot at R-1: `totalSupply` and every excluded address's balance.
- **HELD** if the reads reach a block whose timestamp is at or after the end time with no such block (block
  timestamps strictly increase, so every block at or before the end time has been read), or the first such block's
  timestamp is after the end time.
- **SCANNED** otherwise: the cursor moves to the last block read.
- **VOID** (first check) if the pair is not a pool of the token that a listed factory maps back to the pair:
  `NOT_A_PAIR`, `TOKEN_NOT_IN_PAIR`, `UNKNOWN_FACTORY`, `FACTORY_DOES_NOT_KNOW_PAIR`. Listed factories: Uniswap V2 and
  SushiSwap on Ethereum, the official Uniswap V2 factory on Base Sepolia.
- **PENDING** if a read fails or the RPCs disagree (`RPC_UNREADABLE`, `RPC_DISAGREE`, `MALFORMED_READ`): never a
  verdict. Nothing moves but the counters (`n_checks`, `n_pending`, the last result); anyone checks again.
- No new finalized block: refused (`NOTHING_NEW_FINALIZED`), nothing recorded.

Checks are refused after the recovery deadline (`RECOVERY_WINDOW_OVER_SETTLE_IT`) and on any bond that is not
ACTIVE. A bond whose start block's timestamp is more than 3600 s older than its creation is a **replay**.

## 3. Claims

After RUGGED, each token holder calls `claim(bond_id)` itself: the claimant is `msg.sender`, the same key that holds
the tokens on the bond's chain. Validators read, from both RPCs, the claimant's `balanceOf` at R-1 and its code now.

    share = bond * balanceOf(holder, R-1) // (totalSupply(R-1) - sum of excluded balances at R-1)

Integer math, rounded down; never more than what is left. Refused: `EXCLUDED_ADDRESS`, `CONTRACT_HOLDER` (code at the
address; an EIP-7702 delegation `0xef0100` + address is an EOA and may claim), `NO_BALANCE_AT_R_MINUS_1`,
`SHARE_BELOW_DUST_FLOOR` (also a zero share), `ALREADY_CLAIMED`, `CLAIM_WINDOW_OVER`, `BOND_IS_<status>`,
`NO_CLAIMABLE_SUPPLY`. A read failure or disagreement is refused as `PENDING: ..._TRY_AGAIN` and nothing is recorded.

The claim window opens when the RUGGED check is recorded and lasts the bond's claim window.

`commit_beneficiary(bond_id, address)`: a holder names, once, where its share goes; before it claims, while the bond
is ACTIVE or RUGGED. Without one, the share goes to the holder.

## 4. Settlement

Anyone calls `settle(bond_id)`:

| status | when | GEN goes to | new status |
|---|---|---|---|
| HELD or VOID | any time | the team (the whole bond) | RETURNED |
| RUGGED | after the claim window | the victim fund (everything not claimed) | CLOSED |
| ACTIVE | after the recovery deadline | the victim fund (the whole bond) | UNRESOLVED |

Every payout is one external value message to the recipient, posted in the call that records it; the caller funds
it. `withdraw_credit` returns refused values; `sweep_stray` sends GEN that arrived outside `create_bond` to the
deployer (only above what the ledger holds, and 48 h (canonical) / 1 h (demo) after the last payout).

Ledger: received = held + claims paid + returned + to victim funds + credits paid + swept; held = open bond balances
+ credits owed. Counters move only after every check of the call has passed.

## 5. LaunchGate

Questions are bound: `check_for(token, bond_id)` reads exactly that bond; `is_safe_for(token, team)` reads only the
bonds that `team` itself posted for that token (the worst state wins). `safe` is true only for ACTIVE_HELD_SO_FAR.

| state | when |
|---|---|
| NO_BOND | no such bond, another token, a VOID bond, or a replay that did not rug |
| ACTIVE_HELD_SO_FAR | ACTIVE, at least one agreed read, the last check not PENDING, the last block read at most 6 h (canonical) / 30 min (demo) old |
| HELD_FINAL | HELD or RETURNED |
| RUGGED_PAYING | RUGGED and the claim window open |
| RUGGED_CLOSED | RUGGED after the claim window, or CLOSED |
| PENDING | anything else: no read yet, the last check PENDING, stale reads, no clock, UNRESOLVED, an unreadable registry |

Never favorable on missing, pending or stale data. `attest` / `attest_team` store an answer on chain.

## 6. RPCs

Two RPCs run by different operators for each kind of read. View A is built from log RPC A and state RPC A, view B
from log RPC B and state RPC B; the two views must be identical.

| chain | log RPC A | log RPC B | state RPC A | state RPC B | blocks per check |
|---|---|---|---|---|---|
| ethereum | https://gateway.tenderly.co/public/mainnet | https://rpc.mevblocker.io | https://rpc.mevblocker.io | https://eth-mainnet.public.blastapi.io | 80,000 |
| base-sepolia | https://base-sepolia.gateway.tenderly.co | https://base-sepolia-rpc.publicnode.com | https://base-sepolia-rpc.publicnode.com | https://sepolia.base.org | 40,000 |

| endpoint | blocks per eth_getLogs request | calls per batch | log range past its head |
|---|---|---|---|
| https://gateway.tenderly.co/public/mainnet | 80,000 | 3 | accepted |
| https://rpc.mevblocker.io | 10,000 | 12 | accepted |
| https://eth-mainnet.public.blastapi.io | (state only) | 12 | accepted |
| https://base-sepolia.gateway.tenderly.co | 40,000 | 3 | refused: up to the finalized block |
| https://base-sepolia-rpc.publicnode.com | 40,000 | 12 | refused: up to the finalized block |
| https://sepolia.base.org | (state only) | 6 | refused: up to the finalized block |

A check asks each endpoint as few times as it can: one batch to each log RPC with the chain id, the finalized head
and the first log window; the remaining log windows; one batch of state (block headers, pair calls, balances); and
one more batch when there is a rug snapshot or a factory to ask. The range is cut at the lower of the two log RPCs'
finalized heads. Claims read the claimant's balance and code from the two state RPCs. Each request is retried up to
4 times on a transport error, a 429 or a 5xx.

## 7. Views

`get_bond`, `list_bonds`, `bonds_by_token`, `bonds_by_team`, `list_checks`, `get_check`, `list_claims`, `get_claim`,
`holder_claims`, `get_credit`, `get_config`, `get_stats`; every list is paginated (offset, limit at most 50,
`next_offset` = -1 at the end).
