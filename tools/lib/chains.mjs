// The chain table, the same as CHAINS in contracts/shared/common.py (test_meaning
// checks they match). Per chain: two archive RPCs run by different operators
// (every read is made on both and must be identical), the eth_getLogs window
// both accept (blocks) and how many windows one rug check may read.
export const CHAINS = {
  ethereum: { id: 1, rpcs: ["https://gateway.tenderly.co/public/mainnet", "https://rpc.mevblocker.io"], span: 10000, windows: 8,
    explorer: "https://etherscan.io", weth: "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2" },
  base: { id: 8453, rpcs: ["https://base.gateway.tenderly.co", "https://base.rpc.thirdweb.com"], span: 1000, windows: 8,
    explorer: "https://basescan.org", weth: "0x4200000000000000000000000000000000000006" },
  "base-sepolia": { id: 84532, rpcs: ["https://base-sepolia.gateway.tenderly.co", "https://base-sepolia-rpc.publicnode.com"], span: 10000, windows: 4,
    explorer: "https://sepolia.basescan.org", weth: "0x4200000000000000000000000000000000000006" },
};
export const TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef";
