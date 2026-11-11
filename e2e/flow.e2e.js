// End to end on the live site, demo registry, with a throwaway wallet (prepare.mjs saved its key before use):
// a token team rugs a real Uniswap V2 pair on Base Sepolia; on the site the wallet runs rug checks until RUGGED,
// claims its share (the GEN arrives), is refused on a bond it held nothing in, posts its own bond on a pool that
// holds, checks it to HELD and settles it (the bond comes back). Screenshots, video, trace and a summary go to docs/e2e/.
import { test, expect } from "@playwright/test";
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { connectWallet, rpc } from "./wallet.js";

const root = new URL("../", import.meta.url);
const dep = JSON.parse(readFileSync(new URL("frontend/src/lib/deployments.json", root)));
const DEMO = dep.registryDemo;
const SHOTS = new URL("docs/e2e/", root);
mkdirSync(SHOTS, { recursive: true });
const node = (script, ...args) => execFileSync("node", [new URL(script, root).pathname, ...args], { cwd: new URL("test/", root).pathname }).toString().trim();
const evm = () => JSON.parse(readFileSync(new URL("docs/demo-evm.json", root)));
const summary = { site: "", demo_registry: DEMO, steps: [] };
const log = (step, detail) => { summary.steps.push({ step, ...detail, at: new Date().toISOString() }); console.log(step, JSON.stringify(detail)); writeFileSync(new URL("summary.json", SHOTS), JSON.stringify(summary, null, 1) + "\n"); };
const balance = async (a) => BigInt(await rpc("eth_getBalance", [a, "latest"]));
const shot = (page, name) => page.screenshot({ path: new URL(name + ".png", SHOTS).pathname, fullPage: true });
const statusText = (page) => page.getByRole("status").last();
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function view(page, fn, args) {
  for (let i = 0; i < 6; i++) {
    const r = await page.request.get(`/api/view?a=${DEMO}&f=${fn}&args=${encodeURIComponent(JSON.stringify(args))}&fresh=${Date.now()}`);
    if (r.ok()) return (await r.json()).value;
    await sleep(5000 * (i + 1));
  }
  throw new Error("view " + fn);
}

