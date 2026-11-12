# RugBond rules

Every rule below is what `contracts/RugBond.py` and `contracts/LaunchGate.py` do (with the shared code in
`contracts/shared/common.py` and `contracts/shared/rpc.py`). The site's /docs page is this file;
`test/test_meaning.py` checks every constant and state name here against the deployed bytes in `build/`.

## 1. The bond

A team (or a launchpad) calls `create_bond` with GEN attached; the sender is the **team**. The terms are frozen at
creation; there is no cancel, no top-up and no amendment. A bond does not say where unclaimed GEN goes: the team
never chooses that (section 4).

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
| excluded | up to 24 extra addresses (routers, other team wallets); always excluded as well: the team, the pair, the token, every LP holder, 0x0 and 0x...dEaD |
| dust floor | a share below it is refused |

A refused `create_bond` never raises: the value is credited back to the sender (`withdraw_credit`). Reasons:
`NO_CLOCK`, `BOND_BELOW_MINIMUM`, `BOND_TOO_LARGE`, `NAME_REQUIRED`, `UNSUPPORTED_CHAIN`, `BAD_TOKEN_OR_PAIR`,
`TOKEN_IS_PAIR`, `LP_HOLDERS_*`, `LP_HOLDER_IS_PAIR_OR_TOKEN`, `MIN_LP_INVALID`, `START_BLOCK_INVALID`,
`END_TIME_INVALID`, `CLAIM_WINDOW_INVALID`, `EXCLUDED_*`, `TEAM_IS_REGISTRY_FUND`, `REGISTRY_FUND_IN_TERMS` (the
registry's fund is never a party to a bond: not its team, an LP holder, an excluded address, the token or the pair),
`DUST_FLOOR_INVALID`.

The **recovery deadline** starts at max(end time, creation time) + 7 days (canonical) or 1 hour (demo). Every check
that moves the cursor pushes it to that check's time + the same window, so it only ever ends a bond that no check
has moved for a whole window: PENDING checks never extend it, and a scan that is making progress never runs into it.

## 2. The rug check

Anyone calls `check(bond_id)`. Each bond stores a **cursor** (the last block read), a **span** (how many blocks the
next check may read) and a **lower bound** of the LP holders' summed balance at the cursor. A check reads blocks
[cursor + 1, cursor + span] (from the start block on the first check), cut at the lower of the two RPCs' `finalized`
heads. The span starts at 80,000 blocks on Ethereum, 40,000 on Base Sepolia. From **both** RPCs of the chain:

- every LP Transfer **out of** an LP holder (eth_getLogs on the pair, topic1 = any LP holder). At most 400 transfers
  per check: more, and the range is cut at a block boundary (a block is never split) and the next check goes on from
  there;
- the lower bound walks forward through those transfers: the holders' balances fall only through them, so after a
  block the bound is the bound before it minus what the block sent to non-holders. A block that leaves the bound at
  or above min LP cannot have broken the promise;
- the LP holders' summed `balanceOf` at the end of the start block (first check) and of each block the bound cannot
  clear, in block order, as many blocks as 48 balanceOf calls pay for (48 for one LP holder, 6 for eight). A balance
  read replaces the bound with the real balance. A block that is neither read nor cleared: the range is cut before
  it;
- the timestamp of the last block read;
- on the first check, `token0()`, `token1()`, `factory()` of the pair and the factory's own `getPair(token0, token1)`.

So any number of transfers out, dust or not, is worked through across checks; none is skipped.

**Who decides the range.** The cursor, the span and the bound come from the contract's storage. A validator derives
the range itself and takes from the leader only the last block, and only inside its own range: at or below its own
last block and at most a fixed number of blocks short of it (300 on Ethereum, 1,800 on Base Sepolia: about an hour
of Ethereum blocks and about six minutes of Base Sepolia's 0.2 s blocks; a leader's finalized head may trail). A
round in which the finalized head jumped further than that between the leader's read and a validator's is not
agreed and is simply run again. It then reads that range itself; the two RPCs must answer identically and its facts must
equal the leader's. When the leader says it **could not read** (`RPC_UNREADABLE`, `RPC_DISAGREE`), nothing the
leader sent is used: each validator reads the range it derived and agrees only if its own read fails too. A leader
that claims a failure while the chain is readable is outvoted and replaced.

- **RUGGED** if the summed balance was below min LP at the end of a block R between the start block and the end
  time. R is the first such block: the checks move forward block by block from the start, and within a check the
  blocks are read in order and the first below the floor is R. A floor broken before the start block means R = the
  start block. The rug check also stores R's timestamp, the transactions with LP transfers out in R, the LP balance
  before (R-1) and after (R), and the token snapshot at R-1: `totalSupply` and every excluded address's balance.
- **HELD** if the reads reach a block whose timestamp is at or after the end time with no such block (block
  timestamps strictly increase, so every block at or before the end time has been read), or the first such block's
  timestamp is after the end time.
- **SCANNED** otherwise: the cursor moves to the last block read, the span doubles (up to the chain's span) and the
  recovery deadline moves.
- **VOID** (first check) if the pair is not a pool of the token that a listed factory maps back to the pair:
  `NOT_A_PAIR`, `TOKEN_NOT_IN_PAIR`, `UNKNOWN_FACTORY`, `FACTORY_DOES_NOT_KNOW_PAIR`. Listed factories: Uniswap V2 and
  SushiSwap on Ethereum, the official Uniswap V2 factory on Base Sepolia.
- **PENDING** if a read fails or the RPCs disagree (`RPC_UNREADABLE`, `RPC_DISAGREE`, `MALFORMED_READ`): never a
  verdict. The cursor does not move; the counters do (`n_checks`, `n_pending`, the last result), and the span
  halves (never below one block), so a stretch with more transfers than an endpoint returns in one answer is still
  read, block by block if it must be. Anyone checks again.
- No new finalized block: refused (`NOTHING_NEW_FINALIZED`), nothing recorded.

Checks are refused after the recovery deadline (`RECOVERY_WINDOW_OVER_SETTLE_IT`) and on any bond that is not
ACTIVE. A bond whose start block's timestamp is more than 3600 s older than its creation is a **replay**.

## 3. Claims

After RUGGED, each token holder calls `claim(bond_id)` itself: the claimant is `msg.sender`, the same key that holds
the tokens on the bond's chain. Validators read, from both log RPCs and both state RPCs, the claimant's `balanceOf` at
the end of the bond's start block and at R-1, its code now, and the summed amount of every token Transfer **to** it
**from** a team sender after the start block, up to and including R.

    eligible = max(0, min(balanceOf(holder, start block), balanceOf(holder, R-1)) - received from team senders)
    share = bond * eligible // (totalSupply(R-1) - sum of excluded balances at R-1)

Integer math, rounded down; never more than what is left. Tokens bought after the bond opened earn nothing, a
holder that sold part of its position before R is paid on what it kept, and tokens the team handed over earn
nothing.

**Team senders** are every excluded address except the pair (buys come from the pair), 0x0 (mints), 0x...dEaD and the
chain's swap routers (Ethereum: Uniswap V2 Router02, SushiSwap router, Uniswap Universal Routers; Base Sepolia: Uniswap
V2 router and Universal Router). A transfer from a team sender takes away exactly the amount it carried and nothing
else: a zero-value transfer changes nothing, a dust transfer costs the dust, and nobody is disqualified for having
been sent something. The transfers are summed, not listed, so their number does not matter: a log window with
more of them than an endpoint returns in one answer is split in two until it fits (at most 64 eth_getLogs requests
per log RPC for one claim). The team therefore cannot wash its supply into a claim (a fresh wallet held nothing at the
start; an old holder topped up by the team loses the top-up), and it cannot knock holders out by sending them
tokens. A transfer in the start block itself is part of the start balance. A wallet the team funded before the
start block holds at the start like anyone else; a launchpad that knows such wallets lists them as excluded.

Refused: `EXCLUDED_ADDRESS`, `CONTRACT_HOLDER` (code at the address; an EIP-7702 delegation `0xef0100` + address is an
EOA and may claim), `NO_BALANCE_AT_START_AND_R_MINUS_1`, `NOTHING_ELIGIBLE_AFTER_TEAM_TRANSFERS`,
`SHARE_BELOW_DUST_FLOOR` (also a zero share), `ALREADY_CLAIMED`, `CLAIM_WINDOW_OVER`, `BOND_IS_<status>`,
`NO_CLAIMABLE_SUPPLY`. A read failure or disagreement is refused as `PENDING: ..._TRY_AGAIN` and nothing is recorded;
as in a rug check, a validator accepts a leader's failure only if its own read fails too.

The claim window opens when the RUGGED check is recorded and lasts the bond's claim window.

`commit_beneficiary(bond_id, address)`: a holder names, once, where its share goes; before it claims, while the bond
is ACTIVE or RUGGED. Without one, the share goes to the holder.

## 4. Settlement

No bond names a destination. A claimant receives its own share and nothing else, however few holders claim.
Everything nobody claimed goes to the **registry's fund**, one address per registry, set in the constructor and
written by no method (`get_config`).

Anyone calls `settle(bond_id)`:

| status | when | GEN goes to | new status |
|---|---|---|---|
| HELD or VOID | any time | the team (the whole bond) | RETURNED |
| RUGGED | after the claim window | the registry's fund (everything nobody claimed) | CLOSED |
| ACTIVE | after the recovery deadline | the registry's fund (the whole bond) | UNRESOLVED |

Turnout changes nobody's payout: with one claimant or with all of them, each is paid bond x eligible / claimable
supply. A wallet that claims early in a short window gains nothing from the holders who did not claim.

Every payout is one external value message to the recipient, posted in the call that records it; the caller funds
it. `withdraw_credit` returns refused values; `sweep_stray` sends GEN that arrived outside `create_bond` to the
deployer (only above what the ledger holds, and 48 h (canonical) / 1 h (demo) after the last payout).

Ledger: received = held + claims paid + returned + to the registry's fund + credits paid + swept;
held = open bond balances + credits owed. Counters move only after every check of the call has passed.

## 5. LaunchGate

Questions are bound: `check_for(token, bond_id)` reads exactly that bond; `is_safe_for(token, team)` reads only the
bonds that `team` itself posted for that token (the worst state wins). `safe` is true only for ACTIVE_HELD_SO_FAR.

| state | when |
|---|---|
| NO_BOND | no such bond, another token, a VOID bond, or a replay that did not rug |
| ACTIVE_HELD_SO_FAR | ACTIVE, at least one agreed read, the last check not PENDING, the last block read at most 6 h old (Base Sepolia's finalized head trails its tip by about 4.4 h) |
| HELD_FINAL | HELD or RETURNED |
| RUGGED_PAYING | RUGGED and the claim window open |
| RUGGED_CLOSED | RUGGED after the claim window (CLOSED) |
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
one more batch when there is a rug snapshot, a factory to ask or a shortened range. The range is cut at the lower of
the two log RPCs' finalized heads. Claims read the claimant's balance and code from the two state RPCs and the
transfers from team senders from the two log RPCs. Each request is retried up to
4 times on a transport error, a 429 or a 5xx.

## 7. Views

`get_bond`, `list_bonds`, `bonds_by_token`, `bonds_by_team`, `list_checks`, `get_check`, `list_claims`, `get_claim`,
`holder_claims`, `get_credit`, `get_config`, `get_stats`; every list is paginated (offset, limit at most 50,
`next_offset` = -1 at the end).
