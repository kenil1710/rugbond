# Final check

`node tools/final_check.mjs` at 2026-11-13T09:56:32.160Z: **12/12 passed**.

| # | check | result | detail |
|---|---|---|---|
| 1 | build and site copies fresh | PASS | build/ = contracts/ + shared code; the site's deployments.json and RULES.md are identical to the repository's |
| 2 | source match | PASS | 4/4 contracts read back from Studio Dev are byte-identical to build/ at db54703 and HEAD; all from one commit: true |
| 3 | addresses consistent | PASS | the four deployed addresses appear in README.md, docs/SUBMISSION.md, docs/SEEDS.md, docs/DEMO.md, frontend/src/lib/deployments.json |
| 4 | links | PASS | 257 distinct links, 29 checked (one per page shape): 22 answered 200; 7 explorer pages that serve browsers only (sepolia.basescan.org (403), basescan.org (403)) |
| 5 | canonical replays decided and settled | PASS | 17 replay bonds on 0x8295e5EE6dd5e74a2Ad4704B6025Ae4f2EcA1086: 17 at the expected verdict and rug block; 17 settled (11 to the registry's fund after a claim window in which nobody claimed, 6 back to the launchpad); 18/18 checks stored by GenVM read identically from this machine |
| 6 | payouts arrived | PASS | 85 canonical settle payouts finalized and delivered to their recipients; 12 demo payouts finalized, delivered and matched by the recipient's balance delta |
| 7 | balances match ledgers | PASS | RugBond 0x8295e5EE: eth_getBalance 0 wei, ledger holds 0; RugBondDemo 0xFf72e304: eth_getBalance 0 wei, ledger holds 0; RugBond (superseded) 0x24ff68A1: eth_getBalance 0 wei, ledger holds 0; RugBondDemo (superseded) 0xbaa8FD3e: eth_getBalance 0 wei, ledger holds 0; RugBond (superseded) 0x07ED5695: eth_getBalance 0 wei, ledger holds 0; RugBondDemo (superseded) 0x6dfF7cFE: eth_getBalance 0 wei, ledger holds 0; RugBond (superseded) 0x4D2a5e25: eth_getBalance 0 wei, ledger holds 0; RugBondDemo (superseded) 0x3491AAC8: eth_getBalance 0 wei, ledger holds 0; RugBond (superseded) 0x42f22d3C: eth_getBalance 0 wei, ledger holds 0; RugBondDemo (superseded) 0x40aB4103: eth_getBalance 0 wei, ledger holds 0; the current registries are at 0 |
| 8 | keeper | PASS | last run finished 2.6 h ago (schedule); 0 failed actions; latest successful scheduled run since the deployment (2026-11-12T16:41:34.649Z): https://github.com/kenil1710/rugbond/actions/runs/43384933626 |
| 9 | tests | PASS | offline contract suite 404 tests, keeper suite 23 tests, Direct Mode 24 tests; all pass: true |
| 10 | docs language | PASS | 9 documents: no placeholders, no limitation or risk disclaimers, no tool-vendor mentions |
| 11 | live site | PASS | 14/14 pages and APIs answer 200 at https://rugbond.vercel.app |
| 12 | e2e | PASS | Playwright on https://rugbond.vercel.app (the site's production build), demo registry 0xFf72e30494D0026DE964870F04f4Fba84F3543CE: 1 passed, 0 failed; steps wallet, setup, rug_check_click, rugged, claimed, refused, created, lapsed, closed (docs/e2e/) |
