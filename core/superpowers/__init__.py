#!/usr/bin/env python3
"""
Superpowers 技能集成模块
从 markdown skill 文件加载真正的 skills，支持懒加载（按需加载）
"""

import os
import re
import functools
from pathlib import Path


class Skill:
    """技能基类 - 支持懒加载"""

    def __init__(self, name: str, description: str, path: str, skill_type: str = "markdown"):
        self.name = name
        self.description = description
        self.path = path  # 技能文件路径，懒加载用
        self.skill_type = skill_type  # markdown / python
        self._content = None  # 懒加载的内容
        self._executable = None  # 懒加载的可执行函数
        self._loaded = False  # 是否已加载

    @property
    def content(self):
        if not self._loaded:
            self._load()
        return self._content
    
    @property
    def executable(self):
        if not self._loaded:
            self._load()
        return self._executable

    def _load(self):
        """实际加载技能内容"""
        if self._loaded:
            return
        
        try:
            if self.skill_type == "markdown":
                with open(self.path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # 解析内容（只保留body部分，去掉已经解析过的frontmatter）
                if content.startswith('---'):
                    parts = content.split('---', 2)
                    if len(parts) >= 3:
                        self._content = parts[2].strip()
                    else:
                        self._content = content
                else:
                    self._content = content
                    
            elif self.skill_type == "python":
                import importlib.util
                module_name = Path(self.path).stem
                spec = importlib.util.spec_from_file_location(module_name, self.path)
                if not spec or not spec.loader:
                    raise Exception(f"无法加载Python模块: {self.path}")
                
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                
                # 优先查找register方法，或者直接查找main函数
                self._executable = None
                
                if hasattr(module, 'register'):
                    register_result = module.register()
                    if isinstance(register_result, dict):
                        self._executable = register_result.get('executable', None)
                elif hasattr(module, 'main'):
                    self._executable = module.main
                
                if not self._executable:
                    raise Exception(f"Python技能 {self.name} 没有可执行入口")
            
            self._loaded = True
            print(f"⚡ 懒加载技能: {self.name}")
            
        except Exception as e:
            self._content = f"加载失败: {e}"
            self._executable = None
            self._loaded = True

    def help(self) -> str:
        return f"**{self.name}**\n{self.description}\n\n详见 skill 文件内容。"
    
    def __call__(self, *args, **kwargs):
        """支持直接调用技能"""
        if self.skill_type == "python" and self.executable:
            return self.executable(*args, **kwargs)
        return f"技能 {self.name} 已加载，内容预览：\n\n{self.content[:1000]}..."


def scan_skill_metadata(skill_path: str) -> Skill:
    """只扫描技能元数据，不加载内容（用于懒加载）"""
    try:
        # 是目录型技能（SKILL.md）
        if os.path.isdir(skill_path):
            skill_file = os.path.join(skill_path, "SKILL.md")
            if not os.path.exists(skill_file):
                return None
            
            # 只读取前100行解析frontmatter，不加载完整内容
            with open(skill_file, 'r', encoding='utf-8') as f:
                # 最多读100行，保证只读到frontmatter结束
                lines = []
                frontmatter_end = -1
                for i, line in enumerate(f):
                    lines.append(line)
                    if i > 0 and line.strip() == '---':
                        frontmatter_end = i
                        break
                    if i >= 100:
                        break
                
                content = ''.join(lines)
                name = Path(skill_path).name
                description = ""

                if content.startswith('---') and frontmatter_end > 0:
                    frontmatter = content.split('---', 2)[1]
                    for line in frontmatter.strip().split('\n'):
                        if line.startswith('name:'):
                            name = line.split(':', 1)[1].strip()
                        elif line.startswith('description:'):
                            description = line.split(':', 1)[1].strip()
            
            return Skill(name, description, skill_file, skill_type="markdown")
        
        # 是单文件Python技能
        elif skill_path.endswith('.py') and not os.path.basename(skill_path).startswith('_'):
            module_name = Path(skill_path).stem
            # 读取文件头的docstring作为描述
            description = ""
            with open(skill_path, 'r', encoding='utf-8') as f:
                first_line = f.readline()
                if first_line.startswith(('"""', "'''")):
                    # 读取docstring
                    docstring = []
                    quote_type = first_line[:3]
                    for line in f:
                        if line.strip().endswith(quote_type):
                            break
                        docstring.append(line.strip())
                    description = ' '.join(docstring)
            
            return Skill(module_name, description, skill_path, skill_type="python")
        
        return None
    
    except Exception as e:
        print(f"⚠️ 扫描技能元数据失败 {skill_path}: {e}")
        return None


class PocketSuperpowers:
    """Pocket-Agent 的 Superpowers 集成 - 支持懒加载（按需加载）"""

    def __init__(self, skills_dir: str = None, lazy_load: bool = True):
        self.skills: dict = {}
        self.skills_dir = skills_dir or self._find_skills_dir()
        self.lazy_load = lazy_load  # 是否启用懒加载
        self._scan_skills()
        if not lazy_load:
            # 非懒加载模式，启动时全量加载
            self._load_all_skills()

    def _find_skills_dir(self) -> str:
        """查找 skills 目录"""
        # 尝试多个位置
        candidates = [
            os.path.join(os.path.dirname(__file__), "..", "..", "skills"),
            "/storage/emulated/0/手机agent开发/Pocket-Agent/skills",
            os.path.expanduser("~/.hermes/skills"),
        ]
        for path in candidates:
            if os.path.exists(path):
                return path
        return ""

    def _scan_skills(self):
        """只扫描所有技能的元数据，不加载内容（懒加载模式）"""
        if not self.skills_dir:
            print("⚠️ 未找到 skills 目录")
            return

        # 扫描目录型技能（SKILL.md）
        for item in os.listdir(self.skills_dir):
            skill_path = os.path.join(self.skills_dir, item)
            if os.path.isdir(skill_path):
                skill = scan_skill_metadata(skill_path)
                if skill:
                    self.add_skill(skill)
        
        # 扫描单文件Python技能
        for item in os.listdir(self.skills_dir):
            skill_path = os.path.join(self.skills_dir, item)
            if item.endswith('.py') and not item.startswith('_'):
                skill = scan_skill_metadata(skill_path)
                if skill:
                    self.add_skill(skill)

    def _load_all_skills(self):
        """全量加载所有技能内容（非懒加载模式）"""
        for skill in self.skills.values():
            skill._load()
        print(f"✅ 全量加载完成，共 {len(self.skills)} 个技能")

    def add_skill(self, skill: Skill) -> bool:
        """动态添加技能"""
        if skill.name in self.skills:
            print(f"⚠️ 技能 {skill.name} 已存在，将被覆盖")
        
        self.skills[skill.name] = skill
        
        # 动态绑定方法到实例，支持直接调用：pocket_superpowers.skill_name()
        @functools.wraps(skill.__call__)
        def skill_method(*args, **kwargs):
            return skill(*args, **kwargs)
        
        setattr(self, skill.name, skill_method)
        if not self.lazy_load:
            print(f"✅ 加载技能: {skill.name}")
        else:
            print(f"🔍 发现技能: {skill.name}")
        return True
    
    def remove_skill(self, skill_name: str) -> bool:
        """动态移除技能"""
        if skill_name not in self.skills:
            print(f"⚠️ 技能 {skill_name} 不存在")
            return False
        
        del self.skills[skill_name]
        if hasattr(self, skill_name):
            delattr(self, skill_name)
        print(f"🗑️  移除技能: {skill_name}")
        return True
    
    def reload_skills(self) -> None:
        """重新加载所有技能"""
        self.skills.clear()
        # 清除所有动态绑定的技能方法
        for attr in list(self.__dict__.keys()):
            if attr not in ['skills', 'skills_dir', 'lazy_load'] and not attr.startswith('_'):
                delattr(self, attr)
        self._scan_skills()
        if not self.lazy_load:
            self._load_all_skills()
        print(f"🔄 技能重新加载完成，共发现 {len(self.skills)} 个技能")

    def get_skill(self, name: str) -> Skill:
        """获取指定技能"""
        return self.skills.get(name)
    
    def list_skills(self) -> list:
        """列出所有已发现的技能（不需要加载内容）"""
        return [
            {"name": s.name, "description": s.description, "type": s.skill_type, "loaded": s._loaded}
            for s in self.skills.values()
        ]
    
    def execute_skill(self, skill_name: str, *args, **kwargs):
        """统一调用入口：执行指定技能"""
        skill = self.get_skill(skill_name)
        if not skill:
            return f"❌ 技能 {skill_name} 不存在"
        return skill(*args, **kwargs)
    
    def __getattr__(self, name):
        """动态属性访问，当技能不存在时友好提示"""
        if name.startswith('_'):
            raise AttributeError(f"'PocketSuperpowers' object has no attribute '{name}'")
        # 尝试查找技能
        skill = self.get_skill(name)
        if skill:
            return skill
        # 提示可用技能
        available = ", ".join(self.skills.keys())
        raise AttributeError(f"技能 '{name}' 不存在，可用技能：{available}")


# 全局实例 - 默认启用懒加载
pocket_superpowers = PocketSuperpowers(lazy_load=True)
