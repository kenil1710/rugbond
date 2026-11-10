/**
 * Creates test/.accounts.json (gitignored): throwaway signing keys, saved to
 * disk BEFORE any of them is used. Existing roles are preserved unless --force
 * is passed. Keys never leave this file; scripts load them and print addresses only.
 *
 * The same key is an address on GenLayer Studio Dev and on Base Sepolia.
 *
 *   deployer   deploys every GenLayer contract; deploys the Base Sepolia demo token/pair
 *   keeper     the keeper bot signer (rug checks, settles, closes)
 *   team       posts demo bonds (and is the demo token's team / LP holder)
 *   team2      the second demo token's team
 *   launchpad  posts canonical replay bonds
 *   holder1-5  demo token holders on Base Sepolia (claim on GenLayer with the same key)
 *   victimfund the demo victim-fund address
 *   stranger   anyone else: calls that must be refused
 *   probe      throwaway GenVM probes
 *   e2e        the Playwright wallet
 */
import { createAccount } from "genlayer-js";
import { randomBytes } from "node:crypto";
import { existsSync, readFileSync, writeFileSync } from "node:fs";

const target = new URL("./.accounts.json", import.meta.url);
const force = process.argv.includes("--force");
const ROLES = ["deployer", "keeper", "team", "team2", "launchpad", "holder1", "holder2", "holder3", "holder4", "holder5",
  "victimfund", "stranger", "probe", "e2e"];
const existing = existsSync(target) && !force ? JSON.parse(readFileSync(target, "utf8")) : {};
const out = {};
for (const role of ROLES) {
  if (existing[role]?.key) { out[role] = existing[role]; continue; }
  const key = `0x${randomBytes(32).toString("hex")}`;
  out[role] = { key, address: createAccount(key).address };
}
writeFileSync(target, JSON.stringify(out, null, 2) + "\n", { mode: 0o600 });
for (const role of ROLES) console.log(`  ${role.padEnd(10)} ${out[role].address}`);
