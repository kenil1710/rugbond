# RugBond

[![ci](https://github.com/kenil1710/rugbond/actions/workflows/ci.yml/badge.svg)](https://github.com/kenil1710/rugbond/actions/workflows/ci.yml)
[![keeper](https://github.com/kenil1710/rugbond/actions/workflows/keeper.yml/badge.svg)](https://github.com/kenil1710/rugbond/actions/workflows/keeper.yml)

**A liquidity promise with GEN behind it.** A token team (or the launchpad that lists it) bonds GEN behind a frozen
promise: these LP wallets keep at least this much of the pool's LP until this time. GenLayer validators read the pool
from two RPCs. If the LP is pulled early, the bond is paid to the token's holders at the block before, pro rata; what
they do not claim goes to a victim fund. If the promise holds, the team gets its bond back. Code decides; nobody
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
   together, the start block, the end time, the claim window, the victim fund (never the team), excluded addresses, a
   dust floor, and the GEN posted. No cancel, no amendment.
2. **Rug checks read forward.** Anyone files a check. Validators read the next stretch of finalized blocks: every LP
   Transfer out of an LP holder and the holders' summed LP balance at each such block, from two log RPCs and two state
   RPCs run by different operators. **RUGGED** at the first block where the sum is below the floor (before the end
   time); **HELD** once the reads pass the end time without one. A read error or a disagreement is **PENDING**: never a
   verdict, retried by anyone, bounded by a recovery deadline fixed at creation.
3. **Holders claim themselves.** After RUGGED each holder claims once, with the same key that holds the tokens:
   `share = bond × balanceOf(holder, R-1) ÷ (totalSupply(R-1) − excluded balances)`, read from two RPCs. Contracts and
   excluded addresses cannot claim; a beneficiary can be committed once.
4. **Every GEN has an exit.** After the claim window the rest goes to the victim fund; HELD returns the bond to the
   team; a bond never read to a verdict by its recovery deadline goes to the victim fund.
5. **LaunchGate** answers other contracts per bond: NO_BOND, ACTIVE_HELD_SO_FAR, HELD_FINAL, RUGGED_PAYING,
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

The contracts pin GenLayer's current Python runner (`py-genlayer:babwp9t3…`, GenVM manager v0.6): Studio Dev now
rejects every older runner hash (`invalid_contract runner malformed`).

## Addresses (GenLayer Studio Dev, chain 61997)

See [deployments.json](deployments.json); all four contracts are deployed from one commit and `node tools/verify_source.mjs`
proves the code on chain is byte-identical to `build/`.

## Verify it yourself

```sh
python3 tools/build.py --check          # build/ is contracts/ with the shared code inlined
sh test/run_offline.sh                  # contract, gate, attack, meaning tests + keeper tests
python -m pytest tests/direct           # GenLayer Direct Mode tests (pip install -r tests/direct/requirements.txt)
node tools/verify_source.mjs            # deployed bytes == build/ at the deploy commit
node tools/final_check.mjs              # the whole verification package
```

## Layout

- `contracts/` RugBond and LaunchGate; `contracts/shared/` the rule and the RPC reads (inlined by `tools/build.py`)
- `tools/` feasibility, keeper, verification, real-world check; `tools/lib/rug.mjs` mirrors the contract's reads
- `test/` offline suite (stubbed GenVM), keeper tests, deploy / seed / demo scripts
- `tests/direct/` official Direct Mode tests; `e2e/` Playwright run on the demo; `frontend/` the site
