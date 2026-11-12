# RugBond

[![ci](https://github.com/kenil1710/rugbond/actions/workflows/ci.yml/badge.svg)](https://github.com/kenil1710/rugbond/actions/workflows/ci.yml)
[![keeper](https://github.com/kenil1710/rugbond/actions/workflows/keeper.yml/badge.svg)](https://github.com/kenil1710/rugbond/actions/workflows/keeper.yml)

**A liquidity promise with GEN behind it.** A token team (or the launchpad that lists it) bonds GEN behind a frozen
promise: these LP wallets keep at least this much of the pool's LP until this time. GenLayer validators read the pool
from two RPCs. If the LP is pulled early, the bond is paid to the token's holders at the block before, pro rata: each
holder gets its own share and nothing more, what nobody claims goes to a fund fixed when the registry was deployed,
and the team never chooses where any of it goes. If the promise holds, the team gets its bond back. Code decides; nobody
approves anything.

Live: **https://rugbond.vercel.app** · Rules: [docs/RULES.md](docs/RULES.md) · Feasibility: [docs/FEASIBILITY.md](docs/FEASIBILITY.md) ·
Seeds: [docs/SEEDS.md](docs/SEEDS.md) · Demo: [docs/DEMO.md](docs/DEMO.md) · Real-world check: [docs/REAL_WORLD_CHECK.md](docs/REAL_WORLD_CHECK.md) ·
Attack round: [docs/ATTACK_REPORT.md](docs/ATTACK_REPORT.md) · Final check: [docs/FINAL_CHECK.md](docs/FINAL_CHECK.md)

## What and why

Most memecoin rugs are not clever: the address that minted the pool's LP removes it, minutes or hours after launch,
and the holders are left with tokens nobody can sell. "LP locked" badges are claims about an address; nothing pays
anyone when the claim turns out false. RugBond makes the promise expensive to break and cheap to check: the promise is
a few numbers frozen on GenLayer, the check is a read of public chain data that two RPCs must agree on, and the
payout follows from arithmetic.

## How the rules work

1. **The bond is frozen.** Chain, token, its Uniswap V2-style pair, the LP-holder addresses, the minimum LP they hold
   together, the start block, the end time, the claim window, excluded addresses, a dust floor, and the GEN posted.
   No cancel, no amendment. A bond never says where unclaimed GEN goes: the team has no say in that.
2. **Rug checks read forward.** Anyone files a check. Each bond stores a cursor, a span and a lower bound of the
   holders' LP; validators read the next stretch of finalized blocks from them: every LP Transfer out of an LP holder,
   and the holders' summed LP balance at each block those transfers could have taken below the promise, from two log
   RPCs and two state RPCs run by different operators. **RUGGED** at the first block where the sum is below the floor
   (before the end time); **HELD** once the reads pass the end time without one. Any number of transfers out is worked
   through across checks. A read error or a disagreement is **PENDING**: never a verdict, retried by anyone.
3. **Validators do not take the leader's word.** Each derives the block range from the contract's storage and reads
   it itself. A leader's "could not read" is accepted only when the validator's own read of that range fails too.
4. **Holders claim themselves.** After RUGGED each holder claims once, with the same key that holds the tokens:
   `share = bond × eligible ÷ (totalSupply(R-1) − excluded balances)`, where
   `eligible = max(0, min(balance at the start block, balance at R-1) − tokens the team sent the holder after the start)`,
   read from two RPCs. Supply bought after the bond opened earns nothing; tokens the team hands over earn nothing; a
   zero-value or dust transfer from the team costs a holder exactly what it carried, so nobody can be dusted out of a
   claim. Contracts and excluded addresses cannot claim; a beneficiary can be committed once.
5. **Every GEN has an exit, and none of them is chosen by the team.** A claimant receives its own share only,
   however few holders claim. After the claim window one `settle` sends everything nobody claimed to the registry's
   fund: one address per registry, set in its constructor, written by no method. A rugged bond nobody claimed and a
   bond no check has moved for a whole recovery window go the same way. HELD returns the bond to the team.
6. **LaunchGate** answers other contracts per bond: NO_BOND, ACTIVE_HELD_SO_FAR, HELD_FINAL, RUGGED_PAYING,
   RUGGED_CLOSED, PENDING; bound to a bond id or to the team that posted it; never favorable on missing, pending or
   stale data.

The exact rule, every reason code and every constant are in [docs/RULES.md](docs/RULES.md); the site's /docs page is
that file, and `test/test_meaning.py` checks it against the deployed bytes.

## Scope

RugBond reads one kind of rug: liquidity removed from a Uniswap V2-style pool (Uniswap V2 and SushiSwap pairs whose
factory maps the tokens back to the pair; Aerodrome-style volatile pools are supported by the read code) by the
addresses that promised to hold it. Other rug methods (hidden mints, blacklists, sell taxes, honeypots, V3/V4
positions) are outside the rule. The canonical registry covers Ethereum; the demo registry covers Base Sepolia. Base
mainnet rugs are in the feasibility study, read from this machine; from GenLayer Studio's validators only one public
endpoint serves Base eth_getLogs, and the rule needs two.

The canonical board's bonds are **historical replays**: bonds created now, with small symbolic GEN amounts, over
real rugs and real held liquidity from August 2026 ([docs/SEEDS.md](docs/SEEDS.md)). They show the rule on real
history; they are not promises the teams made. Each is marked `replay` on chain, and LaunchGate never answers
favorably for a replay. The demo registry runs a real token and a real Uniswap V2 pair on Base Sepolia, rugged and
held on purpose.

Turnout changes nobody's payout: a holder is paid bond x eligible / claimable supply whether one holder claims or
all of them, so a wallet that claims early in a short window gains nothing from the holders who stayed away. A
wallet that held the token at the start block claims its own share like any other, whoever is behind it; a
launchpad that knows a team's wallets lists them as excluded when the bond is created. On these testnet deployments
the registry's fund is a throwaway address; a production registry would be deployed with a public, jointly held
one.

The contracts pin GenLayer's current Python runner (`py-genlayer:babwp9t3…`, GenVM manager v0.6): Studio Dev now
rejects every older runner hash (`invalid_contract runner malformed`).

## Addresses (GenLayer Studio Dev, chain 61997)

| contract | address |
|---|---|
| RugBond (canonical, Ethereum) | `0x8295e5EE6dd5e74a2Ad4704B6025Ae4f2EcA1086` |
| RugBondDemo (Base Sepolia) | `0xFf72e30494D0026DE964870F04f4Fba84F3543CE` |
| LaunchGate (on RugBond) | `0xe2038e12BC5D16546EC54BEda14D11B8366ADab3` |
| LaunchGateDemo (on RugBondDemo) | `0xef1eCaC9d8f75de4Bea854c47112aE1757A046C7` |
| the registries' fund (constructor argument of both registries) | `0x9459cb7725ebcbdcda8c4fc679f495e45855c9a7` |

All four were deployed from commit `db54703f42c228a86ad36b77326b7b2037153688` ([deployments.json](deployments.json)); `node tools/verify_source.mjs`
proves the code on chain is byte-identical to `build/` at that commit. Earlier deployments were replaced by later
fixes (the last column says what replaced them); their bonds were still checked and settled by the keeper until each
registry's balance was 0 ([docs/SEEDS.md](docs/SEEDS.md)):

| contract | address | deployed from | replaced by a deployment for |
|---|---|---|---|
| RugBond | `0x24ff68A1adc70B9EA9eEE518a5f912ce65eb2CAE` | ede6ade | claim rule: min(balance at start, at R-1) and received-from-team exclusion |
| RugBondDemo | `0xbaa8FD3ecdCef962A59cc71a335B81E0Cf9b5016` | ede6ade | claim rule: min(balance at start, at R-1) and received-from-team exclusion |
| LaunchGate | `0x58E6D16082fE2Cb0FB38F8e1Ea407e5dc72280FF` | ede6ade | claim rule: min(balance at start, at R-1) and received-from-team exclusion |
| LaunchGateDemo | `0x75089E0b8C9027bf43561431f93E38DeA3D71303` | ede6ade | claim rule: min(balance at start, at R-1) and received-from-team exclusion |
| RugBond | `0x07ED56951513d01B06f350476C4501015256aB2c` | 0c24fde | LaunchGate staleness on the demo chain (6 h) |
| RugBondDemo | `0x6dfF7cFEb1e4e13b7FAC28e0CDf7807a742b9dA6` | 0c24fde | LaunchGate staleness on the demo chain (6 h) |
| LaunchGate | `0x72e4B537b2e6d98745B4b852af9f1e1C388b3804` | 0c24fde | LaunchGate staleness on the demo chain (6 h) |
| LaunchGateDemo | `0x87cA26b544Cff0ba752f44EACe31013e55A3f82d` | 0c24fde | LaunchGate staleness on the demo chain (6 h) |
| RugBond | `0x4D2a5e250a419b1D1798E103F80A23aC5be59a23` | f28753d | C1-C3: team transfers subtracted, no team-chosen fund, stored span and bound, validators derive the range |
| RugBondDemo | `0x3491AAC81ec96B05B50B25AD9F8b3CAeE7fF51b8` | f28753d | C1-C3: team transfers subtracted, no team-chosen fund, stored span and bound, validators derive the range |
| LaunchGate | `0x526D2923C56281f0c95ef9A4a02d8a29E2752D28` | f28753d | C1-C3: team transfers subtracted, no team-chosen fund, stored span and bound, validators derive the range |
| LaunchGateDemo | `0x8317C4e1e8D76335f249d977FA855Cfbb431e5C9` | f28753d | C1-C3: team transfers subtracted, no team-chosen fund, stored span and bound, validators derive the range |
| RugBond | `0x42f22d3C3d782E678C0561217276be836cba93fb` | 9c8495e | R1: no redistribution (a claimant gets its own share only; unclaimed GEN to the registry's fund) |
| RugBondDemo | `0x40aB41033194DFA35aeF2e7b295eFe3AF6ab5715` | 9c8495e | R1: no redistribution (a claimant gets its own share only; unclaimed GEN to the registry's fund) |
| LaunchGate | `0xf079A5119a0997E9d6b47B83E52EF6F3EFF03821` | 9c8495e | R1: no redistribution (a claimant gets its own share only; unclaimed GEN to the registry's fund) |
| LaunchGateDemo | `0xf851bC4dd469CccdB384bcDb2a480eb1255e312B` | 9c8495e | R1: no redistribution (a claimant gets its own share only; unclaimed GEN to the registry's fund) |

## Verify it yourself

```sh
python3 tools/build.py --check          # build/ is contracts/ with the shared code inlined
sh test/run_offline.sh                  # contract, gate, attack, meaning tests + keeper tests
python -m pytest tests/direct           # GenLayer Direct Mode tests (pip install -r tests/direct/requirements.txt)
node tools/verify_source.mjs            # deployed bytes == build/ at the deploy commit
node tools/final_check.mjs              # the whole verification package
```

## End to end

`e2e/flow.e2e.js` (Playwright, a throwaway wallet saved before use) drives the live site, https://rugbond.vercel.app,
on the demo registry: a team rugs a real Uniswap V2 pair on Base Sepolia, the wallet runs rug checks from the bond
page until RUGGED, claims its share (the GEN arrives), is refused by the contract when it then commits a beneficiary,
posts its own bond on a pool that holds, checks it to HELD and settles it (the bond comes back). Screenshots, video,
trace and a summary are in [docs/e2e/](docs/e2e/).

## Layout

- `contracts/` RugBond and LaunchGate; `contracts/shared/` the rule and the RPC reads (inlined by `tools/build.py`)
- `tools/` feasibility, keeper, verification, real-world check; `tools/lib/rug.mjs` mirrors the contract's reads
- `test/` offline suite (stubbed GenVM), keeper tests, deploy / seed / demo scripts
- `tests/direct/` official Direct Mode tests; `e2e/` Playwright run on the demo; `frontend/` the site
