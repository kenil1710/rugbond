import type { Metadata } from "next";
import { readFileSync } from "node:fs";
import path from "node:path";
import { createHash } from "node:crypto";
import { marked } from "marked";
import { REPO } from "@/lib/deployments";

export const metadata: Metadata = { title: "Rules" };

export default function Docs() {
  const md = readFileSync(path.join(process.cwd(), "src/content/RULES.md"), "utf8");
  const sha = createHash("sha256").update(md).digest("hex");
  return (
    <>
      <p className="small" style={{ marginTop: 28 }}>docs/RULES.md, as in the repository · sha256 {sha.slice(0, 16)}</p>
      <article className="prose" dangerouslySetInnerHTML={{ __html: marked.parse(md, { async: false }) as string }} />
      <p className="small">Every number and reason above is checked against the deployed contract code by test/test_meaning.py. Source: <a href={`${REPO}/blob/main/docs/RULES.md`}>docs/RULES.md</a>.</p>
    </>
  );
}
