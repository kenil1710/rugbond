# Final check

`node tools/final_check.mjs` at 2026-11-12T11:58:10.449Z: **10/12 passed**.

| # | check | result | detail |
|---|---|---|---|
| 1 | build and site copies fresh | PASS | build/ = contracts/ + shared code; the site's deployments.json and RULES.md are identical to the repository's |
| 2 | source match | PASS | 4/4 contracts read back from Studio Dev are byte-identical to build/ at 9c8495e and HEAD; all from one commit: true |
| 3 | addresses consistent | FAIL | docs/SUBMISSION.md lacks 0x42f22d3c3d782e678c0561217276be836cba93fb; docs/SUBMISSION.md lacks 0x40ab41033194dfa35aef2e7b295efe3af6ab5715; docs/SUBMISSION.md lacks 0xf079a5119a0997e9d6b47b83e52ef6f3eff03821; docs/SUBMISSION.md lacks 0xf851bc4dd469cccdb384bcdb2a480eb1255e312b |
| 4 | links | PASS | 251 distinct links, 20 checked (one per page shape): 13 answered 200; 7 explorer pages that serve browsers only (sepolia.basescan.org (403), basescan.org (403)) |
| 5 | canonical replays decided and settled | PASS | 17 replay bonds on 0x42f22d3C3d782E678C0561217276be836cba93fb: 17 at the expected verdict and rug block; 17 settled (11 to the registry's fund after a claim window in which nobody claimed, 6 back to the launchpad); 19/19 checks stored by GenVM read identically from this machine |
| 6 | payouts arrived | FAIL | 65 canonical settle payouts finalized and delivered to their recipients; 13 demo payouts finalized, delivered and matched by the recipient's balance delta; 0x42f22d3C bond 7: no settle transaction found; 0x42f22d3C bond 8: no settle transaction found; 0x42f22d3C bond 14: no settle transaction found |
| 7 | balances match ledgers | PASS | RugBond 0x42f22d3C: eth_getBalance 0 wei, ledger holds 0; RugBondDemo 0x40aB4103: eth_getBalance 0 wei, ledger holds 0; RugBond (superseded) 0x24ff68A1: eth_getBalance 0 wei, ledger holds 0; RugBondDemo (superseded) 0xbaa8FD3e: eth_getBalance 0 wei, ledger holds 0; RugBond (superseded) 0x07ED5695: eth_getBalance 0 wei, ledger holds 0; RugBondDemo (superseded) 0x6dfF7cFE: eth_getBalance 0 wei, ledger holds 0; RugBond (superseded) 0x4D2a5e25: eth_getBalance 0 wei, ledger holds 0; RugBondDemo (superseded) 0x3491AAC8: eth_getBalance 0 wei, ledger holds 0; the current registries are at 0 |
| 8 | keeper | PASS | last run finished 0.2 h ago (workflow_dispatch); 0 failed actions; latest successful scheduled run since the deployment (2026-11-12T04:53:01.073Z): https://github.com/kenil1710/rugbond/actions/runs/43177480645 |
| 9 | tests | PASS | offline contract suite 406 tests, keeper suite 26 tests, Direct Mode 24 tests; all pass: true |
| 10 | docs language | PASS | 9 documents: no placeholders, no limitation or risk disclaimers, no tool-vendor mentions |
| 11 | live site | PASS | 14/14 pages and APIs answer 200 at https://rugbond.vercel.app |
| 12 | e2e | PASS | Playwright on https://rugbond.vercel.app (the site's production build), demo registry 0x40aB41033194DFA35aeF2e7b295eFe3AF6ab5715: 1 passed, 0 failed; steps wallet, setup, rug_check_click, rugged, claimed, refused, created, closed (docs/e2e/) |
