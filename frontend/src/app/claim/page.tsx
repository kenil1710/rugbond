import type { Metadata } from "next";
import { Suspense } from "react";
import { ClaimForm } from "./ClaimForm";
export const metadata: Metadata = { title: "Claim" };
export default function Claim() {
  return (
    <>
      <h1>Claim your share</h1>
      <p style={{ maxWidth: 720 }}>Connect the wallet that held the token at the block before the rug: the claimant is the signer itself, and the same key is your address on GenLayer. Validators read your balance at that block from two RPCs. Contracts and excluded addresses cannot claim; each holder claims once. Optionally commit a beneficiary first (once) to be paid elsewhere.</p>
      <Suspense fallback={<p className="small">Loading…</p>}><ClaimForm /></Suspense>
    </>
  );
}
