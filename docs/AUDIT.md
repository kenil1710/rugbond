# Audit A-N

`node tools/audit.mjs` at 2026-11-11T17:06:30.844Z (final check of 2026-11-11T17:06:29.458Z, HEAD ad49601): **14/14**.

| | item | result | evidence |
|---|---|---|---|
| A | source | PASS | 4/4 contracts read back from Studio Dev are byte-identical to build/ at f28753d and HEAD; all from one commit: true |
| B | funds | PASS | 51 canonical settle payouts finalized and delivered to their recipients; 7 demo payouts finalized, delivered and matched by the recipient's balance delta; RugBond 0x4D2a5e25: eth_getBalance 0 wei, ledger holds 0; RugBondDemo 0x3491AAC8: eth_getBalance 0 wei, ledger holds 0; RugBond (superseded) 0x24ff68A1: eth_getBalance 0 wei, ledger holds 0; RugBondDemo (superseded) 0xbaa8FD3e: eth_getBalance 0 wei, ledger holds 0; RugBond (superseded) 0x07ED5695: eth_getBalance 0 wei, ledger holds 0; RugBondDemo (superseded) 0x6dfF7cFE: eth_getBalance 0 wei, ledger holds 0; the current registries are at 0; conservation tests: 21 pass |
| C | stuck states | PASS | every status has an exit (HELD/VOID -> team, RUGGED -> victim fund after the window, ACTIVE past the fixed recovery deadline -> victim fund; credits withdrawable; stray swept): 43 tests; on chain: 17 replay bonds on 0x4D2a5e250a419b1D1798E103F80A23aC5be59a23: 17 at the expected verdict and rug block; 17 settled (11 to the victim fund after the claim window, 6 back to the launchpad) |
| D | evidence binding | PASS | a RUGGED verdict stores R, its timestamp, the LP transfers out in R (tx hashes), LP before/after and the R-1 token snapshot; the pair must be one its listed factory maps back; claims bind to msg.sender and to transfers read from two log RPCs; 56 tests |
| E | two sources | PASS | two log RPCs and two state RPCs per chain from different operators; any disagreement or failure is PENDING, never a verdict (26 tests); GenVM: 39/39 feasibility reads and 2/2 claim reads identical to this machine's |
| F | identity | PASS | the claimant is msg.sender (claim takes only the bond id); a beneficiary is committed once by the holder itself; the team is the bond's sender and never its victim fund; 10 tests |
| G | coverage | PASS | offline contract suite 347 tests, keeper suite 20 tests, Direct Mode 18 tests; all pass: true; Playwright on https://rugbond.vercel.app (the site's production build), demo registry 0x3491AAC81ec96B05B50B25AD9F8b3CAeE7fF51b8: 1 passed, 0 failed; steps wallet, setup, rug_check_click, rugged, claimed, refused, created, closed (docs/e2e/) |
| H | counters | PASS | every write path checks everything before its first write; refused calls change no counter; 7 tests |
| I | real-world truth | PASS | 23/23 verdicts agree with Burn events, rug-transaction senders, reserves and end balances (docs/REAL_WORLD_CHECK.md) |
| J | keeper | PASS | last run finished 0.1 h ago (workflow_dispatch); 0 failed actions; latest successful scheduled run: https://github.com/kenil1710/rugbond/actions/runs/42982369018; keeper tests: 20 |
| K | gate meaning | PASS | bound to (token, bond id) or (token, team); copycats never read; safe only for a fresh agreed read of an ACTIVE bond; every other status x read x age x replay combination unsafe; 57 tests |
| L | docs truth | PASS | every constant, RPC, state and reason in docs/RULES.md checked against build/ (14 tests); the site's /docs is that file; 9 documents: no placeholders, no "known limitations", no tool-vendor mentions |
| M | verification package | PASS | tools/final_check.mjs 12/12; tools/verify_source.mjs; docs/FEASIBILITY.md, SEEDS.md, DEMO.md, REAL_WORLD_CHECK.md, ATTACK_REPORT.md |
| N | demo | PASS | 37/37 demo steps ok on Base Sepolia (rug, claims, refusals, held, copycat, gate); payouts verified; demo registry eth_getBalance 0 wei |
