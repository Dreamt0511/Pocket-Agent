#!/usr/bin/env python3
"""
【主版本】基于LangChain官方create_agent实现 - 参考EchoMind架构
✅  内置工具调用限制，解决递归死循环问题
✅  性能优异，智能性更高
✅  完全兼容原有接口
"""

import os
import json
import re
import subprocess
import asyncio
from datetime import datetime
from typing import List, Tuple, Dict, Any, Optional, Callable, Awaitable, AsyncGenerator
from langchain_core.tools import StructuredTool
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, AIMessageChunk, ToolMessage, RemoveMessage
from langgraph.checkpoint.memory import MemorySaver
from langchain_openai import ChatOpenAI
from .memory import LongTermMemory
from langchain.agents.middleware import ModelCallLimitMiddleware, SummarizationMiddleware, wrap_tool_call
from langchain.agents.middleware.types import AgentMiddleware, ModelResponse
from langchain_core.messages.utils import count_tokens_approximately
from .config import (
    MAX_ITERATIONS,
    RECURSION_LIMIT,
    MAX_CONTEXT_TOKENS,
    SKILLS_DIR,
    SKILL_FILE_NAMES,
    TERMUX_API_CHECK_CMD,
    TERMUX_API_INSTALL_GUIDE,
    ENV_LIGHT_SENSOR_CMD,
    ENV_ACCEL_SENSOR_CMD,
    ENV_TIME_CMD,
    ENV_TIMEZONE_CMD,
    PROJECT_ROOT,
    TASKS_DIR,
    LOGS_DIR,
    EXECUTOR_SKILLS_DIR,
    AUTO_SKILLS_DIR,
    EXECUTOR_LLM_CONFIG,
)
from .prompts.agent_enhance import prompt as agent_enhance_prompt
from .logger import AgentLogger
from .tools.basic_tools import ALL_TOOLS, set_memory_instance, consume_pending_tasks, set_current_conversation_id
from .prompts.executor_system import executor_system_prompt
from .prompts.executor_enhance import prompt as executor_enhance_prompt


# ── 技能加载工具 ──────────────────────────────────────────────
def _read_skill_desc(skill_path: str) -> str:
    """读取SKILL.md前20行中的description字段"""
    try:
        with open(skill_path, 'r', encoding='utf-8') as f:
            for _ in range(20):
                line = f.readline()
                if not line:
                    break
                if line.startswith("description:"):
                    return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return ""


def _scan_skills(scan_dir: str) -> list:
    """
    扫描指定目录下的所有技能，支持单层嵌套分类。
    返回 (category_name, skill_name, desc, skill_path) 元组列表。
    - 如果子目录直接含 SKILL.md → flat 模式，category_name 为空
    - 如果子目录含再下一级子目录有 SKILL.md → category 模式
    """
    results = []
    for entry in sorted(os.listdir(scan_dir)):
        entry_path = os.path.join(scan_dir, entry)
        if not os.path.isdir(entry_path):
            continue

        # 检查 entry 是否直接是技能（含 SKILL.md）
        skill_file = None
        for fn in SKILL_FILE_NAMES:
            candidate = os.path.join(entry_path, fn)
            if os.path.exists(candidate):
                skill_file = candidate
                break

        if skill_file:
            desc = _read_skill_desc(skill_file)
            results.append(("", entry, desc, skill_file))
            continue

        # 否则检查 entry 下的子目录是否有技能（category 模式）
        sub_skills = []
        for sub_entry in sorted(os.listdir(entry_path)):
            sub_path = os.path.join(entry_path, sub_entry)
            if not os.path.isdir(sub_path):
                continue
            for fn in SKILL_FILE_NAMES:
                candidate = os.path.join(sub_path, fn)
                if os.path.exists(candidate):
                    desc = _read_skill_desc(candidate)
                    sub_skills.append((sub_entry, desc, candidate))
                    break

        if sub_skills:
            for name, desc, skill_path in sub_skills:
                results.append((entry, name, desc, skill_path))

    return results


def load_skills_list(agent_type: str = "main") -> str:
    """
    根据agent类型加载对应技能列表
    Args:
        agent_type: "main" → main-skills/ 目录, "executor" → executor-skills/ + auto-skills/executor/
    """
    skills_dir = SKILLS_DIR if agent_type == "main" else EXECUTOR_SKILLS_DIR

    if not os.path.exists(skills_dir):
        return "暂无可用技能。"

    skills = _scan_skills(skills_dir)

    # executor 额外加载自动沉淀技能，和主Agent统一写法
    if agent_type == "executor":
        auto_dir = os.path.join(AUTO_SKILLS_DIR, "executor")
        if os.path.exists(auto_dir):
            skills.extend(_scan_skills(auto_dir))

    if not skills:
        return "暂无可用技能。"

    # 按分类分组输出
    categories = {}
    for cat, name, desc, skill_path in skills:
        categories.setdefault(cat, []).append((name, desc, skill_path))

    lines = []
    for cat, skill_list in categories.items():
        if cat:
            lines.append(f"\n【{cat}】")
        for name, desc, skill_path in skill_list:
            entry = f"- {name}: {desc}（路径：{skill_path}）" if desc else f"- {name}（路径：{skill_path}）"
            lines.append(entry)
        if not cat:
            lines.append("")  # 空行分隔无分类和有分类

    skills_text = "\n".join(lines).strip()
    # 用第一个技能的实际路径作为示例
    first_path = skills[0][3] if skills else ""
    if not first_path:
        first_path = os.path.join(skills_dir, "example", "SKILL.md")
    usage_note = f"\n\n使用说明：需要使用某个技能时，用file_read读取对应SKILL.md即可，例如：file_read(filepath='{first_path}')"

    return skills_text + usage_note


# ── 工具初始化 ──────────────────────────────────────────────
# 从basic_tools导入的ALL_TOOLS已经是@tool装饰的函数，直接使用即可




# ── DeepSeek reasoning_content 兼容补丁 ──────────────────────────────
# LangChain 的 ChatOpenAI 不支持非标准 API 字段（文档写明），导致：
# 1. 流式响应中的 reasoning_content 被 _convert_delta_to_message_chunk 丢弃
# 2. additional_kwargs 中的字段不被 _convert_message_to_dict 传回 API
# 两处 monkey-patch 确保 reasoning_content 在请求-响应周期中完整保留。
import langchain_openai.chat_models.base as _chat_base

# Patch 1: 流式响应中捕获 reasoning_content 存入 additional_kwargs
_original_convert_delta = _chat_base._convert_delta_to_message_chunk

def _patched_convert_delta(_dict, default_class):
    chunk = _original_convert_delta(_dict, default_class)
    if isinstance(chunk, AIMessageChunk):
        rc = _dict.get("reasoning_content")
        if rc:
            chunk.additional_kwargs["reasoning_content"] = rc
    return chunk

_chat_base._convert_delta_to_message_chunk = _patched_convert_delta

# Patch 2: 发送消息时把 additional_kwargs 中的 reasoning_content 传给 API
_original_convert = _chat_base._convert_message_to_dict

def _patched_convert_message_to_dict(message, api="chat/completions"):
    result = _original_convert(message, api)
    if isinstance(message, AIMessage):
        for key in ('reasoning_content',):
            if key in message.additional_kwargs:
                result[key] = message.additional_kwargs[key]
    return result

_chat_base._convert_message_to_dict = _patched_convert_message_to_dict
# ──────────────────────────────────────────────────────────────────────


# ── 工具调用ID修复中间件 ──────────────────────────────────────────────
# 某些LLM（如GLM系列）生成的tool_call缺少id字段，
# 导致LangGraph的ToolNode创建ToolMessage时tool_call_id为空报错
import uuid


class ToolCallIdMiddleware(AgentMiddleware):
    """确保所有工具调用都有有效的id字段"""

    def wrap_model_call(self, request, handler):
        response = handler(request)
        return self._fix_tool_call_ids(response)

    async def awrap_model_call(self, request, handler):
        response = await handler(request)
        return self._fix_tool_call_ids(response)

    def _fix_tool_call_ids(self, response):
        result = list(response.result)
        modified = False
        for i, msg in enumerate(result):
            if isinstance(msg, AIMessage) and hasattr(msg, 'tool_calls') and msg.tool_calls:
                fixed_calls = []
                for tc in msg.tool_calls:
                    if not tc.get("id") or not isinstance(tc["id"], str) or tc["id"] == "":
                        tc = dict(tc)
                        tc["id"] = f"call_{uuid.uuid4().hex[:12]}"
                        fixed_calls.append(tc)
                        modified = True
                    else:
                        fixed_calls.append(tc)
                if modified:
                    result[i] = AIMessage(
                        content=msg.content,
                        tool_calls=fixed_calls,
                        additional_kwargs=msg.additional_kwargs,
                        response_metadata=msg.response_metadata,
                        id=msg.id,
                    )
        if modified:
            return ModelResponse(result=result, structured_response=response.structured_response)
        return response


