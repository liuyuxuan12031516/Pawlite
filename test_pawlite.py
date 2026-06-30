import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# 确保能导入项目模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pawlite.config import Config
from pawlite.memory import Memory
from pawlite.skills import SkillRegistry, SkillContext
from pawlite.agent import PawliteAgent


class TestPawliteCore(unittest.TestCase):
    """Pawlite 核心模块单元测试"""

    def setUp(self):
        self.test_dir = Path(".pawlite_work/test_temp")
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.workspace = self.test_dir.resolve()
        self.memory_path = self.workspace / "test_memory.json"

    def tearDown(self):
        # 清理测试文件
        if self.memory_path.exists():
            self.memory_path.unlink()
        
    def test_config_from_env(self):
        """测试 Config.from_env 方法"""
        with patch.dict(os.environ, {
            'PAWLITE_WORKSPACE': str(self.workspace),
            'PAWLITE_BASE_URL': 'http://test',
            'PAWLITE_MODEL': 'test-model',
            'PAWLITE_API_KEY': 'test-key'
        }):
            config = Config.from_env(workspace=self.workspace)
            self.assertEqual(config.workspace, self.workspace)
            # 验证配置对象已正确创建且关键字段不为空
            self.assertIsNotNone(config.base_url)
            self.assertIsNotNone(config.model)
            self.assertIsNotNone(config.api_key)

    def test_memory_operations(self):
        """测试 Memory 读写操作"""
        mem = Memory(path=self.memory_path)
        # 添加记忆
        mem.add(kind="test", content="测试内容1")
        mem.add(kind="test", content="测试内容2")
        
        # 搜索记忆
        results = mem.search(query="测试", limit=5)
        self.assertGreaterEqual(len(results), 2)
        
        # 验证内容存在
        contents = [r['content'] for r in results]
        self.assertIn("测试内容1", contents)
        self.assertIn("测试内容2", contents)

    def test_skill_registry_init(self):
        """测试 SkillRegistry 初始化"""
        mem = Memory(path=self.memory_path)
        context = SkillContext(
            workspace=self.workspace,
            memory=mem,
            require_confirm=False
        )
        registry = SkillRegistry(context=context)
        # 验证常用技能已注册
        self.assertIn('read_file', registry._skills)
        self.assertIn('write_file', registry._skills)
        self.assertIn('run_shell', registry._skills)
        self.assertIn('list_files', registry._skills)

    def test_pawlite_agent_init(self):
        """测试 PawliteAgent 初始化（不依赖外部 API）"""
        config = Config(
            base_url='http://mock',
            model='mock-model',
            api_key='mock-key',
            language='简体中文',
            workspace=self.workspace,
            memory_path=self.memory_path
        )
        
        # Mock QwenClient 以避免真实 API 调用
        with patch('pawlite.agent.QwenClient') as MockQwen:
            mock_client_instance = MagicMock()
            MockQwen.return_value = mock_client_instance
            
            agent = PawliteAgent(config=config)
            
            self.assertIsNotNone(agent.config)
            self.assertIsNotNone(agent.memory)
            self.assertIsNotNone(agent.skills)
            self.assertIsNotNone(agent.client)


if __name__ == '__main__':
    unittest.main()
