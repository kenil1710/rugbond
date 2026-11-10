// The chain table, the same as CHAINS / RPC_LIMITS in contracts/shared/common.py
// (test_static checks they match). Per chain: two archive RPCs run by different
// operators (every read is made on both and must be identical) and how many
// blocks one rug check reads; per RPC: the eth_getLogs window and batch size it
// serves to validators reading at once.
export const CHAINS = {
  ethereum: { id: 1, rpcs: ["https://gateway.tenderly.co/public/mainnet", "https://rpc.mevblocker.io"], check_blocks: 80000,
    explorer: "https://etherscan.io", weth: "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2" },
  "base-sepolia": { id: 84532, rpcs: ["https://base-sepolia.gateway.tenderly.co", "https://base-sepolia-rpc.publicnode.com"], check_blocks: 40000,
    explorer: "https://sepolia.basescan.org", weth: "0x4200000000000000000000000000000000000006" },
};
export const RPC_LIMITS = {
  "https://gateway.tenderly.co/public/mainnet": { span: 80000, batch: 4 },
  "https://rpc.mevblocker.io": { span: 10000, batch: 12 },
  "https://base-sepolia.gateway.tenderly.co": { span: 40000, batch: 4 },
  "https://base-sepolia-rpc.publicnode.com": { span: 40000, batch: 12 },
};
// Base mainnet: read from this machine only (docs/FEASIBILITY.md): its public endpoints serve eth_getLogs over at most
// 1000 blocks, and from GenLayer Studio's validators only one of them answers eth_getLogs at all.
export const MAC_ONLY = {
  base: { id: 8453, rpcs: ["https://base.gateway.tenderly.co", "https://base.rpc.thirdweb.com"], check_blocks: 8000,
    explorer: "https://basescan.org", weth: "0x4200000000000000000000000000000000000006" },
};
export const MAC_LIMITS = { "https://base.gateway.tenderly.co": { span: 1000, batch: 3 }, "https://base.rpc.thirdweb.com": { span: 1000, batch: 3 } };
export const ALL_CHAINS = { ...CHAINS, ...MAC_ONLY };
export const ALL_LIMITS = { ...RPC_LIMITS, ...MAC_LIMITS };
export const TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef";
