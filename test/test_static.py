"""Static checks on the deployed bytes (build/): header pin, inlined helpers, undefined names, no model, one way out."""
import re
import subprocess
import sys
import unittest
from pathlib import Path

import stub

ROOT = Path(__file__).resolve().parent.parent
FILES = ["RugBond", "LaunchGate"]
PIN = "py-genlayer:babwp9t37jw9g4j2bccgn14g6x7x9s1f7dsmh7emvz735pz4zxa0"


class Static(unittest.TestCase):
    def src(self, n):
        return (ROOT / "build" / (n + ".py")).read_text()


def _gen():
    for n in FILES:
        def t1(self, n=n):
            lines = self.src(n).split("\n")
            self.assertEqual(lines[0], "# v0.3.0")
            self.assertEqual(lines[1], '# { "Depends": "' + PIN + '" }')
        def t2(self, n=n):
            self.assertEqual(stub.undefined_names(ROOT / "build" / (n + ".py")), [])
        def t3(self, n=n):
            s = self.src(n)
            code = "\n".join(l.split("#")[0] for l in s.split("\n")[2:])
            for bad in ("exec_prompt(", "prompt_comparative(", "prompt_non_comparative(", "get_webpage(", "py-genlayer:test",
                        "py-genlayer:latest", "emit_transfer(", ".replace("):
                self.assertNotIn(bad, code, bad)
        def t4(self, n=n):
            self.assertNotIn("# INLINE:", self.src(n))
        def t5(self, n=n):
            s = self.src(n)
            for spelling in ("gl.contract.Contract", "gl.storage.allow", "gl.message.raw"):
                self.assertIn(spelling, s)
        def t6(self, n=n):
            s = self.src(n)
            self.assertNotIn("import requests", s)
            self.assertNotIn("random", s)
            self.assertNotIn("time.time", s)
        for i, t in enumerate((t1, t2, t3, t4, t5, t6)):
            setattr(Static, "test_%s_%d_%s" % (n.lower(), i, t.__name__), t)


_gen()


class Money(unittest.TestCase):
    def test_single_send_site(self):
        s = (ROOT / "build" / "RugBond.py").read_text()
        self.assertEqual(s.count("emit_call("), 1)
        self.assertEqual(len(re.findall(r"self\._send\(", s)), 4)       # claim, settle, withdraw_credit, sweep_stray

    def test_gate_never_sends(self):
        s = (ROOT / "build" / "LaunchGate.py").read_text()
        self.assertNotIn("emit_call", s)
        self.assertNotIn("payable", s)

    def test_only_create_is_payable(self):
        s = (ROOT / "build" / "RugBond.py").read_text()
        self.assertEqual(s.count("@gl.public.write.payable"), 1)
        self.assertIn("@gl.public.write.payable\n    def create_bond", s)

    def test_writes_after_checks(self):
        s = (ROOT / "build" / "RugBond.py").read_text()
        for fn in ("def claim", "def settle", "def check", "def withdraw_credit", "def sweep_stray"):
            body = s[s.index(fn):]
            body = body[:body.index("\n    @gl.public")]
            self.assertIn("# --- writes", body, fn)
            head = body[:body.index("# --- writes")]
            self.assertNotRegex(head, r"\n\s+self\.[a-z_]+(\[[^\]]+\])? = ", fn)

    def test_build_is_fresh(self):
        r = subprocess.run([sys.executable, str(ROOT / "tools" / "build.py"), "--check"], capture_output=True)
        self.assertEqual(r.returncode, 0, r.stdout)


class Rpcs(unittest.TestCase):
    def test_two_rpcs_per_chain_distinct_operators(self):
        import world
        ch = world.module("RugBond").CHAINS
        for k, v in ch.items():
            a, b = v[1]
            host = lambda u: u.split("//")[1].split("/")[0].split(".")[-2]
            self.assertNotEqual(host(a), host(b), k)

    def test_js_chain_table_matches(self):
        import world
        ch = world.module("RugBond").CHAINS
        js = (ROOT / "tools" / "lib" / "chains.mjs").read_text()
        for k, v in ch.items():
            for u in v[1]:
                self.assertIn(u, js)
            self.assertIn("span: %d, windows: %d" % (v[2], v[3]), js)


if __name__ == "__main__":
    unittest.main()
