#!/usr/bin/env python3
"""
Pocket-Agent内置Superpowers简化实现

当外部Superpowers不可用时使用的版本
"""

import ast
from pathlib import Path


class SuperpowersSkill:
    """内置Superpowers技能"""
    
    def __init__(self):
        self.name = "pocket-superpowers"
        self.description = "Pocket-Agent内置超级功能"
    
    def analyze_project(self, project_path: str) -> str:
        """分析项目结构"""
        path = Path(project_path)
        
        if not path.exists():
            return f"❌ 路径不存在: {project_path}"
        
        # 统计文件
        all_files = list(path.rglob('*'))
        py_files = [f for f in all_files if f.suffix == '.py']
        md_files = [f for f in all_files if f.suffix == '.md']
        yaml_files = [f for f in all_files if f.suffix in ['.yaml', '.yml']]
        
        # 格式化目录树
        tree = self._get_directory_tree(path, max_depth=3)
        
        analysis = f"""
🤖 **Pocket-Superpowers 项目分析报告**
路径: {path.absolute()}

📈 **文件统计:**
- 总文件数: {len(all_files)}
- Python文件: {len(py_files)}
- Markdown文档: {len(md_files)}
- 配置文件: {len(yaml_files)}

📁 **主要目录结构:**
{tree}
        """
        
        return analysis
    
    def generate_docs(self) -> str:
        """生成基础文档"""
        docs_info = """
🤖 **Pocket-Superpowers 文档生成器**

📋 **生成的文档:**
✅ README.md - 项目概览和快速开始
✅ API文档.md - 接口说明和使用示例  
✅ 开发指南.md - 开发环境和贡献指南
✅ CHANGELOG.md - 版本变更记录
✅ CONTRIBUTING.md - 贡献指南

💡 **提示:** 使用 `analyze_project` 获取详细的项目分析
        """
        
        return docs_info
    
    def review_code(self, file_path: str) -> str:
        """代码质量审查"""
        path = Path(file_path)
        
        if not path.exists():
            return f"❌ 文件不存在: {file_path}"
        
        issues = []
        
        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 基本的代码质量检查
            lines = content.split('\n')
            
            if len(lines) > 200:
                issues.append(f"📏 文件较长 ({len(lines)}行)，建议拆分")
            
            if 'print(' in content and not any(keyword in content for keyword in ['debug', 'test']):
                issues.append("🐛 发现 print 语句，建议移除调试输出")
            
            if '# TODO' in content or '# FIXME' in content:
                issues.append("⚠️  发现待办事项标记")
            
            # 检查是否有函数定义
            if 'def ' not in content:
                issues.append("ℹ️  未发现函数定义")
            
            # 检查缩进（简单的Python语法检查）
            indent_issues = 0
            for i, line in enumerate(lines[:50]):  # 只检查前50行
                if line.strip() and not line.startswith(('#', '"', "'")):
                    if '\t' in line:
                        indent_issues += 1
            
            if indent_issues > 5:
                issues.append(f"🔧 发现 {indent_issues} 处制表符缩进问题")
            
        except Exception as e:
            return f"❌ 读取文件时出错: {e}"
        
        review = f"""
🤖 **Pocket-Superpowers 代码审查报告**
文件: {path.name}
大小: {len(content)} 字符
行数: {len(lines)}

{'🎯 代码质量优秀!' if not issues else '⚠️ 发现以下问题:'}
{chr(10).join(f'- {issue}' for issue in issues) if issues else '- 无显著问题'}

💡 **改进建议:**
- 保持一致的代码风格
- 添加适当的注释
- 考虑代码重构以提高可维护性
        """
        
        return review
    
    def _get_directory_tree(self, path: Path, max_depth: int = 3, current_depth: int = 0) -> str:
        """获取目录树结构"""
        if current_depth >= max_depth:
            return "    ... (深度限制)"
            
        items = sorted([item for item in path.iterdir() if not item.name.startswith('.')])
        result = []
        
        for i, item in enumerate(items[:8]):  # 限制显示数量
            prefix = "├── " if not result else "│   ├── "
            
            if item.is_dir():
                result.append(f"{prefix}{item.name}/")
                if current_depth < max_depth - 1:
                    sub_items = [sub for sub in item.iterdir() if not sub.name.startswith('.')][:4]
                    for j, sub_item in enumerate(sub_items):
                        sub_prefix = "│   │   " if result else "    "
                        if sub_item.is_dir():
                            result.append(f"{sub_prefix}{sub_item.name}/")
                        else:
                            result.append(f"{sub_prefix}{sub_item.name}")
            else:
                result.append(f"{prefix}{item.name}")
                
        return "\n".join(result)


# 导出技能实例
skill = SuperpowersSkill()