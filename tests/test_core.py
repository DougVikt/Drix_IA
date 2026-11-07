"""Stdlib unittest suite for Drix core modules."""

import unittest, sys, os
sys.path.insert(0, "F:/")

class SecretsTest(unittest.TestCase):
    def test_roundtrip_and_mask(self):
        from core import secrets, runtime
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
        cfg = yaml.safe_load(open("F:/config/config.yaml", encoding="utf-8"))
        ctx = tools.ToolContext(cfg=cfg, workspace="t")
        # deny
        self.assertIn("bloqueada", tools.execute("run_shell", {"command":"echo"}, ctx))
        # ask needs token
        try:
            tools.execute("write_file", {"path":"F:/data/_t.txt","content":"x"}, ctx)
            self.fail("should raise ApprovalRequired")
        except tools.ApprovalRequired as exc:
            token = exc.token
            ctx2 = tools.ToolContext(cfg=cfg, workspace="t", approvals=frozenset({token}))
            out = tools.execute("write_file", {"path":"F:/data/_t.txt","content":"x"}, ctx2)
            self.assertIn("OK", out)

class AgentLoopStubTest(unittest.TestCase):
    def test_events(self):
        import asyncio, sys
        from core import agent, providers
        from core.main import ConversationManager
        p = "F:/data/_agent_unittest.db"
        if os.path.exists(p): os.remove(p)
        cm = ConversationManager(db_path="./data/_agent_unittest.db"); cm.set_workspace("t")
        original = providers.chat
        calls = [0]
        async def fake(messages, tools=None, cfg=None):
            calls[0] += 1
            if calls[0] == 1:
                return {"content":"", "tool_calls":[{"id":"c1","name":"system_info","arguments":{}}]}
            return {"content":"done", "tool_calls":[]}
        providers.chat = fake
        events = []
        async def go():
            async for ev in agent.run("test", cm, workspace="t", max_steps=2):
                events.append(ev["type"])
        asyncio.run(go())
        providers.chat = original
        self.assertIn("tool_call", events)
        self.assertIn("final", events)
        cm.delete_workspace("t"); cm._conn.close()
        if os.path.exists(p): os.remove(p)

if __name__ == "__main__":
    unittest.main(verbosity=2)