class ImageOptimizationMiddleware(AgentMiddleware):
    """优化多模态消息中的图片内容，避免图片base64数据累积导致token溢出"""

    def wrap_model_call(self, request, handler):
        # 处理请求中的历史消息，移除所有图片base64数据
        self._remove_image_content(request.messages)
        response = handler(request)
        return response

    async def awrap_model_call(self, request, handler):
        # 处理请求中的历史消息，移除所有图片base64数据
        self._remove_image_content(request.messages)
        response = await handler(request)
        return response

    def _remove_image_content(self, messages):
        """
        移除所有消息中的图片base64数据，替换为文本描述
        彻底避免图片数据累积导致token溢出
        """
        import re
        for msg in messages:
            if hasattr(msg, 'content'):
                # 处理纯文本格式，移除Markdown图片的base64
                if isinstance(msg.content, str):
                    content = msg.content
                    # 匹配Markdown图片格式：![alt](data:image/...;base64,...)
                    markdown_img_pattern = r'!\[.*?\]\(data:image/[^)]+\)'
                    if re.search(markdown_img_pattern, content):
                        # 把图片替换为文本描述
                        msg.content = re.sub(markdown_img_pattern, '[截图已保存]', content).strip()

                # 处理多模态列表格式，移除图片数据
                if isinstance(msg.content, list):
                    optimized_content = []
                    for item in msg.content:
                        if isinstance(item, dict):
                            # 处理OpenAI格式image_url类型
                            if item.get("type") == "image_url":
                                # 图片替换为文本
                                optimized_content.append({
                                    "type": "text",
                                    "text": "[截图已保存]"
                                })
                            # 处理MCP标准image类型
                            elif item.get("type") == "image":
                                # 图片替换为文本
                                optimized_content.append({
                                    "type": "text",
                                    "text": "[截图已保存]"
                                })
                            else:
                                optimized_content.append(item)
                        else:
                            optimized_content.append(item)
                    msg.content = optimized_content


class MCPToolResultMiddleware(AgentMiddleware):
    """处理MCP工具返回结果，特别是图片数据，转换为正确的多模态格式避免token爆炸"""

    def _process_image_content(self, content):
        """处理图片内容，避免大体积base64导致token超限"""
        import json

        # 处理多模态列表格式的内容
        if isinstance(content, list):
            has_image = False
            image_info = {}
            text_parts = []

            for item in content:
                if isinstance(item, dict):
                    item_type = item.get('type')
                    # 处理文本内容，保留
                    if item_type == 'text' and 'text' in item:
                        text_parts.append(item['text'])
                    # 处理MCP标准image类型
                    elif item_type == 'image' and 'data' in item:
                        has_image = True
                        image_data = item['data'].strip()
                        image_size_kb = len(image_data) * 3 / 4 / 1024
                        image_info['size_kb'] = round(image_size_kb, 2)
                        if 'width' in item:
                            image_info['width'] = item['width']
                        if 'height' in item:
                            image_info['height'] = item['height']
                    # 处理OpenAI格式image_url类型
                    elif item_type == 'image_url' and 'image_url' in item:
                        url = item['image_url'].get('url', '')
                        if url.startswith('data:image/') or url.startswith('/9j/') or url.startswith('iVBORw0KGgo'):
                            has_image = True
                            image_size_kb = len(url) * 3 / 4 / 1024
                            image_info['size_kb'] = round(image_size_kb, 2)

            if has_image:
                # 先保留原有的文本内容
                result = []
                if text_parts:
                    result.append("\n".join(text_parts))

                # 添加图片描述
                info_text = "✅ 已成功截取当前页面的截图"
                if image_info:
                    details = []
                    if 'width' in image_info and 'height' in image_info:
                        details.append(f"分辨率：{image_info['width']} x {image_info['height']}")
                    if 'size_kb' in image_info:
                        details.append(f"大小：{image_info['size_kb']} KB")
                    details.append("格式：JPEG")
                    if details:
                        info_text += "，截图参数：\n- " + "\n- ".join(details)
                info_text += "\n\n你可以直接查看生成的截图内容。如果需要分析图片内容，请明确说明。"
                result.append(info_text)

                return "\n\n".join(result)
            return None

        # 处理字符串格式的内容
        if not isinstance(content, str) or not content.strip():
            return None

        content = content.strip()
        is_image = False
        image_info = {}

        # 尝试解析JSON，检测是否是图片返回
        try:
            if content.startswith(('{', '[')):
                data = json.loads(content)

                # 情况1：MCP标准返回格式 {"content": [{"type": "image", "data": "base64"}]}
                if isinstance(data, dict) and 'content' in data:
                    content_list = data['content']
                    if isinstance(content_list, list) and len(content_list) > 0:
                        item = content_list[0]
                        if isinstance(item, dict) and item.get('type') == 'image' and 'data' in item:
                            is_image = True
                            image_data = item['data'].strip()
                            # 估算图片大小
                            image_size_kb = len(image_data) * 3 / 4 / 1024
                            image_info['size_kb'] = round(image_size_kb, 2)
                            # 尝试提取分辨率信息（如果有）
                            if 'width' in item:
                                image_info['width'] = item['width']
                            if 'height' in item:
                                image_info['height'] = item['height']

                # 情况2：其他JSON格式的图片返回
                if not is_image and isinstance(data, dict):
                    for key in ['image', 'screenshot', 'img', 'base64', 'data']:
                        if key in data and isinstance(data[key], str):
                            val = data[key].strip()
                            if val.startswith('/9j/') or val.startswith('iVBORw0KGgo') or val.startswith('data:image/'):
                                is_image = True
                                image_size_kb = len(val) * 3 / 4 / 1024
                                image_info['size_kb'] = round(image_size_kb, 2)
                                break
        except json.JSONDecodeError:
            pass

        # 情况3：纯文本base64图片
        if not is_image:
            if content.startswith("data:image/") or content.startswith('/9j/') or content.startswith('iVBORw0KGgo'):
                is_image = True
                image_size_kb = len(content) * 3 / 4 / 1024
                image_info['size_kb'] = round(image_size_kb, 2)

        if is_image:
            # 【关键优化】不返回图片base64给LLM，直接返回文本描述
            # 避免大体积图片导致token超限，LLM不需要看到图片二进制数据
            info_text = "✅ 已成功截取当前页面的截图"
            if image_info:
                details = []
                if 'width' in image_info and 'height' in image_info:
                    details.append(f"分辨率：{image_info['width']} x {image_info['height']}")
                if 'size_kb' in image_info:
                    details.append(f"大小：{image_info['size_kb']} KB")
                details.append("格式：JPEG")
                if details:
                    info_text += "，截图参数：\n- " + "\n- ".join(details)
            info_text += "\n\n你可以直接查看生成的截图内容。如果需要分析图片内容，请明确说明。"

            # 返回纯文本，不返回图片数据，彻底解决token超限问题
            return info_text
        return None

    def wrap_tool_call(self, request, handler):
        """同步版本的工具调用处理"""
        result = handler(request)

        # 处理ToolMessage中的图片内容
        if isinstance(result, ToolMessage):
            processed_content = self._process_image_content(result.content)
            if processed_content is not None:
                result.content = processed_content

        return result

    async def awrap_tool_call(self, request, handler):
        """异步版本的工具调用处理"""
        result = await handler(request)

        # 处理ToolMessage中的图片内容
        if isinstance(result, ToolMessage):
            processed_content = self._process_image_content(result.content)
            if processed_content is not None:
                result.content = processed_content

        return result


