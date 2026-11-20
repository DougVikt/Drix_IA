"""Stdlib unittest suite for Drix core modules (Windows and Linux)."""

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class SecretsTest(unittest.TestCase):
    def test_roundtrip_and_mask(self):
        from core import secrets
        secrets.reset_cache()
        secrets.set_secret("unit:test", "secret-abc-123")
        self.assertTrue(secrets.has_secret("unit:test"))
        self.assertEqual(secrets.get_secret("unit:test"), "secret-abc-123")
        self.assertTrue(secrets.mask(secrets.get_secret("unit:test")).startswith("sec"))
        secrets.delete_secret("unit:test")
        self.assertFalse(secrets.has_secret("unit:test"))


class ToolsTest(unittest.TestCase):
    def test_permissions_and_approval(self):
        import yaml
        from core import tools
        with open(ROOT / "config" / "config.yaml", encoding="utf-8") as handle:
            cfg = yaml.safe_load(handle)
        ctx = tools.ToolContext(cfg=cfg, workspace="t")
        target = ROOT / "data" / "_t.txt"
        # deny
        self.assertIn("bloqueada", tools.execute("run_shell", {"command": "echo"}, ctx))
        # ask needs token
        try:
            tools.execute("write_file", {"path": str(target), "content": "x"}, ctx)
            self.fail("should raise ApprovalRequired")
        except tools.ApprovalRequired as exc:
            token = exc.token
            ctx2 = tools.ToolContext(cfg=cfg, workspace="t", approvals=frozenset({token}))
            out = tools.execute("write_file", {"path": str(target), "content": "x"}, ctx2)
            self.assertIn("OK", out)
        try:
            target.unlink()
        except FileNotFoundError:
            pass


class AgentLoopStubTest(unittest.TestCase):
    def test_events(self):
        import asyncio
        from core import agent, providers
        from core.main import ConversationManager
        db_path = ROOT / "data" / "_agent_unittest.db"
        if db_path.exists():
            db_path.unlink()
        cm = ConversationManager(db_path=str(db_path))
        cm.set_workspace("t")
        original = providers.chat
        calls = [0]

        async def fake(messages, tools=None, cfg=None):
            calls[0] += 1
            if calls[0] == 1:
                return {"content": "", "tool_calls": [{"id": "c1", "name": "system_info", "arguments": {}}]}
            return {"content": "done", "tool_calls": []}

        providers.chat = fake
        events = []

        async def go():
            async for ev in agent.run("test", cm, workspace="t", max_steps=2):
                events.append(ev["type"])

        try:
            asyncio.run(go())
        finally:
            providers.chat = original
        self.assertIn("tool_call", events)
        self.assertIn("final", events)
        cm.delete_workspace("t")
        cm._conn.close()
        if db_path.exists():
            db_path.unlink()


if __name__ == "__main__":
    unittest.main(verbosity=2)