/** Click "Run a rug check" on the bond page until the bond leaves ACTIVE. */
async function checkUntil(page, id, want) {
  const t0 = Date.now();
  while (Date.now() - t0 < 7 * 3600_000) {          // Base Sepolia's finalized head trails the tip by about 4.4 hours
    const b = await view(page, "get_bond", [id, Math.floor(Date.now() / 1000)]);
    if (b.status !== "ACTIVE") return b;
    await page.goto(`/bond/demo-${id}`);
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
  if (!evm().E2EDEMO) node("test/demo_evm.mjs", "e2e_setup", address);
  const { bond_id: R } = JSON.parse(node("test/e2e_bond.mjs"));
  if (!evm().E2EDEMO.rug_block) node("test/demo_evm.mjs", "e2e_rug");
  log("setup", { token: evm().E2EDEMO.token, pair: evm().E2EDEMO.pair, bond: R, rug_block: evm().E2EDEMO.rug_block, rug_tx: evm().E2EDEMO.rug_tx });

  // 1. connect
  await page.goto(`/bond/demo-${R}`);
  await page.getByRole("button", { name: "Connect wallet" }).click();
  await expect(page.getByText(address.slice(0, 6))).toBeVisible();
  await shot(page, "01-bond-active");

  // 2. rug checks from the site until RUGGED
  const rb = await checkUntil(page, R, "RUGGED");
  expect(rb.status).toBe("RUGGED");
  expect(rb.rug_block).toBe(evm().E2EDEMO.rug_block);
  await page.goto(`/bond/demo-${R}`);
  await expect(page.getByText("The rug")).toBeVisible();
  await shot(page, "02-rugged-chart");
  log("rugged", { bond: R, rug_block: rb.rug_block, denominator: rb.denominator });

  // 3. claim: the share arrives at the wallet
  const before = await balance(address);
  await page.goto(`/claim?bond=demo-${R}`);
  await page.getByRole("button", { name: "Claim my share" }).click();
  await expect(statusText(page)).toContainText(/accepted|finalized/i, { timeout: 20 * 60_000 });
  let claim = { found: false };
  for (let i = 0; i < 30 && !claim.found; i++) { claim = await view(page, "get_claim", [R, address.toLowerCase()]); if (!claim.found) await sleep(10_000); }
  expect(claim.found).toBe(true);
  let after = await balance(address);
  for (let i = 0; i < 30 && after - before <= 0n; i++) { await sleep(10_000); after = await balance(address); }
  await shot(page, "03-claimed");
  log("claimed", { share: claim.share, paid_to: claim.payee, wallet_delta: String(after - before) });
  expect(after - before).toBeGreaterThan(0n);

  // 4. refusal: a rugged bond this wallet held nothing in (the demo's bond A)
  const A = JSON.parse(readFileSync(new URL("docs/demo-run.json", root))).bonds.A;
  await page.goto(`/claim?bond=demo-${A}`);
  const btn = page.getByRole("button", { name: "Claim my share" });
  if (await btn.isEnabled()) {
    await btn.click();
    await expect(statusText(page)).toContainText(/failed|rejected/i, { timeout: 20 * 60_000 });
  }
  await shot(page, "04-refused");
  log("refused", { bond: A, status: (await statusText(page).count()) ? await statusText(page).innerText() : "claim button disabled: the bond is no longer open for claims" });

  // 5. create: this wallet bonds HOLDDEMO (a pool that keeps its liquidity) for a few minutes
  const hold = evm().HOLDDEMO;
  const headNow = Number(node("test/demo_evm.mjs", "head"));
  await page.goto("/team");
  await page.getByLabel("Name").fill("e2e bond " + headNow);
  await page.getByLabel("Token").fill(hold.token);
  await page.getByLabel("V2 pair").fill(hold.pair);
  await page.getByLabel(/LP holders/).fill(hold.team);
  await page.getByLabel(/Promised minimum LP/).fill("1");
  await page.getByLabel("Start block").fill(String(headNow));
  await page.getByLabel(/Promise length/).fill("0.05");
  await page.getByLabel(/Claim window/).fill("1");
  await page.getByLabel("Bond (GEN)").fill("0.5");
  await page.getByLabel(/Victim fund/).fill(JSON.parse(readFileSync(new URL("test/.accounts.json", root))).victimfund.address);
  await page.getByRole("button", { name: "Post bond" }).click();
  await expect(statusText(page)).toContainText(/accepted|finalized/i, { timeout: 20 * 60_000 });
  await shot(page, "05-created");
  let mine = { items: [] };
  for (let i = 0; i < 20 && !mine.items.find((b) => b.name === "e2e bond " + headNow); i++) { mine = await view(page, "bonds_by_team", [address.toLowerCase(), 0, 50, Math.floor(Date.now() / 1000)]); await sleep(5000); }
  const H = mine.items.find((b) => b.name === "e2e bond " + headNow).bond_id;
  log("created", { bond: H });

  // 6. checks until HELD, then close: settle returns the bond to this wallet
  const hb = await checkUntil(page, H, "HELD");
  expect(hb.status).toBe("HELD");
  const b2 = await balance(address);
  await page.goto(`/bond/demo-${H}`);
  await page.getByRole("button", { name: /Settle/ }).click();
  await expect(statusText(page)).toContainText(/accepted|finalized/i, { timeout: 20 * 60_000 });
  let a2 = await balance(address);
  for (let i = 0; i < 30 && a2 - b2 <= 0n; i++) { await sleep(10_000); a2 = await balance(address); }
  const fin = await view(page, "get_bond", [H, Math.floor(Date.now() / 1000)]);
  await shot(page, "06-closed");
  log("closed", { bond: H, status: fin.status, settled_to: fin.settled_to, amount: fin.settled_amount, wallet_delta: String(a2 - b2) });
  expect(fin.status).toBe("RETURNED");
  expect(a2 - b2).toBeGreaterThan(0n);
});
