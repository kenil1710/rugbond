/**
 * Deploys every RugBond contract to Studio Dev FROM HEAD.
 *
 *   node deploy.mjs [--set=final|smoke] [--reason="..."] [--force]
 *   node deploy.mjs --commit=<sha> --only=RugBondDemo,LaunchGateDemo --force --reason="..."
 *     redeploys only the named contracts from build/ at <sha> (an ancestor of HEAD
 *     whose build/ files HEAD still has byte for byte), leaving the others untouched
 *
 * The bytes sent are `git show HEAD:build/<File>.py`, never the working tree,
 * and the script refuses to run if contracts/ or build/ has uncommitted
 * changes or build/ is stale - so what is on chain is byte-identical to the
 * pushed commit. Order:
 *
 *   RugBond         CANONICAL  (Ethereum, claim window >= 1 h)
 *   RugBondDemo     DEMO       (Base Sepolia, claim window >= 1 min)
 *   LaunchGate      on CANONICAL
 *   LaunchGateDemo  on DEMO
 *
 */
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { createClient, createAccount } from "genlayer-js";
import { CHAINS, accounts, fundOnStudio, deploy, argOf } from "./harness.mjs";

const root = new URL("..", import.meta.url).pathname;
const git = (...a) => execFileSync("git", ["-C", root, ...a]).toString();
if (git("status", "--porcelain", "contracts", "build").trim() !== "") {
  console.error("contracts/ or build/ has uncommitted changes; commit first"); process.exit(1);
}
execFileSync("python3", [root + "tools/build.py", "--check"], { stdio: "inherit" });
const head = git("rev-parse", argOf("commit", "HEAD")).trim();
const only = argOf("only", "") ? argOf("only", "").split(",") : null;
if (head !== git("rev-parse", "HEAD").trim()) {
  execFileSync("git", ["-C", root, "merge-base", "--is-ancestor", head, "HEAD"]);
  if (git("diff", "--name-only", head, "HEAD", "--", "build").trim() !== "") { console.error(`build/ changed since ${head}`); process.exit(1); }
}
const set = argOf("set", "final");
const chain = CHAINS.studiodev;
const acc = accounts();
const account = createAccount(acc.deployer.key);
const wallet = createClient({ chain, account });
const read = createClient({ chain });
await fundOnStudio(chain, account.address, 1000n * 10n ** 18n);
console.log(`deployer ${account.address}  HEAD ${head}  set ${set}`);

const path = new URL(set === "final" ? "../deployments.json" : `../deployments.${set}.json`, import.meta.url);
const doc = existsSync(path) ? JSON.parse(readFileSync(path, "utf8"))
  : { network: "studiodev", chain_id: 61997, rpc: "https://studio-dev.genlayer.com/api", explorer: "https://explorer-studio-dev.genlayer.com/", contracts: {} };
const persist = () => writeFileSync(path, JSON.stringify(doc, null, 2) + "\n");
const sha = (b) => createHash("sha256").update(b).digest("hex");

async function one(name, file, args, extra = {}) {
  const prev = doc.contracts[name];
  if (only && !only.includes(name)) { console.log(`${name} kept at ${prev.address}`); return prev.address; }
  if (prev?.commit === head && prev?.address && !process.argv.includes("--force")) {
    console.log(`${name} already deployed from HEAD at ${prev.address}`);
    return prev.address;
  }
  const code = execFileSync("git", ["-C", root, "show", `${head}:build/${file}.py`]);
  console.log(`\n${name}  build/${file}.py  args=${JSON.stringify(args)}  ${code.length} bytes  sha256 ${sha(code)}`);
  const res = await deploy({ chain, wallet, read, code: code.toString("utf8"), args, label: name });
  if (!res.ok) { console.error(`${name} FAILED`, res.out?.status, res.reason ?? "", res.out?.revertReason ?? "", res.out?.stderr?.slice(-2000) ?? ""); process.exit(1); }
  console.log(`  address ${res.address}`);
  if (prev?.address && prev.address !== res.address) {
    doc.superseded ??= [];
    doc.superseded.push({ name, ...prev, superseded_by: res.address, why: argOf("reason", "redeployed") });
  }
  doc.contracts[name] = { address: res.address, deploy_tx: res.hash, file: `build/${file}.py`, source: `contracts/${file}.py`,
    commit: head, bytes: code.length, sha256: sha(code), constructor_args: args, deployer: account.address,
    deployed_at: new Date().toISOString(), ...extra };
  persist();
  return res.address;
}

// the registry's fund: where GEN no holder claimed goes when it cannot go to claimants. Fixed here, at deployment;
// no method of the contract writes it. On this testnet it is a throwaway address (role `fund`).
const fund = acc.fund.address.toLowerCase();
const rc = await one("RugBond", "RugBond", ["CANONICAL", fund], { mode: "CANONICAL", fund });
const rd = await one("RugBondDemo", "RugBond", ["DEMO", fund], { mode: "DEMO", fund });
await one("LaunchGate", "LaunchGate", [rc], { mode: "CANONICAL" });
await one("LaunchGateDemo", "LaunchGate", [rd], { mode: "DEMO" });
console.log(`\nwrote ${path.pathname}`);
