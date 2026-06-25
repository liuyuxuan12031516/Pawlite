import sys
import os
import json
from pathlib import Path

# 确保能导入 pawlite 模块
sys.path.insert(0, str(Path(__file__).parent))

def test_config():
    """测试配置加载"""
    from pawlite.config import Config
    # Config 没有 load 方法，使用 from_env
    cfg = Config.from_env(workspace=Path("."))
    assert cfg is not None, "Config load failed"
    assert hasattr(cfg, 'api_key'), "Config missing api_key"
    print("[PASS] Config loaded successfully")
    return True

def test_memory():
    """测试记忆读写"""
    from pawlite.memory import Memory
    mem_path = Path(".pawlite_work/test_mem.json")
    mem = Memory(path=mem_path)
    mem.add(kind="test", content="test_value")
    results = mem.search(query="test_value")
    assert len(results) > 0, "Memory search failed"
    assert results[0]["content"] == "test_value", "Memory content mismatch"
    # 清理测试文件
    if mem_path.exists():
        mem_path.unlink()
    print("[PASS] Memory read/write successful")
    return True

def test_skills_registry():
    """测试技能注册"""
    from pawlite.skills import SkillRegistry, SkillContext
    from pawlite.memory import Memory
    
    # 构造必要的上下文
    mem = Memory(path=Path(".pawlite_work/dummy_mem.json"))
    context = SkillContext(
        workspace=Path("."),
        memory=mem,
        require_confirm=False
    )
    registry = SkillRegistry(context=context)
    
    # 检查内置技能是否注册 (通过 manifest 或内部 _skills)
    assert "list_files" in registry._skills, "list_files skill missing"
    assert "read_file" in registry._skills, "read_file skill missing"
    print("[PASS] Skills registry initialized correctly")
    return True

def main():
    print("Starting Pawlite Tests...")
    tests = [
        test_config,
        test_memory,
        test_skills_registry
    ]
    passed = 0
    failed = 0
    for test in tests:
        try:
            if test():
                passed += 1
        except Exception as e:
            print(f"[FAIL] {test.__name__}: {str(e)}")
            failed += 1
    
    print(f"\nResults: {passed} passed, {failed} failed")
    return failed == 0

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)