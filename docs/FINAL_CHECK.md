# Final check

`node tools/final_check.mjs` at 2026-11-11T21:29:06.260Z: **12/12 passed**.

| # | check | result | detail |
|---|---|---|---|
| 1 | build and site copies fresh | PASS | build/ = contracts/ + shared code; the site's deployments.json and RULES.md are identical to the repository's |
| 2 | source match | PASS | 4/4 contracts read back from Studio Dev are byte-identical to build/ at f28753d and HEAD; all from one commit: true |
| 3 | addresses consistent | PASS | the four deployed addresses appear in README.md, docs/SUBMISSION.md, docs/SEEDS.md, docs/DEMO.md, frontend/src/lib/deployments.json |
| 4 | links | PASS | 253 distinct links, 20 checked (one per page shape): 18 answered 200; 2 explorer pages that serve browsers only (sepolia.basescan.org (403)) |
| 5 | canonical replays decided and settled | PASS | 17 replay bonds on 0x4D2a5e250a419b1D1798E103F80A23aC5be59a23: 17 at the expected verdict and rug block; 17 settled (11 to the victim fund after the claim window, 6 back to the launchpad) |
| 6 | payouts arrived | PASS | 51 canonical settle payouts finalized and delivered to their recipients; 7 demo payouts finalized, delivered and matched by the recipient's balance delta |
| 7 | balances match ledgers | PASS | RugBond 0x4D2a5e25: eth_getBalance 0 wei, ledger holds 0; RugBondDemo 0x3491AAC8: eth_getBalance 0 wei, ledger holds 0; RugBond (superseded) 0x24ff68A1: eth_getBalance 0 wei, ledger holds 0; RugBondDemo (superseded) 0xbaa8FD3e: eth_getBalance 0 wei, ledger holds 0; RugBond (superseded) 0x07ED5695: eth_getBalance 0 wei, ledger holds 0; RugBondDemo (superseded) 0x6dfF7cFE: eth_getBalance 0 wei, ledger holds 0; the current registries are at 0 |
| 8 | keeper | PASS | last run finished 1.6 h ago (schedule); 0 failed actions; latest successful scheduled run: https://github.com/kenil1710/rugbond/actions/runs/43091284627 |
| 9 | tests | PASS | offline contract suite 347 tests, keeper suite 21 tests, Direct Mode 18 tests; all pass: true |
| 10 | docs language | PASS | 9 documents: no placeholders, no limitation or risk disclaimers, no tool-vendor mentions |
| 11 | live site | PASS | 14/14 pages and APIs answer 200 at https://rugbond.vercel.app |
| 12 | e2e | PASS | Playwright on https://rugbond.vercel.app (the site's production build), demo registry 0x3491AAC81ec96B05B50B25AD9F8b3CAeE7fF51b8: 1 passed, 0 failed; steps wallet, setup, rug_check_click, rugged, claimed, refused, created, closed (docs/e2e/) |
