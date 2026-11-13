# Submission

## One-liner

RugBond: a token team bonds GEN behind a frozen liquidity promise; if the LP is pulled early, code on GenLayer pays the bond to the holders.

(140 characters)

## Description

A team or launchpad posts GEN behind a frozen promise: these wallets keep at least this much of a Uniswap V2-style pool's LP until a set time. Validators read LP Transfer logs and balances from two log RPCs and two state RPCs that must agree; each validator derives the block range from contract state and accepts a failed read only if its own read fails too. The first block below the floor is the rug: holders claim bond x eligible / claimable supply, eligible = min(balance at start, at R-1) minus tokens the team sent them (dust costs only the dust). Each claimant gets its own share only, whatever the turnout; unclaimed GEN goes to a registry fund fixed at deployment, never chosen by a team. A held promise returns the bond. A flood of LP transfers is scanned across checks. Errors are PENDING, never a verdict. LaunchGate never answers favorably on stale data. Built on 23 real cases (17 rugs: 11 Ethereum, 6 Base; 6 held), 23/23 confirmed by chain signals; seeds are replays.

(984 characters)

## Review verification

Open https://rugbond.vercel.app/verify (on-chain code = build/ at one commit). Run sh test/run_offline.sh (404 tests) and pytest tests/direct (24). docs/DEMO.md: a real Base Sepolia rug, a dusting attempt, a 1,100-transfer flood, claims, refusals, unclaimed GEN to the fund, payouts checked at recipients, balance 0. docs/SEEDS.md: 17 replays settled. node tools/final_check.mjs: 12/12; docs/AUDIT.md: 14/14.

(408 characters)

## Counts

- real cases: 23 (17 rugs: 11 Ethereum, 6 Base; 6 held), all verdicts as expected
- checks GenVM stored on the canonical registry that this machine reads identically: 18/18
- feasibility study (first read code): GenVM reads identical to this machine's 39/39, claim reads 2/2
- real-world check: 23/23
- tests: offline 404, keeper 23, Direct Mode 24, Playwright e2e on the live site
- canonical replay bonds: 17, settled 17
- final check 12/12, audit 14/14

## Addresses (GenLayer Studio Dev, chain 61997)

- RugBond: `0x8295e5EE6dd5e74a2Ad4704B6025Ae4f2EcA1086`
- RugBondDemo: `0xFf72e30494D0026DE964870F04f4Fba84F3543CE`
- LaunchGate: `0xe2038e12BC5D16546EC54BEda14D11B8366ADab3`
- LaunchGateDemo: `0xef1eCaC9d8f75de4Bea854c47112aE1757A046C7`
- the registries' fund (constructor argument of both): `0x9459cb7725ebcbdcda8c4fc679f495e45855c9a7`

All four deployed from commit `db54703f42c228a86ad36b77326b7b2037153688`.

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
