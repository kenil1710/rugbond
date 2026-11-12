# What if pulling the liquidity cost the team money?

Most memecoin rugs I looked at this autumn were not clever. Someone deploys a token, pairs it with a few ETH on
Uniswap V2, keeps the LP tokens, waits for buyers, and a few hours later calls `removeLiquidity`. The pool is empty,
the holders own tokens nobody can sell, and the deployer walks away with the ETH. On Ethereum I found dozens of
these in a single week, many from the same handful of wallets. On Base it was worse: in one sample, every new WETH
pair with real liquidity was pulled within a day.

"LP locked" badges exist, and they help, but they're a claim about an address. If the claim turns out to be false
nothing happens to the team, and nobody pays the holders. So I built RugBond around a different question: what if
the team had to put money behind the promise, and breaking it paid the people it hurt?

## The idea

A team, or the launchpad listing it, posts a bond in GEN on GenLayer and freezes a promise:

> these wallets will keep at least this much of the pool's LP, from this block until this time.

That's it. No roadmap, no vibes, just numbers you can check on chain. If the LP those wallets hold drops below the
floor before the deadline, the bond belongs to the people who held the token when it happened, in proportion to
what they held. Whatever they don't claim within the window is shared among the holders who did claim. The team
never gets to say where unclaimed money goes (more on that below). If the promise holds, the team gets its bond back.

## Who decides?

Nobody, which was the point. GenLayer's validators each read the chain themselves, and every read has to come back
identical from two RPC endpoints run by different operators. The rule is plain code: walk forward from the start
block, look at every LP transfer out of the promised wallets, check their combined balance at the end of each of those
blocks, and stop at the first block where it's below the floor. That block is R. If nothing breaks the floor before
the deadline, the promise held.

If a read fails or the two endpoints disagree, nothing is decided. The check is marked pending and anyone can run
it again. There's a fixed recovery deadline, so you can't stall a bond forever by spamming broken checks.

## The part I got wrong at first

My first version paid holders on their balance at R-1, the block before the rug. Then I tried attacking it, and the
team can game that easily. Right before pulling, the team buys up most of the float from its own pool. The ETH it
pays goes into the pool, and it gets that ETH straight back when it removes the liquidity. Then it claims most of its
own bond through fresh wallets. The penalty almost disappears.

The fix: a holder is paid on the smaller of its balance at the bond's start block and at R-1, so anything bought
after the promise was made earns nothing. I like this version much better: the bond protects the people who trusted
the promise when it was made.

## The parts a reviewer got me on

Three more, from a strict review of the deployed code.

My second rule also said: any address that received the token straight from the team after the start can't claim at
all. That hands the team a weapon. Send every holder one wei, or a zero-value transfer, and nobody can claim. Now a
transfer from the team just gets subtracted from what the holder is paid on. Dust costs the dust.

The team used to name a "victim fund" for unclaimed money, with a rule that it couldn't name itself. A second
wallet gets around that in one step. So the team no longer names anything. Unclaimed shares are split among the
holders who did claim, in one extra round, and the odd leftover wei go to an address fixed when the registry was
deployed. The same goes for a bond nobody managed to read in time. And a team can't run out that clock by flooding
its LP wallet with tiny transfers: the scan keeps a cursor per bond, works through any number of them across checks,
and the deadline only counts time in which no check made progress.

Last one: a validator used to re-read whatever block range the leader named. A dishonest leader could name an empty
range, say "I couldn't read it", and have validators agree. Now each validator works the range out from the
contract's own storage, and it accepts "couldn't read" only if its own read fails too.

## Does it work on real rugs?

I pulled 23 real cases: 17 rugs (11 on Ethereum, 6 on Base, all Uniswap V2 LP pulls by the wallet that minted the
LP), and 6 tokens whose LP stayed put, whether team-held, locked in UNCX, or burned. The rule's verdict matched every
one. Then I checked each verdict against things the rule never looks at: the Burn event in the rug block, who sent
that transaction, how much WETH left the pool. All 23 agreed. Four of the "held" tokens still went to zero through
selling, and that's honest: RugBond bonds the liquidity promise, not the price.

Inside GenVM, every validator read of those cases came back byte-for-byte identical to my own reads. Base mainnet
turned out to be the awkward one. From the validators' servers, only one free public endpoint will serve Base logs,
and the rule needs two. So the live registry covers Ethereum, and the demo runs on Base Sepolia.

## What's live

- A canonical registry with replay bonds over those real Ethereum rugs and held tokens. To be clear, these were
  created after the fact, with tiny bonds, to show the rule on real history. They're marked as replays on chain, and
  the gate never treats a replay as a credential.
- A demo on Base Sepolia with real tokens and a real Uniswap V2 pair. I rug one and hold the other, then go through
  the claims, a dusting attempt, a flood of 1,100 LP transfers, every kind of refusal, the bonus round and the
  settlements, with each payout checked by the recipient's balance.
- LaunchGate, a small contract that answers "is this token's promise holding right now?" for one bond or one team.
  It never answers favorably on missing, pending or stale data, and a copycat bond by someone else is never read.
- A keeper on GitHub Actions that files the checks and settlements, with its state on a branch so a crashed run
  picks up where it stopped.

It only covers one kind of rug, liquidity pulled from a V2-style pool. Hidden mints, blacklists and honeypots are a
different problem. But that one kind is most of what I saw, and it's the kind you can check.
