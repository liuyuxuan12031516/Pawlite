import sys
import os
import tempfile
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from pawlite.config import Config
from pawlite.memory import Memory
from pawlite.skills import SkillRegistry, SkillContext
from pawlite.agent import PawliteAgent

def test_config_initialization():
    """测试 Config 初始化"""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        config = Config.from_env(workspace, api_key="test_key", offline=True)
        assert config.api_key == "test_key"
        assert config.workspace == workspace.resolve()
        assert config.offline is True
        print("Config 初始化测试通过")

def test_memory_read_write():
    """测试 Memory 读写"""
    with tempfile.TemporaryDirectory() as tmpdir:
        mem_path = Path(tmpdir) / "memory.json"
        memory = Memory(mem_path)
        
        # 测试添加
        item = memory.add("test_kind", "test_content")
        assert item["kind"] == "test_kind"
        assert item["content"] == "test_content"
        
        # 测试读取
        recent = memory.recent(limit=1)
        assert len(recent) == 1
        assert recent[0]["content"] == "test_content"
        
        # 测试搜索
        hits = memory.search("test_content")
        assert len(hits) == 1
        
        print("Memory 读写测试通过")

def test_skill_registry():
    """测试 SkillRegistry 注册和基本功能"""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        mem_path = workspace / "memory.json"
        memory = Memory(mem_path)
        context = SkillContext(
            workspace=workspace,
            memory=memory,
            require_confirm=False
        )
        registry = SkillRegistry(context)
        
        # 测试 manifest
        manifest = registry.manifest
        assert isinstance(manifest, list)
        assert len(manifest) > 0
        
        # 测试 now 技能
        result = registry.run("now", {})
        assert result["ok"] is True
        assert "time" in result
        
        # 测试 list_files 技能
        result = registry.run("list_files", {"path": "."})
        assert result["ok"] is True
        
        print("SkillRegistry 测试通过")

def test_agent_initialization():
    """测试 PawliteAgent 初始化"""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        config = Config.from_env(workspace, api_key="test_key", offline=True)
        agent = PawliteAgent(config)
        
        assert agent.config == config
        assert agent.memory is not None
        assert agent.skills is not None
        
        print("PawliteAgent 初始化测试通过")

if __name__ == "__main__":
    try:
        test_config_initialization()
        test_memory_read_write()
        test_skill_registry()
        test_agent_initialization()
        print("\n所有测试用例通过！")
    except Exception as e:
        print(f"\n测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
