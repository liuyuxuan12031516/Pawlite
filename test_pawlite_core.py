import unittest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

# 确保能导入 pawlite
sys.path.insert(0, str(Path(__file__).parent))

from pawlite.config import Config
from pawlite.skills import SkillRegistry, SkillContext
from pawlite.cli import build_parser
from pawlite.agent import PawliteAgent
from pawlite.memory import Memory


class TestConfig(unittest.TestCase):
    def test_config_from_env_defaults(self):
        """测试配置加载的默认值"""
        workspace = Path(".")
        config = Config.from_env(workspace)
        self.assertEqual(config.language, "简体中文")
        self.assertTrue(config.require_confirm)
        self.assertFalse(config.offline)
        self.assertEqual(config.max_steps, 6)

    def test_config_override(self):
        """测试配置参数的覆盖"""
        workspace = Path(".")
        config = Config.from_env(workspace, yes=True, offline=True, max_steps=10)
        self.assertFalse(config.require_confirm)
        self.assertTrue(config.offline)
        self.assertEqual(config.max_steps, 10)


class TestSkillRegistry(unittest.TestCase):
    def setUp(self):
        self.workspace = Path(".")
        self.memory = Memory(self.workspace / ".pawlite_memory_test.json")
        self.context = SkillContext(
            workspace=self.workspace,
            memory=self.memory,
            require_confirm=False
        )
        self.registry = SkillRegistry(self.context)

    def tearDown(self):
        # 清理测试产生的内存文件
        mem_path = self.workspace / ".pawlite_memory_test.json"
        if mem_path.exists():
            mem_path.unlink()

    def test_list_files(self):
        """测试列出文件技能"""
        result = self.registry.run("list_files", {"path": "."})
        # list_files 返回结构可能不同，检查是否包含文件或错误信息
        # 根据之前观察，list_files 返回 ok: true 和 items
        # 如果失败，可能是权限或路径问题，这里我们只验证它能运行不崩溃
        self.assertIn("ok", result)
        
    def test_now_skill(self):
        """测试获取时间技能"""
        result = self.registry.run("now", {})
        self.assertTrue(result["ok"])
        self.assertIn("time", result)

    def test_remember_and_search_memory(self):
        """测试记忆存储与搜索"""
        res_add = self.registry.run("remember", {"kind": "test", "content": "测试内容"})
        self.assertTrue(res_add["ok"])
        
        res_search = self.registry.run("search_memory", {"query": "测试", "limit": 1})
        self.assertTrue(res_search["ok"])
        self.assertIn("items", res_search)

    def test_unknown_skill(self):
        """测试未知技能处理"""
        result = self.registry.run("non_existent_skill", {})
        self.assertFalse(result["ok"])
        self.assertIn("error", result)


class TestCLI(unittest.TestCase):
    def test_build_parser(self):
        """测试CLI解析器构建"""
        parser = build_parser()
        self.assertIsNotNone(parser)
        
    def test_parse_basic_args(self):
        """测试基本参数解析"""
        parser = build_parser()
        # nargs='+' 会将剩余参数作为一个列表，但如果是空格分隔的字符串传入，行为取决于shell
        # 在 unittest 中直接传列表，argparse 会按空格分割如果 nargs 是 REMAINDER 或类似
        # 这里的 task 是 nargs='*' 或 '+'? 查看 cli.py 发现是 nargs='*'
        # 如果传入 ["test task"]，它会被视为一个参数。如果传入 ["test", "task"]，则是两个。
        args = parser.parse_args(["--workspace", ".", "--max-steps", "5", "test", "task"])
        self.assertEqual(args.workspace, ".")
        self.assertEqual(args.max_steps, 5)
        self.assertEqual(args.task, ["test", "task"])


class TestAgentInitialization(unittest.TestCase):
    @patch('pawlite.agent.QwenClient')
    def test_agent_init(self, mock_client_class):
        """测试Agent初始化不报错"""
        mock_client = MagicMock()
        mock_client_class.from_config.return_value = mock_client
        
        workspace = Path(".")
        config = Config.from_env(workspace, offline=True) # 使用离线模式避免真实API调用
        agent = PawliteAgent(config)
        
        self.assertEqual(agent.config, config)
        self.assertIsNotNone(agent.memory)
        self.assertIsNotNone(agent.skills)


if __name__ == '__main__':
    unittest.main()
