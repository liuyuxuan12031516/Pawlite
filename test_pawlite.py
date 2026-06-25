import sys
import os
import json
from pathlib import Path

# 确保可以导入项目模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_config_loading():
    """测试配置加载"""
    try:
        from pawlite.config import Config
        workspace = Path.cwd()
        config = Config.from_env(workspace)
        assert config is not None, "配置对象不应为空"
        assert hasattr(config, 'api_key'), "配置应包含api_key"
        print("[PASS] 配置加载成功")
        return True
    except Exception as e:
        print(f"[FAIL] 配置加载失败: {e}")
        return False

def test_memory_operations():
    """测试记忆读写"""
    try:
        from pawlite.memory import Memory
        test_path = Path(".pawlite_work/test_memory.json")
        test_path.parent.mkdir(parents=True, exist_ok=True)
        mem = Memory(path=test_path)
        
        # 清理旧数据
        if test_path.exists():
            test_path.unlink()
            
        test_content = "test_value_123"
        mem.add(kind="test", content=test_content)
        
        # 验证文件存在且内容正确
        assert test_path.exists(), "记忆文件未创建"
        data = json.loads(test_path.read_text(encoding="utf-8"))
        assert len(data) > 0, "记忆列表为空"
        assert data[-1]['content'] == test_content, "记忆内容不匹配"
        
        print("[PASS] 记忆读写成功")
        return True
    except Exception as e:
        print(f"[FAIL] 记忆操作失败: {e}")
        return False

def test_skill_registration():
    """测试技能注册"""
    try:
        from pawlite.skills import SkillRegistry, SkillContext, Memory
        from pathlib import Path
        
        workspace = Path.cwd()
        memory = Memory(path=workspace / ".pawlite_work/test_skill_memory.json")
        context = SkillContext(workspace=workspace, memory=memory, require_confirm=False)
        registry = SkillRegistry(context=context)
        
        # 验证默认技能已注册
        assert "list_files" in registry._skills, "默认技能 list_files 未注册"
        assert "read_file" in registry._skills, "默认技能 read_file 未注册"
        
        print("[PASS] 技能注册成功")
        return True
    except Exception as e:
        print(f"[FAIL] 技能注册失败: {e}")
        return False

def test_agent_initialization():
    """测试代理初始化"""
    try:
        from pawlite.agent import PawliteAgent
        from pawlite.config import Config
        from pathlib import Path
        
        workspace = Path.cwd()
        config = Config.from_env(workspace)
        # 设置为离线模式或确保有API key，这里主要测试初始化结构
        # 如果没API key，初始化可能会在client处失败，但我们只测到skills注册
        agent = PawliteAgent(config=config)
        
        assert agent.config is not None, "代理配置不应为空"
        assert agent.skills is not None, "代理技能注册器不应为空"
        assert agent.memory is not None, "代理记忆模块不应为空"
        
        print("[PASS] 代理初始化成功")
        return True
    except Exception as e:
        print(f"[FAIL] 代理初始化失败: {e}")
        return False

if __name__ == "__main__":
    results = []
    results.append(test_config_loading())
    results.append(test_memory_operations())
    results.append(test_skill_registration())
    results.append(test_agent_initialization())
    
    if all(results):
        print("\n所有测试通过！")
    else:
        print("\n存在失败的测试，请检查日志。")
        sys.exit(1)