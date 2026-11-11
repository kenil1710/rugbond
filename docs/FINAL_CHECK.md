# Final check

`node tools/final_check.mjs` at 2026-11-11T13:37:25.949Z: **11/12 passed**.

| # | check | result | detail |
|---|---|---|---|
| 1 | build and site copies fresh | PASS | build/ = contracts/ + shared code; the site's deployments.json and RULES.md are identical to the repository's |
| 2 | source match | PASS | 4/4 contracts read back from Studio Dev are byte-identical to build/ at f28753d and HEAD; all from one commit: true |
| 3 | addresses consistent | PASS | the four deployed addresses appear in README.md, docs/SUBMISSION.md, docs/SEEDS.md, docs/DEMO.md, frontend/src/lib/deployments.json |
| 4 | links | PASS | 236 distinct links, 19 checked (one per page shape): 12 answered 200; 7 explorer pages that serve browsers only (sepolia.basescan.org (403), basescan.org (403)) |
| 5 | canonical replays decided and settled | PASS | 17 replay bonds on 0x4D2a5e250a419b1D1798E103F80A23aC5be59a23: 17 at the expected verdict and rug block; 17 settled (11 to the victim fund after the claim window, 6 back to the launchpad) |
| 6 | payouts arrived | PASS | 51 canonical settle payouts finalized and delivered to their recipients; 7 demo payouts finalized, delivered and matched by the recipient's balance delta |
| 7 | balances match ledgers | PASS | RugBond 0x4D2a5e25: eth_getBalance 0 wei, ledger holds 0; RugBondDemo 0x3491AAC8: eth_getBalance 0 wei, ledger holds 0; RugBond (superseded) 0x24ff68A1: eth_getBalance 0 wei, ledger holds 0; RugBondDemo (superseded) 0xbaa8FD3e: eth_getBalance 0 wei, ledger holds 0; RugBond (superseded) 0x07ED5695: eth_getBalance 0 wei, ledger holds 0; RugBondDemo (superseded) 0x6dfF7cFE: eth_getBalance 0 wei, ledger holds 0; the current registries are at 0 |
| 8 | keeper | PASS | last run finished 0.1 h ago (workflow_dispatch); 0 failed actions; latest successful scheduled run: https://github.com/kenil1710/rugbond/actions/runs/42982369018 |
| 9 | tests | PASS | offline contract suite 347 tests, keeper suite 20 tests, Direct Mode 18 tests; all pass: true |
| 10 | docs language | PASS | 9 documents: no placeholders, no "known limitations", no tool-vendor mentions |
| 11 | live site | FAIL | 4/14 pages and APIs answer 200 at https://rugbond.vercel.app; /gate (-1), /keeper (-1), /verify (-1), /docs (-1), /bond/1 (-1), /bond/demo-1 (-1), /api/bond?id=1 (-1), /api/address?a=0xDd4B5DeFd7198C5A4597655323b851967d7a814F (-1), /api/badge?bond=1 (-1), /api/verify (-1) |
| 12 | e2e | PASS | Playwright on https://rugbond.vercel.app: 1 passed, 0 failed (docs/e2e/) |
