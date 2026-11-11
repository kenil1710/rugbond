// Step 1 of the e2e run: a fresh throwaway key, saved in the gitignored test/.accounts.json (under "throwaway")
// BEFORE it is funded or used; funded from the Studio Dev faucet. Prints only the address.
import { generatePrivateKey, privateKeyToAccount } from "viem/accounts";
import { readFileSync, writeFileSync } from "node:fs";
const ACCOUNTS = new URL("../test/.accounts.json", import.meta.url);
const key = generatePrivateKey();
const address = privateKeyToAccount(key).address;
const a = JSON.parse(readFileSync(ACCOUNTS, "utf8"));
(a.throwaway ??= []).push({ key, address, use: "e2e", created_at: new Date().toISOString() });
writeFileSync(ACCOUNTS, JSON.stringify(a, null, 2) + "\n", { mode: 0o600 });
await fetch("https://studio-dev.genlayer.com/api", { method: "POST", headers: { "content-type": "application/json" },
  body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "sim_fundAccount", params: [address, 50 * 1e18] }) });
console.log(address);
