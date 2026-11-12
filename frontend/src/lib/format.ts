export const short = (a: string | undefined | null, n = 6) => (a ? `${a.slice(0, n + 2)}…${a.slice(-4)}` : "");
export const EXPLORERS: Record<string, string> = { ethereum: "https://etherscan.io", base: "https://basescan.org", "base-sepolia": "https://sepolia.basescan.org" };
export const scan = (chain: string, kind: "address" | "tx" | "block" | "token", v: string | number) => `${EXPLORERS[chain] ?? EXPLORERS.ethereum}/${kind}/${v}`;
export const CHAIN_LABEL: Record<string, string> = { ethereum: "Ethereum", base: "Base", "base-sepolia": "Base Sepolia" };

/** A wei-like integer string as a decimal with at most `sig` significant digits. */
export function units(v: string | bigint | number | undefined, decimals = 18, sig = 4): string {
  if (v === undefined || v === null || v === "") return "0";
  let n = BigInt(v);
  const neg = n < 0n;
  if (neg) n = -n;
  const base = 10n ** BigInt(decimals);
  const whole = n / base;
  const frac = (n % base).toString().padStart(decimals, "0");
  let s: string;
  if (whole >= 1000n) s = whole.toLocaleString("en-US");
  else if (whole > 0n) s = `${whole}.${frac.slice(0, Math.max(0, sig - whole.toString().length))}`.replace(/\.?0+$/, "");
  else {
    const lead = frac.search(/[1-9]/);
    s = lead < 0 ? "0" : `0.${frac.slice(0, lead + sig)}`.replace(/0+$/, "");
  }
  return (neg ? "-" : "") + s;
}

export const gen = (wei: string | bigint | undefined) => units(wei ?? "0", 18, 4);

export function when(epoch: number): string {
  if (!epoch) return "";
  return new Date(epoch * 1000).toISOString().replace("T", " ").slice(0, 16) + " UTC";
}

export function ago(epoch: number, now = Math.floor(Date.now() / 1000)): string {
  if (!epoch) return "never";
  const d = now - epoch;
  const a = Math.abs(d);
  const t = a < 90 ? `${a}s` : a < 5400 ? `${Math.round(a / 60)} min` : a < 172800 ? `${Math.round(a / 3600)} h` : `${Math.round(a / 86400)} days`;
  return d >= 0 ? `${t} ago` : `in ${t}`;
}

/** What a bond's status means to a holder, in one sticker. */
export const STATUS: Record<string, { label: string; tone: "safe" | "rug" | "wait" | "done" }> = {
  ACTIVE: { label: "Holding so far", tone: "safe" },
  HELD: { label: "Held · bond back to team", tone: "safe" },
  RETURNED: { label: "Held · bond returned", tone: "done" },
  RUGGED: { label: "Rugged · holders claim", tone: "rug" },
  CLOSED: { label: "Rugged · closed", tone: "rug" },
  VOID: { label: "Void · not a pool of the token", tone: "wait" },
  UNRESOLVED: { label: "Unresolved · to the registry's fund", tone: "wait" },
};

export const REASON_TEXT: Record<string, string> = {
  RPC_UNREADABLE: "An RPC did not answer. Anyone can check again.",
  RPC_DISAGREE: "The two RPCs answered differently. Anyone can check again.",
  MALFORMED_READ: "The read did not add up. Anyone can check again.",
  NOT_A_PAIR: "The pair address does not answer like a V2 pool.",
  TOKEN_NOT_IN_PAIR: "The pair is not a pool of this token.",
  UNKNOWN_FACTORY: "The pair's factory is not a listed Uniswap V2-style factory.",
  FACTORY_DOES_NOT_KNOW_PAIR: "The factory maps the tokens to another pair: a look-alike.",
};
