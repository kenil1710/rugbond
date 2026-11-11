# Submission

## One-liner

RugBond: a token team bonds GEN behind a frozen liquidity promise; if the LP is pulled early, code on GenLayer pays the bond to the holders.

(140 characters)

## Description

A team or launchpad posts GEN behind a frozen promise: these wallets keep at least this much of a Uniswap V2-style pool's LP until a set time. Validators read LP Transfer logs and balances from two log RPCs and two state RPCs that must agree. The first block below the floor is the rug: holders then claim bond x min(balance at start, at R-1) / claimable supply; tokens bought after the start or received from the team earn nothing; the rest goes to a victim fund after the window. A held promise returns the bond. Errors are PENDING, never a verdict. LaunchGate answers per bond or team, never favorably on stale data. Built on 23 real cases (17 rugs: 11 Ethereum, 6 Base; 6 held), 23/23 confirmed by independent chain signals; canonical seeds are replays created after the events.

(782 characters)

## Review verification

Open https://rugbond.vercel.app/verify (on-chain code = build/ at one commit). Run sh test/run_offline.sh (? tests) and pytest tests/direct (?). docs/DEMO.md: a real Base Sepolia rug, claims, refusals, payouts checked at recipients, registry balance 0. docs/SEEDS.md: 17 replay bonds settled. node tools/final_check.mjs: 0/0; docs/AUDIT.md: 0/14.

(346 characters)

## Counts

- real cases: 23 (17 rugs: 11 Ethereum, 6 Base; 6 held), all verdicts as expected
- GenVM reads identical to this machine's: 39/39, claim reads 2/2
- real-world check: 23/23
- tests: offline ?, keeper ?, Direct Mode ?, Playwright e2e on the live site
- canonical replay bonds: 17, settled 17
- final check 0/0, audit 0/14

## Addresses (GenLayer Studio Dev, chain 61997)

- RugBond: `0x4D2a5e250a419b1D1798E103F80A23aC5be59a23`
- RugBondDemo: `0x3491AAC81ec96B05B50B25AD9F8b3CAeE7fF51b8`
- LaunchGate: `0x526D2923C56281f0c95ef9A4a02d8a29E2752D28`
- LaunchGateDemo: `0x8317C4e1e8D76335f249d977FA855Cfbb431e5C9`

All four deployed from commit `f28753db96904dc172867cced068c641888ce864`.
