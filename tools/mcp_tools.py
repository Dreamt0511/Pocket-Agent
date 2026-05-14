#!/usr/bin/env python3
"""
MCP 工具封装 - NeuralBridge Android 控制
自动从MCP服务器获取工具列表，动态生成工具封装，无需手动维护
"""

import json
import requests
import functools
import os
from typing import Optional, List, Dict, Any, Callable

NEURALBRIDGE_MCP_URL = os.getenv("NEURALBRIDGE_MCP_URL", "http://127.0.0.1:7474/mcp")
CONTEXT7_MCP_URL = os.getenv("CONTEXT7_MCP_URL", "http://127.0.0.1:3007/mcp")

def tool(name: str, description: str, parameters: Dict[str, Any]):
    """工具装饰器（保持原有接口不变）"""
    def decorator(func):
        func._tool_info = {
            "name": name,
            "description": description,
            "parameters": parameters,
        }
        return func
    return decorator


def mcp_call(tool_name: str, **kwargs) -> str:
    """
    调用 MCP 工具（通过 Hermes Agent 运行时注入）
    保持原有逻辑不变
    """
    return f"[MCP:{tool_name}] {json.dumps(kwargs, ensure_ascii=False)}"


def _fetch_mcp_tools(server_url: str) -> List[Dict[str, Any]]:
    """从指定MCP服务器获取所有工具定义"""
    try:
        resp = requests.post(
            server_url,
            headers={"Content-Type": "application/json"},
            json={
                "jsonrpc": "2.0",
                "method": "tools/list",
                "id": 1
            },
            timeout=10
        )
        resp.raise_for_status()
        return resp.json()["result"]["tools"]
    except Exception as e:
        print(f"⚠️ 获取MCP工具列表失败({server_url}): {str(e)}，将跳过该服务")
        return []


def _create_tool_function(tool_def: Dict[str, Any]) -> Callable:
    """根据工具定义动态生成工具函数"""
    tool_name = tool_def["name"]
    description = tool_def["description"]
    input_schema = tool_def["inputSchema"]
    properties = input_schema.get("properties", {})
    required = input_schema.get("required", [])
    
    # JSON Schema类型到Python类型的映射
    type_map = {
        "string": "str",
        "integer": "int",
        "boolean": "bool",
        "number": "float",
        "array": "list",
        "object": "dict"
    }
    
    # 生成函数签名
    parameters = []
    defaults = []
    for param_name, param_def in properties.items():
        param_type = type_map.get(param_def.get("type", "any"), "Any")
        # 生成参数注释
        param_desc = param_def.get("description", "")
        parameters.append(f"{param_name}: Optional[{param_type}] = None" if param_name not in required else f"{param_name}: {param_type}")
        if param_name not in required:
            defaults.append(None)
    
    # 构建函数体
    func_code = f"""
def {tool_name}({', '.join(parameters)}):
    \"\"\"{description}\"\"\"
    params = {{k: v for k, v in locals().items() if v is not None}}
    return mcp_call("{tool_name}", **params)
    """
    
    # 执行代码生成函数
    local_vars = {}
    exec(func_code, globals(), local_vars)
    func = local_vars[tool_name]
    
    # 应用tool装饰器
    decorated_func = tool(
        name=tool_name,
        description=description,
        parameters=input_schema
    )(func)
    
    return decorated_func


# 动态加载所有MCP工具（同时加载NeuralBridge和context7两个服务）
_all_tools = []
# 加载NeuralBridge工具
_neuralbridge_tools = _fetch_mcp_tools(NEURALBRIDGE_MCP_URL)
_all_tools.extend(_neuralbridge_tools)
# 加载context7工具
_context7_tools = _fetch_mcp_tools(CONTEXT7_MCP_URL)
_all_tools.extend(_context7_tools)

for _tool_def in _all_tools:
    _tool_func = _create_tool_function(_tool_def)
    # 将函数注册到模块全局命名空间
    globals()[_tool_def["name"]] = _tool_func


# 导出所有工具名称（用于外部遍历）
__all__ = [_tool_def["name"] for _tool_def in _all_tools] + ["tool", "mcp_call"]

# 导出所有工具函数列表（供init.py加载）
ALL_MCP_TOOLS = [globals()[name] for name in __all__ if name not in ["tool", "mcp_call"]]
