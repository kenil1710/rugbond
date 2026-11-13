// End to end on the live site, demo registry, with a throwaway wallet (prepare.mjs saved its key before use):
// a token team rugs a real Uniswap V2 pair on Base Sepolia; on the site the wallet runs rug checks until RUGGED,
// claims its share (the GEN arrives), is refused on a bond it held nothing in, posts its own bond on a pool that
// holds, checks it to HELD and settles it (the bond comes back). Screenshots, video, trace and a summary go to docs/e2e/.
import { test, expect } from "@playwright/test";
import { readFileSync, writeFileSync, mkdirSync, existsSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { connectWallet, rpc } from "./wallet.js";

const root = new URL("../", import.meta.url);
const dep = JSON.parse(readFileSync(new URL("frontend/src/lib/deployments.json", root)));
const DEMO = dep.registryDemo;
const SHOTS = new URL("docs/e2e/", root);
mkdirSync(SHOTS, { recursive: true });
const KEY = process.env.E2E_KEY ?? "E2EDEMO";
const node = (script, ...args) => execFileSync("node", [new URL(script, root).pathname, ...args], { cwd: new URL("test/", root).pathname }).toString().trim();
const evm = () => JSON.parse(readFileSync(new URL("docs/demo-evm.json", root)));
// E2E_RESUME=1 continues an interrupted run: the summary and the screenshots of the steps already done are kept
const RESUME = !!process.env.E2E_RESUME && existsSync(new URL("summary.json", SHOTS));
const summary = RESUME ? JSON.parse(readFileSync(new URL("summary.json", SHOTS))) : { site: "", demo_registry: DEMO, steps: [] };
const log = (step, detail) => { if (RESUME && ["wallet", "setup", "rugged", "claimed", "refused"].includes(step) && summary.steps.some((x) => x.step === step && (x.what ?? "") === (detail.what ?? ""))) return; summary.steps.push({ step, ...detail, at: new Date().toISOString() }); console.log(step, JSON.stringify(detail)); writeFileSync(new URL("summary.json", SHOTS), JSON.stringify(summary, null, 1) + "\n"); };
const balance = async (a) => BigInt(await rpc("eth_getBalance", [a, "latest"]));
const shot = (page, name) => (RESUME && /^0[1-4]/.test(name) && existsSync(new URL(name + ".png", SHOTS)) ? null : page.screenshot({ path: new URL(name + ".png", SHOTS).pathname, fullPage: true }));
const statusText = (page) => page.getByRole("status").last();
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function view(page, fn, args) {
  for (let i = 0; i < 20; i++) {          // Studio meters reads per IP per minute: wait the minute out
    try {
      const r = await page.request.get(`/api/view?a=${DEMO}&f=${fn}&args=${encodeURIComponent(JSON.stringify(args))}&fresh=${Date.now()}`, { timeout: 120_000 });
      if (r.ok()) return (await r.json()).value;
    } catch { /* retried */ }
    await sleep(Math.min(15000 * (i + 1), 90000));
  }
  throw new Error("view " + fn);
}

/** page.goto, retried: a dropped connection is not a site failure. */
async function go(page, url) {
  for (let i = 0; ; i++) {
    try { return await page.goto(url, { timeout: 120_000 }); } catch (e) { if (i >= 5) throw e; await sleep(20_000 * (i + 1)); }
  }
}

/** Click "Run a rug check" on the bond page until the bond leaves ACTIVE. */
async function checkUntil(page, id, want) {
  const t0 = Date.now();
  while (Date.now() - t0 < 7 * 3600_000) {          // Base Sepolia's finalized head trails the tip by about 4.4 hours
    const b = await view(page, "get_bond", [id, Math.floor(Date.now() / 1000)]);
    if (b.status !== "ACTIVE") return b;
    await go(page, `/bond/demo-${id}`);
    await page.getByRole("button", { name: "Run a rug check" }).click();
    await expect(statusText(page)).toContainText(/accepted|finalized|failed|rejected/i, { timeout: 20 * 60_000 });
    const t = await statusText(page).innerText();
    log("rug_check_click", { bond: id, status: t.slice(0, 160) });
    if (!/accepted|finalized/i.test(t)) await sleep(240_000);
  }
  throw new Error(`bond ${id} never reached ${want}`);
}

test("rug check, claim, refusal, create, close on the demo registry", async ({ page, baseURL }) => {
  summary.site = baseURL;
  const address = await connectWallet(page);
  log("wallet", { address, note: "throwaway key saved in test/.accounts.json by e2e/prepare.mjs before use; funded from the Studio Dev faucet" });

  // 0. the chain side: a token, a real Uniswap V2 pair, tokens to this wallet before the bond; the team's bond; the rug
  if (!evm()[KEY]) node("test/demo_evm.mjs", "e2e_setup", address, KEY);
  const { bond_id: R } = JSON.parse(execFileSync("node", [new URL("test/e2e_bond.mjs", root).pathname], { cwd: new URL("test/", root).pathname, env: { ...process.env, E2E_KEY: KEY } }).toString().trim());
  if (!evm()[KEY].rug_block) node("test/demo_evm.mjs", "e2e_rug", KEY);
  log("setup", { token: evm()[KEY].token, pair: evm()[KEY].pair, bond: R, rug_block: evm()[KEY].rug_block, rug_tx: evm()[KEY].rug_tx });

  // 1. connect
  await go(page, `/bond/demo-${R}`);
  await page.getByRole("button", { name: "Connect wallet" }).click();
  await expect(page.getByText(address.slice(0, 6)).first()).toBeVisible();
  await shot(page, "01-bond-active");

  // 2. rug checks from the site until RUGGED
  const rb = await checkUntil(page, R, "RUGGED");
  expect(["RUGGED", "CLOSED"]).toContain(rb.status);
  expect(rb.rug_block).toBe(evm()[KEY].rug_block);
  await go(page, `/bond/demo-${R}`);
  await expect(page.getByText("The rug")).toBeVisible();
  await shot(page, "02-rugged-chart");
  log("rugged", { bond: R, rug_block: rb.rug_block, denominator: rb.denominator });

  // 3. claim: the share arrives at the wallet (resumable: a claim already on chain is kept)
  let claim = await view(page, "get_claim", [R, address.toLowerCase()]);
  if (!claim.found) {
    const before = await balance(address);
    await go(page, `/claim?bond=demo-${R}`);
    await page.getByRole("button", { name: "Claim my share" }).click();
    await expect(statusText(page)).toContainText(/accepted|finalized/i, { timeout: 20 * 60_000 });
    for (let i = 0; i < 30 && !claim.found; i++) { claim = await view(page, "get_claim", [R, address.toLowerCase()]); if (!claim.found) await sleep(10_000); }
    let after = await balance(address);
    for (let i = 0; i < 30 && after - before <= 0n; i++) { await sleep(10_000); after = await balance(address); }
    log("claimed", { share: claim.share, paid_to: claim.payee, wallet_delta: String(after - before) });
    expect(after - before).toBeGreaterThan(0n);
  } else log("claimed", { share: claim.share, paid_to: claim.payee, note: "claimed through the site in an earlier pass of this run" });
  expect(claim.found).toBe(true);
  await go(page, `/claim?bond=demo-${R}`);
  await expect(page.getByText(/You claimed/)).toBeVisible({ timeout: 120_000 });
  await shot(page, "03-claimed");

  // 4. refusals from the contract: a beneficiary after claiming (ALREADY_CLAIMED), and a closed bond's claim button is off
  const box = page.getByPlaceholder("0x… where your share should go");
  if (await box.count()) {
    await box.fill("0x000000000000000000000000000000000000beef");
    await page.getByRole("button", { name: "Commit" }).click();
    await expect(statusText(page)).toContainText(/failed|rejected/i, { timeout: 20 * 60_000 });
    log("refused", { what: "commit_beneficiary after claiming", status: await statusText(page).innerText() });
    await shot(page, "04-refused-beneficiary");
  }
  const A = JSON.parse(readFileSync(new URL("docs/demo-run.json", root))).bonds.A;
  for (let i = 0; i < 180; i++) { if ((await view(page, "get_bond", [A, Math.floor(Date.now() / 1000)])).status === "CLOSED") break; await sleep(60_000); }   // the demo run closes A after its claim window
  await go(page, `/claim?bond=demo-${A}`);
  await expect(page.getByRole("button", { name: "Claim my share" })).toBeDisabled({ timeout: 120_000 });
  await shot(page, "04-refused-closed");
  log("refused", { bond: A, what: "claim on a closed bond", status: "claim button disabled: the bond is CLOSED" });

  // 5. create: this wallet bonds HOLDDEMO (a pool that keeps its liquidity) for a few minutes (resumable: an e2e bond
  // this wallet already posted is used, never a second one)
  const hold = evm().HOLDDEMO;
  let mine = await view(page, "bonds_by_team", [address.toLowerCase(), 0, 50, Math.floor(Date.now() / 1000)]);
  let H = mine.items.find((b) => b.name.startsWith("e2e bond ") && ["ACTIVE", "HELD"].includes(b.status) && b.due !== "FUND")?.bond_id;   // a lapsed bond (no check for its recovery window) is not used
  if (!H) {
    const headNow = Number(node("test/demo_evm.mjs", "head"));
    await go(page, "/team");
    await page.getByLabel("Name").fill("e2e bond " + headNow);
    await page.getByLabel("Token").fill(hold.token);
    await page.getByLabel("V2 pair").fill(hold.pair);
    await page.getByLabel(/LP holders/).fill(hold.team);
    await page.getByLabel(/Promised minimum LP/).fill("1");
    await page.getByLabel("Start block").fill(String(headNow));
    await page.getByLabel(/Promise length/).fill("0.05");
    await page.getByLabel(/Claim window/).fill("1");
    await page.getByLabel("Bond (GEN)").fill("0.5");
    await page.getByRole("button", { name: "Post bond" }).click();
    await expect(statusText(page)).toContainText(/accepted|finalized/i, { timeout: 20 * 60_000 });
    await shot(page, "05-created");
    for (let i = 0; i < 20 && !H; i++) { mine = await view(page, "bonds_by_team", [address.toLowerCase(), 0, 50, Math.floor(Date.now() / 1000)]); H = mine.items.find((b) => b.name === "e2e bond " + headNow)?.bond_id; if (!H) await sleep(5000); }
  }
  log("created", { bond: H });

  // 6. checks until HELD, then close: settle returns the bond to this wallet
  const hb = await checkUntil(page, H, "HELD");
  expect(hb.status).toBe("HELD");
  const b2 = await balance(address);
  await go(page, `/bond/demo-${H}`);
  for (let i = 0; ; i++) {          // a fee estimate that times out sent nothing: the click is repeated
    await page.getByRole("button", { name: /Settle/ }).click();
    await expect(statusText(page)).toContainText(/accepted|finalized|failed|rejected/i, { timeout: 20 * 60_000 });
    const t = await statusText(page).innerText();
    if (/accepted|finalized/i.test(t) || i >= 5 || !/timed out|rate limit/i.test(t)) break;
    log("settle_click_retried", { bond: H, status: t.slice(0, 160) });
    await sleep(60_000); await go(page, `/bond/demo-${H}`);
  }
  await expect(statusText(page)).toContainText(/accepted|finalized/i, { timeout: 60_000 });
  let a2 = await balance(address);
  for (let i = 0; i < 60 && a2 - b2 < 400_000_000_000_000_000n; i++) { await sleep(10_000); a2 = await balance(address); }   // the 0.5 GEN bond less the fee; a fee refund alone is not the payout
  const fin = await view(page, "get_bond", [H, Math.floor(Date.now() / 1000)]);
  await shot(page, "06-closed");
  log("closed", { bond: H, status: fin.status, settled_to: fin.settled_to, amount: fin.settled_amount, wallet_delta: String(a2 - b2) });
  expect(fin.status).toBe("RETURNED");
  expect(a2 - b2).toBeGreaterThan(0n);
});
