# Submission

## One-liner

RugBond: a token team bonds GEN behind a frozen liquidity promise; if the LP is pulled early, code on GenLayer pays the bond to the holders.

(140 characters)

## Description

A team or launchpad posts GEN behind a frozen promise: these wallets keep at least this much of a Uniswap V2-style pool's LP until a set time. Validators read LP Transfer logs and balances from two log RPCs and two state RPCs that must agree; each validator derives the block range from contract state and accepts a failed read only if its own read fails too. The first block below the floor is the rug: holders claim bond x eligible / claimable supply, eligible = min(balance at start, at R-1) minus tokens the team sent them (dust costs only the dust). Unclaimed GEN is shared pro rata among claimants; no team picks a destination (leftovers go to a fund fixed at deployment). A held promise returns the bond. A flood of LP transfers is scanned across checks. Errors are PENDING, never a verdict. LaunchGate never answers favorably on stale data. Built on 23 real cases (17 rugs: 11 Ethereum, 6 Base; 6 held), 23/23 confirmed by chain signals; seeds are replays.

(964 characters)

## Review verification

Open https://rugbond.vercel.app/verify (on-chain code = build/ at one commit). Run sh test/run_offline.sh (406 tests) and pytest tests/direct (24). docs/DEMO.md: a real Base Sepolia rug, a dusting attempt, a 1,100-transfer flood, claims, bonuses, refusals, payouts checked at recipients, balance 0. docs/SEEDS.md: 17 replays settled. node tools/final_check.mjs: 12/12; docs/AUDIT.md: 14/14.

(390 characters)

## Counts

- real cases: 23 (17 rugs: 11 Ethereum, 6 Base; 6 held), all verdicts as expected
- checks GenVM stored on the canonical registry that this machine reads identically: 19/19
- feasibility study (first read code): GenVM reads identical to this machine's 39/39, claim reads 2/2
- real-world check: 23/23
- tests: offline 406, keeper 26, Direct Mode 24, Playwright e2e on the live site
- canonical replay bonds: 17, settled 17
- final check 12/12, audit 14/14

## Addresses (GenLayer Studio Dev, chain 61997)

- RugBond: `0x42f22d3C3d782E678C0561217276be836cba93fb`
- RugBondDemo: `0x40aB41033194DFA35aeF2e7b295eFe3AF6ab5715`
- LaunchGate: `0xf079A5119a0997E9d6b47B83E52EF6F3EFF03821`
- LaunchGateDemo: `0xf851bC4dd469CccdB384bcDb2a480eb1255e312B`
- the registries' fund (constructor argument of both): `0x9459cb7725ebcbdcda8c4fc679f495e45855c9a7`

All four deployed from commit `9c8495ebcd8d2d42843ee17d51ed0d6ca0afce46`.

## Evidence

- https://github.com/kenil1710/rugbond/blob/main/docs/RULES.md
- https://github.com/kenil1710/rugbond/blob/main/docs/ATTACK_REPORT.md
- https://github.com/kenil1710/rugbond/blob/main/docs/AUDIT.md
- https://github.com/kenil1710/rugbond/blob/main/docs/FINAL_CHECK.md
- https://github.com/kenil1710/rugbond/blob/main/docs/SEEDS.md
- https://github.com/kenil1710/rugbond/blob/main/docs/DEMO.md
- https://github.com/kenil1710/rugbond/blob/main/docs/FEASIBILITY.md
- https://github.com/kenil1710/rugbond/blob/main/docs/REAL_WORLD_CHECK.md
- https://github.com/kenil1710/rugbond/blob/main/docs/e2e/summary.json
- https://rugbond.vercel.app/verify
- https://github.com/kenil1710/rugbond/actions/workflows/ci.yml
- https://github.com/kenil1710/rugbond/actions/workflows/keeper.yml
