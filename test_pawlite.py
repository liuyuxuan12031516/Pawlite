#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Pawlite 项目核心模块测试脚本
验证配置加载、记忆读写、技能注册及基础代理实例化。
"""
import sys
import os
from pathlib import Path

# 确保可以导入 pawlite 包
sys.path.insert(0, str(Path(__file__).parent))

def test_config():
    """测试配置模块"""
    from pawlite.config import Config
    workspace = Path.cwd()
    # 使用离线模式或模拟 API Key 以避免网络请求，这里主要测试结构
    config = Config.from_env(
        workspace=workspace,
        api_key="test_key_for_structure_check",
        yes=True, # 跳过确认
        offline=True
    )
    assert config.workspace == workspace.resolve(), "工作区路径解析错误"
    assert config.api_key == "test_key_for_structure_check", "API Key 未正确设置"
    assert config.require_confirm is False, "yes 参数未生效"
    print("[PASS] Config 模块测试通过")
    return config

def test_memory():
    """测试记忆模块"""
    from pawlite.memory import Memory
    import tempfile
    import json
    
    with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as tmp:
        mem_path = Path(tmp.name)
    
    try:
        memory = Memory(path=mem_path)
        
        # 测试添加记忆
        item = memory.add(kind="test", content="测试内容1")
        assert "time" in item, "记忆项缺少时间戳"
        assert item["kind"] == "test", "记忆种类不匹配"
        
        # 测试读取最近记忆
        recent = memory.recent(limit=1)
        assert len(recent) == 1, "最近记忆读取失败"
        assert recent[0]["content"] == "测试内容1", "记忆内容不匹配"
        
        # 测试搜索记忆
        hits = memory.search(query="测试内容1")
        assert len(hits) >= 1, "记忆搜索失败"
        
        print("[PASS] Memory 模块测试通过")
    finally:
        if mem_path.exists():
            mem_path.unlink()

def test_skills():
    """测试技能注册表"""
    from pawlite.skills import SkillRegistry, SkillContext
    from pawlite.memory import Memory
    import tempfile
    from pathlib import Path

    with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as tmp:
        mem_path = Path(tmp.name)
    
    workspace = Path.cwd()
    memory = Memory(path=mem_path)
    context = SkillContext(
        workspace=workspace,
        memory=memory,
        require_confirm=False
    )
    registry = SkillRegistry(context=context)
    
    # 测试技能清单
    manifest = registry.manifest
    assert isinstance(manifest, list), "技能清单格式错误"
    skill_names = [s['name'] for s in manifest]
    assert 'read_file' in skill_names, "缺少 read_file 技能"
    assert 'run_shell' in skill_names, "缺少 run_shell 技能"
    
    # 测试执行一个简单技能 (now)
    result = registry.run(name="now", args={})
    assert result.get("ok") is True, "执行 now 技能失败"
    
    print("[PASS] Skills 模块测试通过")
    
    if mem_path.exists():
        mem_path.unlink()

def test_agent_init():
    """测试代理初始化"""
    from pawlite.agent import PawliteAgent
    from pawlite.config import Config
    
    workspace = Path.cwd()
    config = Config.from_env(
        workspace=workspace,
        api_key="test_key",
        yes=True,
        offline=True
    )
    
    # 在离线模式下，Agent 初始化不应报错，即使没有真实的 LLM 连接
    agent = PawliteAgent(config=config)
    assert agent.config == config, "Agent 配置未正确绑定"
    assert agent.skills is not None, "Agent 技能注册表未初始化"
    
    print("[PASS] Agent 初始化测试通过")

if __name__ == "__main__":
    print("开始运行 Pawlite 核心模块测试...")
    try:
        test_config()
        test_memory()
        test_skills()
        test_agent_init()
        print("\n所有测试通过！项目核心模块功能正常。")
    except Exception as e:
        print(f"\n测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