# ── Agent 核心实现 ──────────────────────────────────────────────
class LangChainPocketAgent:
    """
    基于LangChain官方create_agent实现的PocketAgent
    参考EchoMind架构，内置工具调用限制，解决递归死循环问题
    """

    def __init__(
        self,
        system_prompt: str = "",
        llm_config: Dict[str, Any] = None,
        ui=None,
        max_iterations: int = 50,
        checkpointer=None,
    ):
        self.ui = ui
        self.base_system_prompt = system_prompt
        self.max_iterations = max_iterations
        self.llm_config = llm_config or {}
        self.checkpointer = checkpointer

        # 初始化LLM
        self._init_llm()

        # 创建Agent
        self._create_agent()

        # 会话配置：recursion_limit从配置文件读取，作为极端情况的底层兜底
        # 正常情况下max_iterations会先生效，优雅停止；极端情况recursion_limit兜底报错
        self.config = {
            "configurable": {
                "thread_id": "default-session"
            },
            "recursion_limit": RECURSION_LIMIT
        }

        # 暴露工具列表
        self.tools = ALL_TOOLS

        # 环境感知缓存 — 后台刷新，不阻塞对话
        self._cached_env_tag = None
        self._refresh_env_lock = asyncio.Lock()

        # 初始化记忆系统，用于用户画像更新
        self.memory = LongTermMemory(memory_dir=os.path.join(PROJECT_ROOT, "memory"))
        # 设置全局记忆实例，供update_user_profile工具使用
        set_memory_instance(self.memory)
        # 预加载用户画像，只加载一次，避免破坏缓存
        self._user_profile = self.memory.get_user_profile()

        # 初始化日志系统
        self.logger = AgentLogger(log_dir=os.path.join(PROJECT_ROOT, "logs"))
        # 确保任务目录存在
        os.makedirs(TASKS_DIR, exist_ok=True)

        # 后台子Agent执行结果缓存（用于下次对话通知用户）
        self._background_task_results: list[dict] = []

        # 子Agent LLM缓存（复用配置，避免每个任务创建新客户端）
        self._executor_llm = None

        # 子Agent沉淀的新技能列表（待主Agent验证格式）
        self._pending_skill_verification: list[str] = []

    def _run_sensor(self, cmd: str, timeout: int = 5) -> Optional[str]:
        """执行Termux传感器命令，返回stdout或None"""
        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
            return result.stdout.strip() if result.returncode == 0 else None
        except Exception:
            return None

    def _sense_environment(self) -> Optional[str]:
        """采集环境状态，返回自然语言格式的环境标签或None"""
        try:
            # 时间与时区
            time_out = self._run_sensor(ENV_TIME_CMD)
            tz_out = self._run_sensor(ENV_TIMEZONE_CMD)
            if not time_out:
                return None
            hour = int(time_out.split(":")[0])
            tz = tz_out or ""

            descs = []

            # 时段判断
            if hour >= 6 and hour < 12:
                descs.append(f"现在是{time_out}({tz})，上午工作时段")
            elif hour >= 12 and hour < 14:
                descs.append(f"现在是{time_out}({tz})，中午休息时段")
            elif hour >= 14 and hour < 18:
                descs.append(f"现在是{time_out}({tz})，下午工作时段")
            elif hour >= 18 and hour < 22:
                descs.append(f"现在是{time_out}({tz})，傍晚休息时段")
            else:
                descs.append(f"现在是{time_out}({tz})，深夜休息时段")

            # 光照
            light_out = self._run_sensor(ENV_LIGHT_SENSOR_CMD)
            if light_out:
                try:
                    light_data = json.loads(light_out)
                    for v in light_data.values():
                        if isinstance(v, dict) and "values" in v and v["values"]:
                            lux = v["values"][0]
                            if lux < 1:
                                descs.append("环境极暗")
                            elif lux < 50:
                                descs.append("环境较暗")
                            elif lux < 500:
                                descs.append("光线正常，室内")
                            else:
                                descs.append("光线明亮")
                            break
                except json.JSONDecodeError:
                    pass

            # 加速度计判断活动状态
            accel_out = self._run_sensor(ENV_ACCEL_SENSOR_CMD)
            if accel_out:
                try:
                    accel_data = json.loads(accel_out)
                    for v in accel_data.values():
                        if isinstance(v, dict) and "values" in v:
                            vals = v["values"]
                            if len(vals) >= 3:
                                x_vals = vals[0::3][:3]
                                y_vals = vals[1::3][:3]
                                z_vals = vals[2::3][:3]
                                max_diff = max(
                                    max(x_vals) - min(x_vals),
                                    max(y_vals) - min(y_vals),
                                    max(z_vals) - min(z_vals),
                                )
                                if max_diff < 0.3:
                                    descs.append("手机静止，用户可能坐着或没在使用手机")
                                elif max_diff < 2.0:
                                    descs.append("手机有轻微活动")
                                else:
                                    descs.append("手机在移动中，用户可能在走路或活动")
                            break
                except json.JSONDecodeError:
                    pass

            # 电池
            batt_out = self._run_sensor("termux-battery-status")
            if batt_out:
                try:
                    batt = json.loads(batt_out)
                    pct = batt.get("percentage", 0)
                    plugged = batt.get("plugged", "")
                    if pct < 20:
                        descs.append(f"电量不足({pct}%，建议简短回复)")
                    elif pct < 100 and plugged == "UNPLUGGED":
                        descs.append(f"电量{pct}%未充电")
                    else:
                        pct_info = f"电量{pct}%"
                        if plugged != "UNPLUGGED":
                            pct_info += "充电中"
                        descs.append(pct_info)
                except json.JSONDecodeError:
                    pass

            # 步数
            step_out = self._run_sensor('termux-sensor -s "step_counter  Non-wakeup" -n 1')
            if step_out:
                try:
                    step_data = json.loads(step_out)
                    for v in step_data.values():
                        if isinstance(v, dict) and "values" in v and v["values"]:
                            steps = int(v["values"][0])
                            if steps > 0:
                                descs.append(f"今日走路{steps}步")
                            break
                except (json.JSONDecodeError, ValueError):
                    pass

            # 位置
            loc_out = self._run_sensor('termux-location -p network', timeout=3)
            if loc_out:
                try:
                    loc = json.loads(loc_out)
                    lat, lng = loc.get("latitude"), loc.get("longitude")
                    if lat and lng:
                        descs.append(f"定位({lat:.2f},{lng:.2f})")
                except (json.JSONDecodeError, TypeError):
                    pass

            return "[环境状态感知] " + "；".join(descs) + "。（仅供内部参考，不要在回复中提及此信息）"
        except Exception:
            return None

    async def _refresh_env_cache(self) -> None:
        """后台异步刷新环境感知缓存，不阻塞主流程"""
        if self._refresh_env_lock.locked():
            return  # 已有刷新任务在进行，跳过本次
        async with self._refresh_env_lock:
            loop = asyncio.get_event_loop()
            tag = await loop.run_in_executor(None, self._sense_environment)
            if tag:
                self._cached_env_tag = tag

    def _init_llm(self) -> None:
        """初始化LLM客户端"""
        default_config = {
            "base_url": "http://127.0.0.1:8080/v1",
            "api_key": "dummy",
            "model": "gelab-zero-4b-preview",
            "temperature": 0.7,
            "max_tokens": 8000,
            "timeout": 10,  # 总超时10秒（原来是30秒）
            "max_retries": 1,  # 失败后最多重试1次（原来是2次）
        }
        config = {**default_config, **self.llm_config}

        # 如果API key为空或dummy，使用mock配置避免OpenAI验证错误
        if not config["api_key"] or config["api_key"] == "dummy":
            # 使用一个不会实际发起网络请求的配置
            config["base_url"] = "http://mock.localhost:9999/v1"
            config["api_key"] = "mock-key"

        # 初始化ChatOpenAI客户端
        self.llm = ChatOpenAI(
            base_url=config["base_url"],
            api_key=config["api_key"],
            model=config["model"],
            temperature=config["temperature"],
            max_tokens=config["max_tokens"],
            timeout=config["timeout"],
            streaming=True,
            verbose=False,
            max_retries=config.get("max_retries", 2),  # 失败后重试
        )

    def _create_agent(self) -> None:
        """使用官方create_agent创建Agent，内置中间件限制工具调用"""
        # 预加载技能列表
        skills_list = load_skills_list("main")

        # 动态注入工具列表和技能列表到增强提示词
        tool_names = ", ".join([tool.name for tool in ALL_TOOLS])
        enhanced_system_prompt = self.base_system_prompt + "\n\n" + agent_enhance_prompt.format(
            tool_names=tool_names,
            skills_list=skills_list
        )

        # 配置中间件
        middleware = [
            # MCP工具结果处理：将图片base64转换为正确的多模态格式，避免纯文本token爆炸
            MCPToolResultMiddleware(),
            # 图片内容优化：避免历史图片base64数据累积导致token溢出
            ImageOptimizationMiddleware(),
            # 修复工具调用ID：某些LLM生成的tool_call缺少id字段
            ToolCallIdMiddleware(),
            # 历史消息自动压缩：token超过64K时自动压缩，保留最近20条消息
            SummarizationMiddleware(
                model=self.llm,  # 使用当前配置的模型进行压缩
                trigger=("tokens", MAX_CONTEXT_TOKENS // 2),  # token数超过64K时触发压缩
                keep=("messages", 20),  # 压缩后保留最近20条消息，减少上下文长度
            ),
            # 模型调用次数限制：单次运行最多调用MAX_ITERATIONS次模型（对应最多MAX_ITERATIONS轮迭代）
            # 达到限制后自动优雅结束，不会报错
            ModelCallLimitMiddleware(
                run_limit=MAX_ITERATIONS,
                exit_behavior="end",
            )
        ]

        # 持久化存储 — 使用外部传入的 AsyncSqliteSaver（app.py 初始化）
        if self.checkpointer is None:
            self.checkpointer = MemorySaver()

        # 保存系统提示词用于token统计（state中的messages不包含系统提示词）
        self._system_prompt = enhanced_system_prompt

        # 使用官方create_agent创建Agent，递归限制在config中配置
        self.agent = create_agent(
            model=self.llm,
            tools=ALL_TOOLS,
            system_prompt=enhanced_system_prompt,
            checkpointer=self.checkpointer,
            middleware=middleware,
        )

    async def get_context_usage(self) -> dict:
        """获取当前完整上下文的token用量
        直接构建实际发送给AI的完整messages数组+工具定义，一次性估算。
        Returns:
            {"current": int, "max": int, "percentage": float}
            失败时返回0/128000/0
        """
        try:
            state = await self.agent.aget_state(self.config)
            state_messages = state.values.get("messages", []) or []

            # 构建实际发送给LLM的完整messages：[系统提示词, *对话历史, *当前输入]
            full_messages = []
            sys_prompt = getattr(self, '_system_prompt', '')
            if sys_prompt:
                full_messages.append(SystemMessage(content=sys_prompt))
            full_messages.extend(state_messages)

            # 一次性估算：messages（含tool_calls）+ tools（按JSON schema格式）
            # chars_per_token=2.0 更适合中英文混合场景（默认4.0偏英文）
            current_tokens = count_tokens_approximately(
                full_messages,
                tools=list(ALL_TOOLS),
                chars_per_token=2.0,
            )

            return {
                "current": current_tokens,
                "max": MAX_CONTEXT_TOKENS,
                "percentage": round(current_tokens / MAX_CONTEXT_TOKENS * 100, 1)
            }
        except Exception:
            return {"current": 0, "max": MAX_CONTEXT_TOKENS, "percentage": 0.0}

    async def run_conversation(
        self,
        user_message: str,
        on_token: Optional[Callable[[str], Awaitable[None]]] = None,
        on_tool_event: Optional[Callable[[dict], Awaitable[None]]] = None,
    ) -> Tuple[str, bool, int]:
        """
        运行对话
        Args:
            user_message: 用户输入消息
            on_token: 可选的异步回调，每收到一个 token chunk 时调用，用于实现真正的流式推送
            on_tool_event: 可选的异步回调，工具调用事件（tool_start/tool_end/thinking），用于推送工具执行进度
        Returns:
            (响应内容, 是否使用了流式输出, 本次对话调用工具次数)
        """
        try:
            full_response = ""
            progress_display = None
            tool_call_count = 0  # 统计本次对话的工具调用次数
            start_time = datetime.now()  # 记录开始时间，用于总耗时
            conv_task_id = f"conv_{datetime.now().strftime('%H%M%S')}"

            # 记录对话开始
            self.logger.log_conversation_start(conv_task_id, user_message)

            # 通知用户后台任务完成
            if self._background_task_results and self.ui and hasattr(self.ui, 'console'):
                for _r in self._background_task_results:
                    status_icon = "✅" if _r.get("status") == "completed" else "❌"
                    summary_trunc = _r.get("summary", "")[:120]
                    self.ui.console.print(
                        f"[dim]{status_icon} 后台任务 [{_r['task_id']}] "
                        f"{summary_trunc}[/dim]"
                    )
                self._background_task_results.clear()

            # 初始化进度显示
            if self.ui and hasattr(self.ui, 'create_progress_display'):
                progress_display = self.ui.create_progress_display()
                progress_display.__enter__()
                progress_display.update("思考中")

            # 环境感知：使用缓存数据（后台异步刷新，不阻塞）
            # 首次对话无缓存时跳过，后续由后台任务自动刷新
            env_tag = getattr(self, '_cached_env_tag', None)

            # 构建消息列表：用户画像 + 环境感知合并到用户消息中
            profile_text = f"{self._user_profile}" if self._user_profile else ""
            # 语音由系统自动处理，不需要模型干预
            env_text = env_tag if env_tag else ""
            env_text = env_tag if env_tag else ""
            combined_context = "\n\n".join(filter(None, [profile_text, env_text]))
            if combined_context:
                combined_message = f"{combined_context}\n\n---\n{user_message}"
            else:
                combined_message = user_message

            # 使用多种stream模式同时获取消息流和执行更新
            async for chunk in self.agent.astream(
                {"messages": [HumanMessage(content=combined_message)]},
                config=self.config,
                stream_mode=["messages", "updates"],
                version="v2"
            ):
                # 刷新进度时间（每次收到chunk都更新，让时间走动）
                if progress_display:
                    progress_display.update()

                # 处理消息流（用于流式输出回复内容）
                if chunk["type"] == "messages":
                    message_chunk, metadata = chunk["data"]
                    node = metadata.get("langgraph_node", "")

                    if node == "model" and hasattr(message_chunk, "content") and message_chunk.content:
                        # LangGraph stream_mode="messages" 中每个 AIMessageChunk
                        # 是增量内容，直接追加即可
                        if type(message_chunk) is AIMessage:
                            continue

                        content = message_chunk.content

                        # 【去重检测】模型调用工具后可能重新生成文本，造成重复输出
                        # 条件：已积累100+字符，且当前chunk≥15字符，检查是否在重复已有内容
                        if len(full_response) > 100 and len(content) >= 15:
                            recent_window = full_response[-400:]
                            if content[:30] in recent_window:
                                continue

                        # 如果是首次收到内容，先关闭进度显示
                        if progress_display:
                            progress_display.__exit__(None, None, None)
                            progress_display = None

                        # 实时输出到UI
                        if self.ui and hasattr(self.ui, 'print_stream_chunk'):
                            self.ui.print_stream_chunk(content)
                        # 收集完整响应（增量chunk，直接追加）
                        full_response += content

                        # 如果有 on_token 回调，实时推送 token 给调用方
                        if on_token is not None:
                            await on_token(content)

                # 处理更新事件（用于进度显示）
                elif chunk["type"] == "updates" and progress_display:
                    for source, update in chunk["data"].items():
                        if source == "model":
                            # 模型正在思考或生成工具调用
                            message = update["messages"][-1]
                            if hasattr(message, 'tool_calls') and message.tool_calls:
                                # 检测到工具调用
                                for tc in message.tool_calls:
                                    tool_call_count += 1  # 工具调用计数+1
                                    tool_name = tc["name"]
                                    tool_args = tc["args"]
                                    # 记录日志
                                    self.logger.log_tool_call(
                                        conv_task_id, tool_call_count,
                                        tool_name, tool_args, "[执行中]"
                                    )

                                    # 通知外部工具调用开始
                                    if on_tool_event is not None:
                                        await on_tool_event({
                                            "type": "tool_start",
                                            "name": tool_name,
                                            "args": tool_args
                                        })

                                    # 特殊处理shell_exec，显示命令内容
                                    if tool_name == "shell_exec" and "command" in tool_args:
                                        command = tool_args["command"]
                                        # 截断过长的命令
                                        display_cmd = command[:50] + "..." if len(command) > 50 else command
                                        if self.ui and hasattr(self.ui, 'print_info'):
                                            self.ui.print_info(f"执行命令: {command}")
                                        progress_display.update(f"执行: {display_cmd}")
                                    else:
                                        # 其他工具显示名称和参数
                                        args_text = ", ".join([f"{k}={v}" for k, v in tool_args.items()])
                                        args_text = args_text[:30] + "..." if len(args_text) > 30 else args_text
                                        progress_display.update(f"调用: {tool_name}({args_text})")
                            else:
                                progress_display.update("思考中")
                                if on_tool_event is not None:
                                    await on_tool_event({"type": "thinking"})
                        elif source == "tools":
                            # 工具执行完成
                            message = update["messages"][-1]
                            tool_name_2 = message.name if hasattr(message, 'name') else "工具"
                            progress_display.update(f"处理 {tool_name_2} 结果")
                            if on_tool_event is not None:
                                await on_tool_event({
                                    "type": "tool_end",
                                    "name": tool_name_2
                                })

            # 关闭进度显示
            if progress_display:
                progress_display.__exit__(None, None, None)

            # ── 消费后台任务派发队列，同步执行子Agent并实时显示输出 ──
            pending_tasks = consume_pending_tasks()
            for pt in pending_tasks:
                task_path = pt.get("task_path", "")
                task_id = pt.get("task_id", "unknown")
                description = pt.get("description", "")
                if task_path and os.path.exists(task_path):
                    if self.ui:
                        self.ui.console.print(
                            f"\n[bold yellow]▶ 子Agent执行: {description}[/bold yellow]"
                        )
                    await self._run_executor_foreground(task_path, task_id)

            # ── 技能验证：通知主Agent检查新沉淀的技能 ──
            if self._pending_skill_verification:
                skills_str = ", ".join(self._pending_skill_verification)
                try:
                    msg = HumanMessage(content=f"【技能验证】新技能：{skills_str}。请对照 skill-creator 格式检查并修正。")
                    await self.agent.update_state(self.config, {"messages": [msg]})
                except Exception:
                    pass
                self._pending_skill_verification = []

            # ── 清理主Agent状态中的 delegate_task 相关消息 ──
            # 避免下次对话时因工具调用消息格式问题导致 DashScope 400 错误
            if pending_tasks:
                try:
                    state = await self.agent.aget_state(self.config)
                    msgs = state.values.get("messages", [])
                    # 查找所有 delegate_task 工具调用的ID
                    delegate_tc_ids = set()
                    to_remove_ids = set()
                    for m in msgs:
                        if hasattr(m, 'tool_calls') and m.tool_calls:
                            for tc in m.tool_calls:
                                if tc.get('name') == 'delegate_task':
                                    if m.id:
                                        to_remove_ids.add(m.id)
                                    delegate_tc_ids.add(tc.get('id', ''))
                    # 查找对应的 ToolMessage
                    for m in msgs:
                        if isinstance(m, ToolMessage) and m.tool_call_id in delegate_tc_ids:
                            if m.id:
                                to_remove_ids.add(m.id)

                    if to_remove_ids:
                        removals = [RemoveMessage(id=mid) for mid in to_remove_ids]
                        await self.agent.update_state(self.config, {"messages": removals})
                except Exception:
                    pass

            # ── 后处理去重 ──
            # 模型在调用工具（如 tts_speak）后可能重新生成一遍内容，导致重复输出
            if len(full_response) > 200:
                # 取前80个字符在后文中查找第二次出现
                prefix = full_response[:80]
                dup_pos = full_response.find(prefix, 80)
                if dup_pos > 0:
                    full_response = full_response[:dup_pos]

            # 如果stream没有返回内容（极端情况），回退到ainvoke
            if not full_response:
                result = await self.agent.ainvoke(
                    {"messages": [HumanMessage(content=user_message)]},
                    config=self.config
                )
                last_message = result["messages"][-1]
                full_response = str(last_message.content).strip()

                # 统计ainvoke模式下的工具调用次数
                for msg in result["messages"]:
                    if hasattr(msg, 'tool_calls') and msg.tool_calls:
                        tool_call_count += len(msg.tool_calls)

            # 计算总耗时并获取token用量，打印完成行 | 上下文条
            elapsed = int((datetime.now() - start_time).total_seconds())
            usage = await self.get_context_usage()
            if self.ui:
                bar_text = ""
                if usage["current"] > 0:
                    bar_text = self.ui.format_context_bar(usage)
                # 先换行再打印，与AI回复内容分开
                self.ui.console.print(
                    f"\n\n✅ [dim cyan]完成 (总耗时 {elapsed} 秒)[/dim cyan] {bar_text}"
                )

            # 记录日志
            try:
                self.logger.log_conversation_end(conv_task_id, full_response.strip()[:200], tool_call_count, elapsed)
            except Exception:
                pass

            # 后台刷新环境感知缓存，为下一次对话准备（不阻塞本次返回）
            asyncio.create_task(self._refresh_env_cache())

            return (full_response.strip(), True, tool_call_count)

        except asyncio.CancelledError:
            # 任务被取消，确保进度显示被关闭
            if 'progress_display' in locals() and progress_display:
                try:
                    progress_display.__exit__(None, None, None)
                except:
                    pass
            # 重新抛出取消异常，让上层处理
            raise
        except KeyboardInterrupt:
            # 键盘中断，确保进度显示被关闭
            if 'progress_display' in locals() and progress_display:
                try:
                    progress_display.__exit__(None, None, None)
                except:
                    pass
            # 重新抛出，让上层处理中断
            raise
        except Exception as e:
            # 确保进度显示被关闭
            if 'progress_display' in locals() and progress_display:
                try:
                    progress_display.__exit__(type(e), e, None)
                except:
                    pass

            # 取消子Agent监控
            if 'subagent_monitor_task' in locals() and subagent_monitor_task:
                subagent_monitor_task.cancel()

            import traceback
            error_details = traceback.format_exc()

            # 特殊处理超时错误
            error_str = str(e).lower()
            if "timeout" in error_str or "timed out" in error_str or "time out" in error_str:
                error_msg = "⏱️  请求超时，请检查网络连接或稍后再试。如果问题持续存在，可以尝试降低模型输出长度或切换到更小的模型。"
            elif "connection" in error_str or "network" in error_str or "refused" in error_str:
                error_msg = "🔌  网络连接失败，请检查LLM服务是否正常运行，API地址和密钥是否配置正确。"
            else:
                error_msg = f"Agent 执行错误: {str(e)}\n{error_details[:800]}"

            return (error_msg, False, tool_call_count)

    async def stream_conversation(self, user_message: str, thread_id: str = None, history: list = None) -> AsyncGenerator[dict, None]:
        """
        流式对话 - async generator，直接 yield 结构化事件，供 FastAPI SSE 端点使用
        Args:
            user_message: 用户输入消息
            thread_id: 可选的会话ID，用于隔离不同会话的对话历史。为None时使用默认session
            history: 可选的历史消息列表 [{"role": "user"/"assistant", "content": "..."}]
        Yields:
            {"type": "token", "content": "你好"}                   -- 文本 token
            {"type": "tool_start", "name": "...", "args": {...}}    -- 工具调用开始
            {"type": "tool_end", "name": "..."}                     -- 工具调用完成
            {"type": "thinking"}                                    -- 模型思考中
            {"type": "done", "response": "...", "success": True, "tool_calls": N}  -- 完成
            {"type": "error", "message": "..."}                     -- 错误
        """
        # 使用传入的 thread_id 或默认配置，实现会话隔离
        # 支持 _thread_id_map 映射（clear_history 后旧 thread_id 会映射到新 UUID）
        actual_thread_id = thread_id or self.config["configurable"]["thread_id"]
        if hasattr(self, '_thread_id_map') and actual_thread_id in self._thread_id_map:
            actual_thread_id = self._thread_id_map[actual_thread_id]
        config = {
            "configurable": {"thread_id": actual_thread_id},
            "recursion_limit": self.config.get("recursion_limit", RECURSION_LIMIT),
        }
        try:
            full_response = ""
            tool_call_count = 0
            start_time = datetime.now()
            conv_task_id = f"conv_{datetime.now().strftime('%H%M%S')}"

            # 记录对话开始
            self.logger.log_conversation_start(conv_task_id, user_message)

            # 环境感知：使用缓存数据（后台异步刷新，不阻塞）
            env_tag = getattr(self, '_cached_env_tag', None)

            # 构建消息列表：用户画像 + 环境感知合并到用户消息中
            profile_text = f"{self._user_profile}" if self._user_profile else ""
            env_text = env_tag if env_tag else ""
            combined_context = "\n\n".join(filter(None, [profile_text, env_text]))
            if combined_context:
                combined_message = f"{combined_context}\n\n---\n{user_message}"
            else:
                combined_message = user_message

            # 构建输入消息：历史消息 + 当前消息
            input_messages = []
            if history:
                for msg in history:
                    if msg["role"] == "user":
                        input_messages.append(HumanMessage(content=msg["content"]))
                    elif msg["role"] == "assistant":
                        input_messages.append(AIMessage(content=msg["content"]))
            input_messages.append(HumanMessage(content=combined_message))

            async for chunk in self.agent.astream(
                {"messages": input_messages},
                config=config,
                stream_mode=["messages", "updates"],
                version="v2"
            ):
                if self._check_cancel():
                    break

                # 处理消息流（用于流式输出回复内容）
                if chunk["type"] == "messages":
                    message_chunk, metadata = chunk["data"]
                    node = metadata.get("langgraph_node", "")

                    if node == "model" and hasattr(message_chunk, "content"):
                        # 检查是否有推理内容（DeepSeek 等模型的思考过程）
                        rc = message_chunk.additional_kwargs.get("reasoning_content", "") if hasattr(message_chunk, "additional_kwargs") else ""
                        if rc:
                            yield {"type": "thinking"}

                        if message_chunk.content:
                            # LangGraph stream_mode="messages" 中每个 AIMessageChunk
                            # 是增量内容，直接追加即可
                            if type(message_chunk) is AIMessage:
                                continue

                            content = message_chunk.content

                            # 【去重检测】模型调用工具后可能重新生成文本，造成重复输出
                            # 条件：已积累100+字符，且当前chunk>=15字符，检查是否在重复已有内容
                            if len(full_response) > 100 and len(content) >= 15:
                                recent_window = full_response[-400:]
                                if content[:30] in recent_window:
                                    continue

                            # 收集完整响应（增量chunk，直接追加）
                            full_response += content

                            # yield 文本 token
                            yield {"type": "token", "content": content}

                # 处理更新事件（用于进度显示）
                elif chunk["type"] == "updates":
                    for source, update in chunk["data"].items():
                        if source == "model":
                            message = update["messages"][-1]
                            if hasattr(message, 'tool_calls') and message.tool_calls:
                                # 检测到工具调用
                                for tc in message.tool_calls:
                                    tool_call_count += 1  # 工具调用计数+1
                                    tool_name = tc["name"]
                                    tool_args = tc["args"]
                                    # 记录日志
                                    self.logger.log_tool_call(
                                        conv_task_id, tool_call_count,
                                        tool_name, tool_args, "[执行中]"
                                    )

                                    # yield 工具调用开始事件
                                    yield {
                                        "type": "tool_start",
                                        "name": tool_name,
                                        "args": tool_args
                                    }
                            else:
                                # 模型思考中
                                yield {"type": "thinking"}
                        elif source == "tools":
                            # 工具执行完成
                            message = update["messages"][-1]
                            tool_name_2 = message.name if hasattr(message, 'name') else "工具"
                            yield {
                                "type": "tool_end",
                                "name": tool_name_2
                            }

            # ── 消费后台任务派发队列，同步执行子Agent并实时显示输出 ──
            pending_tasks = consume_pending_tasks()
            skill_background_tasks = []  # 收集后台技能沉淀任务
            for pt in pending_tasks:
                task_path = pt.get("task_path", "")
                task_id = pt.get("task_id", "unknown")
                description = pt.get("description", "")
                if task_path and os.path.exists(task_path):
                    # 存储子Agent任务引用，供 /cancel 终止
                    self._executor_task = asyncio.current_task()
                    try:
                        async for event in self._run_executor_foreground(task_path, task_id):
                            if self._check_cancel():
                                break
                            # 收集后台技能沉淀任务，稍后等待
                            if event.get("type") == "_skill_task":
                                skill_background_tasks.append((event["task"], event["queue"]))
                            else:
                                yield event
                    finally:
                        self._executor_task = None

            # ── 等待后台技能沉淀任务完成，输出结果 ──
            for skill_task, skill_queue in skill_background_tasks:
                try:
                    # 输出技能沉淀开始标记
                    yield {"type": "token", "content": "\n\n📝 技能沉淀中...\n"}
                    # 从队列中读取输出直到结束标记
                    while True:
                        try:
                            item = await asyncio.wait_for(skill_queue.get(), timeout=120)
                        except asyncio.TimeoutError:
                            yield {"type": "token", "content": "\n[error] 技能沉淀超时\n"}
                            break
                        if item is None:
                            break
                        yield item
                    # 确保后台任务完成
                    await asyncio.wait_for(skill_task, timeout=5)
                except Exception as e:
                    yield {"type": "token", "content": f"\n[error] 技能沉淀异常: {str(e)[:100]}\n"}

            # ── 技能验证：通知主Agent检查新沉淀的技能 ──
            if self._pending_skill_verification:
                skills_str = ", ".join(self._pending_skill_verification)
                try:
                    msg = HumanMessage(content=f"【技能验证】新技能：{skills_str}。请对照 skill-creator 格式检查并修正。")
                    await self.agent.update_state(config, {"messages": [msg]})
                except Exception:
                    pass
                self._pending_skill_verification = []

            # ── 清理主Agent状态中的 delegate_task 相关消息 ──
            # 避免下次对话时因工具调用消息格式问题导致 DashScope 400 错误
            if pending_tasks:
                try:
                    state = await self.agent.aget_state(config)
                    msgs = state.values.get("messages", [])
                    # 查找所有 delegate_task 工具调用的ID
                    delegate_tc_ids = set()
                    to_remove_ids = set()
                    for m in msgs:
                        if hasattr(m, 'tool_calls') and m.tool_calls:
                            for tc in m.tool_calls:
                                if tc.get('name') == 'delegate_task':
                                    if m.id:
                                        to_remove_ids.add(m.id)
                                    delegate_tc_ids.add(tc.get('id', ''))
                    # 查找对应的 ToolMessage
                    for m in msgs:
                        if isinstance(m, ToolMessage) and m.tool_call_id in delegate_tc_ids:
                            if m.id:
                                to_remove_ids.add(m.id)

                    if to_remove_ids:
                        removals = [RemoveMessage(id=mid) for mid in to_remove_ids]
                        await self.agent.update_state(config, {"messages": removals})
                except Exception:
                    pass

            # ── 后处理去重 ──
            # 模型在调用工具（如 tts_speak）后可能重新生成一遍内容，导致重复输出
            if len(full_response) > 200:
                # 取前80个字符在后文中查找第二次出现
                prefix = full_response[:80]
                dup_pos = full_response.find(prefix, 80)
                if dup_pos > 0:
                    full_response = full_response[:dup_pos]

            # 如果stream没有返回内容（极端情况），回退到ainvoke
            if not full_response:
                result = await self.agent.ainvoke(
                    {"messages": [HumanMessage(content=user_message)]},
                    config=config
                )
                last_message = result["messages"][-1]
                full_response = str(last_message.content).strip()

                # 统计ainvoke模式下的工具调用次数
                for msg in result["messages"]:
                    if hasattr(msg, 'tool_calls') and msg.tool_calls:
                        tool_call_count += len(msg.tool_calls)

                # yield 回退的完整响应
                yield {"type": "token", "content": full_response}

            # 记录日志
            elapsed = int((datetime.now() - start_time).total_seconds())
            try:
                self.logger.log_conversation_end(conv_task_id, full_response.strip()[:200], tool_call_count, elapsed)
            except Exception:
                pass

            # 后台刷新环境感知缓存，为下一次对话准备（不阻塞本次返回）
            asyncio.create_task(self._refresh_env_cache())

            # yield 完成事件
            yield {"type": "done", "response": full_response.strip(), "success": True, "tool_calls": tool_call_count}

        except asyncio.CancelledError:
            # 重新抛出取消异常，让上层处理
            raise
        except KeyboardInterrupt:
            # 重新抛出，让上层处理中断
            raise
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()

            # 特殊处理超时错误
            error_str = str(e).lower()
            if "timeout" in error_str or "timed out" in error_str or "time out" in error_str:
                error_msg = "⏱️  请求超时，请检查网络连接或稍后再试。如果问题持续存在，可以尝试降低模型输出长度或切换到更小的模型。"
            elif "connection" in error_str or "network" in error_str or "refused" in error_str:
                error_msg = "\U0001f50c  网络连接失败，请检查LLM服务是否正常运行，API地址和密钥是否配置正确。"
            else:
                error_msg = f"Agent 执行错误: {str(e)}\n{error_details[:800]}"

            yield {"type": "error", "message": error_msg}

    def clear_history(self, thread_id: str = None) -> None:
        """清空指定会话的对话历史"""
        import uuid
        if thread_id:
            # 为该会话生成新的内部 thread_id，旧历史自动失效
            self._thread_id_map = getattr(self, '_thread_id_map', {})
            self._thread_id_map[thread_id] = str(uuid.uuid4())
        else:
            # 清空默认会话
            self.config = {
                "configurable": {
                    "thread_id": str(uuid.uuid4())
                },
                "recursion_limit": self.max_iterations
            }

    def cancel(self) -> None:
        """请求取消当前正在执行的推理"""
        self._cancel_requested = True

    def _check_cancel(self) -> bool:
        """检查是否请求了取消，如果是则重置标志并返回 True"""
        if getattr(self, '_cancel_requested', False):
            self._cancel_requested = False
            return True
        return False

    async def cleanup(self) -> None:
        """关闭所有HTTP客户端，避免退出时 httpx 异步生成器报错"""
        try:
            if hasattr(self, 'llm') and self.llm is not None:
                await self.llm.async_client.aclose()
        except Exception:
            pass
        try:
            if hasattr(self, '_executor_llm') and self._executor_llm is not None:
                await self._executor_llm.async_client.aclose()
        except Exception:
            pass

    def _render_task_progress(self, task_data: dict) -> str:
        """渲染子Agent任务进度"""
        lines = []
        for step in task_data.get("steps", []):
            status = step.get("status", "pending")
            desc = step.get("desc", "")
            if status == "completed":
                lines.append(f"  \u2714 {desc}")
            elif status == "in_progress":
                lines.append(f"  \u23f3 {desc}")
            elif status == "failed":
                lines.append(f"  \u2718 {desc}")
            elif status == "skipped":
                lines.append(f"  \u293e {desc}")
            else:
                lines.append(f"  \u25fb {desc}")
        return "\n".join(lines) if lines else ""

    async def _run_executor_foreground(self, task_path: str, task_id: str):
        """前台运行子Agent（executor），yield 结构化事件供 SSE 流式推送"""
        try:
            executor_tool_names = {"shell_exec", "file_read", "file_write", "file_search", "mcp_call", "system_info", "tts_speak"}
            executor_tools = [t for t in ALL_TOOLS if t.name in executor_tool_names]
            executor_skills = load_skills_list("executor")
            executor_tool_names_str = ", ".join(t.name for t in executor_tools)

            from langchain.agents.middleware import ModelCallLimitMiddleware
            enhanced = executor_enhance_prompt.format(
                tool_names=executor_tool_names_str,
                skills_list=executor_skills,
            )
            system_content = executor_system_prompt.replace("{tool_rules_and_skills}", enhanced)

            if self._executor_llm is None:
                # 子Agent LLM 配置：从 .env 读取，未设置的字段继承主Agent
                _base = EXECUTOR_LLM_CONFIG.get("base_url")
                _api = EXECUTOR_LLM_CONFIG.get("api_key")
                _mod = EXECUTOR_LLM_CONFIG.get("model")
                _tmp = EXECUTOR_LLM_CONFIG.get("temperature")
                _tok = EXECUTOR_LLM_CONFIG.get("max_tokens")
                executor_llm_config = {
                    "base_url": _base if _base else self.llm.openai_api_base,
                    "api_key": _api if _api else self.llm.openai_api_key,
                    "model": _mod if _mod else self.llm.model_name,
                    "temperature": float(_tmp) if _tmp and _tmp.replace(".", "", 1).lstrip("-").isdigit() else 0.5,
                    "max_tokens": int(_tok) if _tok and _tok.isdigit() else 16000,
                }
                # 子Agent任务包含MCP/Shell调用，超时设30s比主Agent的10s更长
                self._executor_llm = ChatOpenAI(
                    base_url=executor_llm_config["base_url"],
                    api_key=executor_llm_config["api_key"],
                    model=executor_llm_config["model"],
                    temperature=executor_llm_config["temperature"],
                    max_tokens=executor_llm_config["max_tokens"],
                    timeout=30,
                    streaming=True,
                    max_retries=1,
                )
            executor_llm = self._executor_llm
            executor_middleware = [
                ToolCallIdMiddleware(),
                ModelCallLimitMiddleware(
                    run_limit=self.max_iterations,
                    exit_behavior="end",
                ),
            ]
            from langgraph.checkpoint.memory import MemorySaver
            executor_agent = create_agent(
                model=executor_llm,
                tools=executor_tools,
                system_prompt=system_content,
                checkpointer=MemorySaver(),
                middleware=executor_middleware,
            )

            if not os.path.exists(task_path):
                if self.ui:
                    self.ui.console.print("  [red]❌ 任务文件不存在[/red]")
                self._background_task_results.append({
                    "task_id": task_id,
                    "status": "failed",
                    "summary": "❌ 任务文件不存在",
                })
                yield {"type": "executor_done", "task_id": task_id, "status": "failed"}
                return

            with open(task_path, "r", encoding="utf-8") as f:
                task_data = json.load(f)
            objective = task_data.get("objective", "")

            # 记录子Agent开始
            self.logger.log_executor_start(task_id, objective)
            self._executor_step_start = datetime.now()
            executor_step = 0
            had_intervention = False  # 是否申请了人工介入

            # yield 子Agent启动标识
            yield {"type": "executor_start", "task_id": task_id, "objective": objective}

            # 用户画像要求语音时，启动时语音通知
            _profile = getattr(self, '_user_profile', '') or ''
            if any(kw in _profile for kw in ['语音', '朗读', '播报', 'voice']):
                try:
                    _speak = objective[:80].replace('"', ' ').replace("'", " ")
                    subprocess.run(
                        f'termux-tts-speak "开始执行任务：{_speak}" &>/dev/null &',
                        shell=True, timeout=5,
                    )
                except Exception:
                    pass

            # 搜集已有技能列表，让子Agent知道已经沉淀过哪些
            existing_skills = []
            auto_executor_dir = os.path.join(AUTO_SKILLS_DIR, "executor")
            if os.path.exists(auto_executor_dir):
                for _cat in sorted(os.listdir(auto_executor_dir)):
                    _cat_path = os.path.join(auto_executor_dir, _cat)
                    if os.path.isdir(_cat_path):
                        existing_skills.append(_cat)
            skills_hint = f"\n（已有沉淀技能：{', '.join(existing_skills) or '无'}，执行完毕后需沉淀/更新/跳过）"

            # 流式执行子Agent，实时输出
            full_response = ""
            async for chunk in executor_agent.astream(
                {"messages": [HumanMessage(content="请读取 " + task_path + " 并开始执行。" + skills_hint)]},
                config={"configurable": {"thread_id": "executor_" + task_id}},
                stream_mode=["messages", "updates"],
                version="v2",
            ):
                if self._check_cancel():
                    break

                if chunk["type"] == "messages":
                    message_chunk, metadata = chunk["data"]
                    node = metadata.get("langgraph_node", "")
                    if node == "model" and hasattr(message_chunk, "content"):
                        # 检查推理内容（DeepSeek 等模型的思考过程）
                        rc = message_chunk.additional_kwargs.get("reasoning_content", "") if hasattr(message_chunk, "additional_kwargs") else ""
                        if rc:
                            yield {"type": "thinking"}

                        if message_chunk.content:
                            if type(message_chunk) is AIMessage:
                                continue
                            content = message_chunk.content
                            full_response += content
                            if self.ui:
                                self.ui.print_stream_chunk(content)
                            yield {"type": "token", "content": content}

                elif chunk["type"] == "updates":
                    for source, update in chunk["data"].items():
                        if source == "model":
                            message = update["messages"][-1]
                            if hasattr(message, 'tool_calls') and message.tool_calls:
                                for tc in message.tool_calls:
                                    executor_step += 1
                                    tool_name = tc["name"]
                                    tool_args = tc["args"]
                                    # 记录日志
                                    self.logger.log_executor_step(task_id, executor_step, tool_name, tool_args)
                                    # yield 工具调用开始
                                    yield {"type": "tool_start", "name": tool_name, "args": tool_args}
                                    # 检测人工介入请求（tts_speak 工具 或 shell_exec 调用 termux-tts-speak）
                                    if tool_name == "tts_speak" and "text" in tool_args:
                                        had_intervention = True
                                        speak_text = tool_args["text"][:80]
                                        self.logger.log_executor_intervention(task_id, f"TTS语音通知: {speak_text}", "pending")
                                        if self.ui:
                                            self.ui.console.print(f"\n  [bold yellow]🆘 子Agent申请人工介入: {speak_text}[/bold yellow]")
                                    elif tool_name == "shell_exec" and "command" in tool_args:
                                        cmd = tool_args["command"]
                                        # 兼容旧的 termux-tts-speak shell 调用
                                        if "termux-tts-speak" in cmd or "termux-tts" in cmd:
                                            had_intervention = True
                                            speak_text = cmd.split('"')[1] if '"' in cmd else cmd[30:80]
                                            self.logger.log_executor_intervention(task_id, f"TTS语音通知: {speak_text}", "pending")
                                            if self.ui:
                                                self.ui.console.print(f"\n  [bold yellow]🆘 子Agent申请人工介入: {speak_text}[/bold yellow]")
                                        else:
                                            display_cmd = cmd[:60] + "..." if len(cmd) > 60 else cmd
                                            if self.ui:
                                                self.ui.console.print(f"\n  [dim]⚡ {display_cmd}[/dim]")
                                    elif tool_name == "mcp_call" and "tool_name" in tool_args:
                                        mcp_tool = tool_args["tool_name"]
                                        if self.ui:
                                            self.ui.console.print(f"\n  [dim]📱 MCP: {mcp_tool}[/dim]")
                                    else:
                                        args_text = ", ".join([f"{k}={v}" for k, v in tool_args.items()])
                                        args_text = args_text[:40] + "..." if len(args_text) > 40 else args_text
                                        if self.ui:
                                            self.ui.console.print(f"\n  [dim]🔧 {tool_name}({args_text})[/dim]")
                            else:
                                yield {"type": "thinking"}
                        elif source == "tools":
                            message = update["messages"][-1]
                            tool_name_2 = message.name if hasattr(message, 'name') else "工具"
                            yield {"type": "tool_end", "name": tool_name_2}

            # ── 重试机制：如果子Agent没有执行有效操作（仅读了task.json就停了），强制重试 ──
            # 注意：重试必须使用全新Agent实例 + 内联任务内容，不能复用原对话线程，
            # 否则 DashScope 会校验历史中的 tool_call/tool_message 配对导致 400 错误
            retry_count = 0
            while executor_step <= 2 and retry_count < 2:
                retry_count += 1
                if self.ui:
                    self.ui.console.print(f"\n  [yellow]🔄 子Agent仅执行了{executor_step}步，强制重试第{retry_count}次...[/yellow]")

                # 读取 task.json 内容以内联到指令中
                try:
                    with open(task_path, "r", encoding="utf-8") as f:
                        task_data_retry = json.load(f)
                    retry_objective = task_data_retry.get("objective", "")
                    retry_steps = task_data_retry.get("steps", [])
                except Exception:
                    retry_objective = ""
                    retry_steps = []

                steps_lines = []
                for s in retry_steps:
                    desc = s.get("desc", "")
                    steps_lines.append(f"{s['id']}. {desc}")
                steps_text = "\n".join(steps_lines)

                retry_instruction = (
                    f"执行以下任务，必须调用工具完成每个步骤，禁止只输出文字：\n\n"
                    f"目标：{retry_objective}\n"
                    f"步骤：\n{steps_text}\n\n"
                    f"可用工具：shell_exec（启动App/查包名/点击）、mcp_call（手机操控）、"
                    f"file_read/write、tts_speak\n"
                    f"立即开始执行步骤1，不用再读task.json了！"
                )

                # 创建全新的 Agent 实例，避免历史消息中的 tool_call 格式问题
                fresh_agent = create_agent(
                    model=executor_llm,
                    tools=executor_tools,
                    system_prompt=system_content,
                    checkpointer=MemorySaver(),
                    middleware=executor_middleware,
                )
                async for chunk in fresh_agent.astream(
                    {"messages": [HumanMessage(content=retry_instruction)]},
                    config={"configurable": {"thread_id": "executor_retry_" + task_id + "_" + str(retry_count)}},
                    stream_mode=["messages", "updates"],
                    version="v2",
                ):
                    if self._check_cancel():
                        break

                    if chunk["type"] == "messages":
                        message_chunk, metadata = chunk["data"]
                        node = metadata.get("langgraph_node", "")
                        if node == "model" and hasattr(message_chunk, "content") and message_chunk.content:
                            if type(message_chunk) is AIMessage:
                                continue
                            content = message_chunk.content
                            full_response += content
                            if self.ui:
                                self.ui.print_stream_chunk(content)
                            yield {"type": "token", "content": content}
                    elif chunk["type"] == "updates":
                        for source, update in chunk["data"].items():
                            if source == "model":
                                message = update["messages"][-1]
                                if hasattr(message, 'tool_calls') and message.tool_calls:
                                    for tc in message.tool_calls:
                                        executor_step += 1
                                        tool_name = tc["name"]
                                        tool_args = tc["args"]
                                        self.logger.log_executor_step(task_id, executor_step, tool_name, tool_args)
                                        yield {"type": "tool_start", "name": tool_name, "args": tool_args}
                                        if self.ui:
                                            args_text = ", ".join([f"{k}={v}" for k, v in tool_args.items()])
                                            args_text = args_text[:40] + "..." if len(args_text) > 40 else args_text
                                            self.ui.console.print(f"\n  [dim]🔧 {tool_name}({args_text})[/dim]")
                                else:
                                    yield {"type": "thinking"}
                            elif source == "tools":
                                message = update["messages"][-1]
                                tool_name_2 = message.name if hasattr(message, 'name') else "工具"
                                yield {"type": "tool_end", "name": tool_name_2}
                    if self._check_cancel():
                        break

            # 执行完成
            if had_intervention:
                self.logger.log_executor_intervention(task_id, "子Agent在等待后继续执行", "resolved")
                if self.ui:
                    self.ui.console.print("\n  [green]✅ 人工介入后继续执行[/green]")

            # 重新从磁盘读取（executor 可能通过 file_write 修改过 steps）
            executor_end_time = datetime.now()
            try:
                with open(task_path, "r", encoding="utf-8") as f:
                    task_data = json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                pass  # 文件损坏时用原内存数据

            # 检查是否有失败的步骤
            failed_steps = [s for s in task_data.get("steps", []) if s.get("status") == "failed"]
            has_failures = bool(failed_steps)

            # 记录模型思考过程到日志
            self.logger.log_executor_reasoning(task_id, full_response)
            summary = full_response.strip()[:300] if full_response.strip() else "执行完毕"
            executor_elapsed = int((executor_end_time - self._executor_step_start).total_seconds()) if hasattr(self, '_executor_step_start') else 0
            if has_failures:
                task_data["status"] = "completed_with_failures"
                self.logger.log_executor_end(task_id, f"完成（{len(failed_steps)}个步骤失败）")
                status_text = f"⚠️ 子Agent完成（{len(failed_steps)}个步骤失败）"
            else:
                task_data["status"] = "completed"
                self.logger.log_executor_end(task_id, "完成")
                status_text = "✅ 子Agent任务完成"
            task_data["completed_at"] = datetime.now().isoformat()
            task_data["summary"] = summary
            with open(task_path, "w", encoding="utf-8") as f:
                json.dump(task_data, f, ensure_ascii=False, indent=2)

            # ── 统计 token 消耗 ──
            try:
                executor_state = await executor_agent.aget_state(
                    {"configurable": {"thread_id": "executor_" + task_id}}
                )
                executor_msgs = executor_state.values.get("messages", []) or []
                executor_tokens = count_tokens_approximately(
                    executor_msgs,
                    tools=list(executor_tools),
                    chars_per_token=2.0,
                )
                token_text = f" | 消耗 ≈{executor_tokens} tokens"
            except Exception:
                token_text = ""

            if self.ui:
                self.ui.console.print(f"\n  [green]{status_text}，⏱️ {executor_elapsed}s{token_text}[/green]")

            # yield 完成事件（立即汇报，不等待技能沉淀）
            yield {"type": "executor_done", "task_id": task_id, "status": "completed" if not has_failures else "completed_with_failures"}

            # ── 技能沉淀：后台异步执行，完成后通过队列输出 ──
            steps = task_data.get("steps", [])
            objective = task_data.get("objective", "")
            needs_skill = len(steps) >= 3 and objective and not has_failures
            if needs_skill:
                # 快速扫描：子Agent是否已自行沉淀技能
                new_skills = []
                auto_executor_dir = os.path.join(AUTO_SKILLS_DIR, "executor")
                if os.path.exists(auto_executor_dir):
                    for _cat in sorted(os.listdir(auto_executor_dir)):
                        _cat_path = os.path.join(auto_executor_dir, _cat)
                        if not os.path.isdir(_cat_path):
                            continue
                        for _fn in os.listdir(_cat_path):
                            if not _fn.endswith(".md"):
                                continue
                            _fp = os.path.join(_cat_path, _fn)
                            _mtime = os.path.getmtime(_fp)
                            _start_ts = self._executor_step_start.timestamp() if hasattr(self, '_executor_step_start') else 0
                            if _start_ts > 0 and _mtime >= _start_ts - 5 and os.path.getsize(_fp) > 50:
                                new_skills.append(_cat)
                                break
                skill_was_written = bool(new_skills)

                if skill_was_written:
                    if self.ui:
                        self.ui.console.print(f"\n  [dim]\U0001f4dd 子Agent已沉淀技能[/dim]")
                    self._pending_skill_verification.extend(new_skills)
                else:
                    # 检查是否真的执行了操作（executor_step > 2 说明有过实际工具调用）
                    if executor_step <= 2:
                        if self.ui:
                            self.ui.console.print(f"\n  [dim]\U0001f4dd 子Agent未执行有效操作（仅{executor_step}步），跳过技能沉淀[/dim]")
                    else:
                        # 后台异步执行技能沉淀，通过队列传递输出
                        if self.ui:
                            self.ui.console.print(f"\n  [dim]\U0001f4dd 技能沉淀后台进行中...[/dim]")

                        # 创建队列用于传递后台任务的输出
                        skill_output_queue = asyncio.Queue()

                        async def _consolidate_skill():
                            try:
                                skill_followup = (
                                    "任务已完成。现在请沉淀技能到 `agent/skills/auto-skills/executor/`：\n\n"
                                    "1. 先用 `directory_list('agent/skills/auto-skills/executor/')` 检查已有技能\n"
                                    "2. 如果找到相关技能 → 用 `file_read` 读取，评估是否需要补充完善\n"
                                    "3. 如果已覆盖 → 用 `file_write` 写一个说明文件说明'已有XX技能覆盖'\n"
                                    "4. 如果需要完善 → 用 `file_write` 更新，补充本次执行的关键发现\n"
                                    "5. 如果没找到 → 用 `file_write` 创建新技能\n\n"
                                    "技能内容需包含：包名、关键坐标、操作步骤、失败经验。"
                                )
                                async for _chunk in executor_agent.astream(
                                    {"messages": [HumanMessage(content=skill_followup)]},
                                    config={"configurable": {"thread_id": "executor_skill_" + task_id}},
                                    stream_mode=["messages", "updates"],
                                    version="v2",
                                ):
                                    if _chunk["type"] == "messages":
                                        message_chunk, metadata = _chunk["data"]
                                        node = metadata.get("langgraph_node", "")
                                        if node == "model" and hasattr(message_chunk, "content") and message_chunk.content:
                                            if type(message_chunk) is not AIMessage:
                                                content = message_chunk.content
                                                await skill_output_queue.put({"type": "token", "content": content})
                                    elif _chunk["type"] == "updates":
                                        for source, update in _chunk["data"].items():
                                            if source == "model":
                                                message = update["messages"][-1]
                                                if hasattr(message, 'tool_calls') and message.tool_calls:
                                                    for tc in message.tool_calls:
                                                        tool_name = tc["name"]
                                                        tool_args = tc["args"]
                                                        await skill_output_queue.put({"type": "tool_start", "name": tool_name, "args": tool_args})
                                            elif source == "tools":
                                                message = update["messages"][-1]
                                                tool_name_2 = message.name if hasattr(message, 'name') else "工具"
                                                await skill_output_queue.put({"type": "tool_end", "name": tool_name_2})
                                await skill_output_queue.put(None)  # 结束标记
                            except Exception as e:
                                await skill_output_queue.put({"type": "token", "content": f"\n[error] 技能沉淀失败: {str(e)[:100]}\n"})
                                await skill_output_queue.put(None)

                        # 启动后台任务
                        skill_task = asyncio.create_task(_consolidate_skill())
                        # 返回后台任务引用，供调用方等待
                        yield {"type": "_skill_task", "task": skill_task, "queue": skill_output_queue}

            return

        except asyncio.CancelledError:
            if 'full_response' in locals():
                self.logger.log_executor_reasoning(task_id, full_response)
            self.logger.log_executor_end(task_id, "中断")
            if self.ui:
                self.ui.console.print("\n  [yellow]⏹️ 子Agent执行被中断[/yellow]")
            yield {"type": "executor_done", "task_id": task_id, "status": "cancelled"}
            raise
        except Exception:
            import traceback
            error_detail = traceback.format_exc()
            if 'full_response' in locals():
                self.logger.log_executor_reasoning(task_id, full_response)
            # 如果之前申请过人工介入，记录介入失败
            if 'had_intervention' in locals() and had_intervention:
                self.logger.log_executor_intervention(task_id, "子Agent异常退出，人工介入未解决问题", "failed")
            self.logger.log_executor_end(task_id, f"失败: {error_detail}")

            # 标记 task.json 为失败状态
            try:
                if os.path.exists(task_path):
                    with open(task_path, "r", encoding="utf-8") as _f:
                        _td = json.load(_f)
                    _td["status"] = "failed"
                    _td["error"] = str(error_detail)[:500]
                    with open(task_path, "w", encoding="utf-8") as _f:
                        json.dump(_td, _f, ensure_ascii=False, indent=2)
            except Exception:
                pass

            # 提取关键错误信息（去掉冗长的调用栈）
            error_short = str(error_detail)
            for _line in reversed(error_detail.split("\n")):
                _line = _line.strip()
                if _line and not _line.startswith(("File ", "  ", "During", "Traceback")):
                    error_short = _line
                    break
            if self.ui:
                if 'had_intervention' in locals() and had_intervention:
                    self.ui.console.print("\n  [red]❌ 人工介入未解决问题，子Agent执行失败[/red]")
                self.ui.console.print(f"\n  [red]❌ 子Agent执行失败: {error_short}[/red]")

            # 语音通知用户失败原因
            try:
                _err_msg = error_short[:120].replace('"', ' ').replace("'", " ")
                subprocess.run(
                    f'termux-tts-speak "任务执行失败：{_err_msg}" &>/dev/null &',
                    shell=True, timeout=5,
                )
            except Exception:
                pass

            # 记录到后台结果，下次对话时主Agent可查看
            self._background_task_results.append({
                "task_id": task_id,
                "status": "failed",
                "summary": f"❌ 执行失败: {error_short[:200]}",
            })

            yield {"type": "executor_done", "task_id": task_id, "status": "failed"}

