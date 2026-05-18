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
from typing import List, Tuple, Dict, Any, Optional, Callable
from langchain_core.tools import StructuredTool
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, AIMessageChunk, ToolMessage
from langgraph.checkpoint.memory import MemorySaver
from langchain_openai import ChatOpenAI
from langchain.agents.middleware import ModelCallLimitMiddleware, SummarizationMiddleware, wrap_tool_call
from langchain.agents.middleware.types import AgentMiddleware, ModelResponse
from langchain_core.messages.utils import count_tokens_approximately
from .llm import LLMManager
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
)
from .prompts.agent_enhance import prompt as agent_enhance_prompt
from .tools.basic_tools import ALL_TOOLS


# ── 技能加载工具 ──────────────────────────────────────────────
def load_skills_list() -> str:
    """
    预加载所有可用技能的名称和描述，用于系统提示词
    返回格式化为列表的技能信息
    """
    skills_dir = SKILLS_DIR

    if not os.path.exists(skills_dir):
        return "暂无可用技能。"

    skills = []
    for d in os.listdir(skills_dir):
        skill_dir = os.path.join(skills_dir, d)
        if not os.path.isdir(skill_dir):
            continue

        # 支持配置的技能文件名称（大小写）
        skill_path = None
        for filename in SKILL_FILE_NAMES:
            candidate_path = os.path.join(skill_dir, filename)
            if os.path.exists(candidate_path):
                skill_path = candidate_path
                break

        if os.path.exists(skill_path):
            # 只读取技能元数据（名称+描述），不读取完整内容
            try:
                with open(skill_path, 'r', encoding='utf-8') as f:
                    desc = ""
                    # 只读取前20行找description，避免大文件占用token
                    for _ in range(20):
                        line = f.readline()
                        if not line:
                            break
                        if line.startswith("description:"):
                            desc = line.split(":", 1)[1].strip()
                            break
                skills.append(f"- {d}: {desc}")
            except Exception as e:
                skills.append(f"- {d}: 无描述")

    if not skills:
        return "暂无可用技能。"

    skills_text = "\n".join(skills)
    usage_note = f"\n\n使用说明：需要使用某个技能时，用file_read工具读取对应SKILL.md文件即可，例如：file_read(filepath='{SKILLS_DIR}/neuralbridge-operation-standard/SKILL.md')"

    return skills_text + usage_note


# ── 工具初始化 ──────────────────────────────────────────────
# 从basic_tools导入的ALL_TOOLS已经是@tool装饰的函数，直接使用即可




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
    ):
        self.ui = ui
        self.base_system_prompt = system_prompt
        self.max_iterations = max_iterations
        self.llm_config = llm_config or {}

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

            return "[环境状态感知] " + "；".join(descs) + "。据此调整回复语气。但不要反复重复提醒，避免用户反感。"
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
        skills_list = load_skills_list()

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

        # 持久化存储
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

    async def run_conversation(self, user_message: str) -> Tuple[str, bool, int]:
        """
        运行对话
        Args:
            user_message: 用户输入消息
        Returns:
            (响应内容, 是否使用了流式输出, 本次对话调用工具次数)
        """
        try:
            full_response = ""
            progress_display = None
            tool_call_count = 0  # 统计本次对话的工具调用次数
            start_time = datetime.now()  # 记录开始时间，用于总耗时

            # 初始化进度显示
            if self.ui and hasattr(self.ui, 'create_progress_display'):
                progress_display = self.ui.create_progress_display()
                progress_display.__enter__()
                progress_display.update("思考中")

            # 环境感知：使用缓存数据（后台异步刷新，不阻塞）
            # 首次对话无缓存时跳过，后续由后台任务自动刷新
            env_tag = getattr(self, '_cached_env_tag', None)
            enriched_message = f"{env_tag}\n\n{user_message}" if env_tag else user_message

            # 使用多种stream模式同时获取消息流和执行更新
            async for chunk in self.agent.astream(
                {"messages": [HumanMessage(content=enriched_message)]},
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
                        # 如果是首次收到内容，先关闭进度显示
                        if progress_display:
                            progress_display.__exit__(None, None, None)
                            progress_display = None

                        # 实时输出到UI
                        if self.ui and hasattr(self.ui, 'print_stream_chunk'):
                            self.ui.print_stream_chunk(message_chunk.content)
                        # 收集完整响应
                        full_response += message_chunk.content

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
                        elif source == "tools":
                            # 工具执行完成
                            message = update["messages"][-1]
                            tool_name = message.name if hasattr(message, 'name') else "工具"
                            progress_display.update(f"处理 {tool_name} 结果")

            # 关闭进度显示
            if progress_display:
                progress_display.__exit__(None, None, None)

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

    def clear_history(self) -> None:
        """清空对话历史"""
        # 生成新的thread_id，重置会话
        import uuid
        self.config = {
            "configurable": {
                "thread_id": str(uuid.uuid4())
            },
            "recursion_limit": self.max_iterations
        }
=======
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
from typing import List, Tuple, Dict, Any, Optional, Callable
from langchain_core.tools import StructuredTool
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, AIMessageChunk, ToolMessage
from langgraph.checkpoint.memory import MemorySaver
from langchain_openai import ChatOpenAI
from langchain.agents.middleware import ModelCallLimitMiddleware, SummarizationMiddleware, wrap_tool_call
from langchain.agents.middleware.types import AgentMiddleware, ModelResponse
from langchain_core.messages.utils import count_tokens_approximately
from .llm import LLMManager
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
)
from .prompts.agent_enhance import prompt as agent_enhance_prompt
from .tools.basic_tools import ALL_TOOLS


# ── 技能加载工具 ──────────────────────────────────────────────
def load_skills_list() -> str:
    """
    预加载所有可用技能的名称和描述，用于系统提示词
    返回格式化为列表的技能信息
    """
    skills_dir = SKILLS_DIR

    if not os.path.exists(skills_dir):
        return "暂无可用技能。"

    skills = []
    for d in os.listdir(skills_dir):
        skill_dir = os.path.join(skills_dir, d)
        if not os.path.isdir(skill_dir):
            continue

        # 支持配置的技能文件名称（大小写）
        skill_path = None
        for filename in SKILL_FILE_NAMES:
            candidate_path = os.path.join(skill_dir, filename)
            if os.path.exists(candidate_path):
                skill_path = candidate_path
                break

        if os.path.exists(skill_path):
            # 只读取技能元数据（名称+描述），不读取完整内容
            try:
                with open(skill_path, 'r', encoding='utf-8') as f:
                    desc = ""
                    # 只读取前20行找description，避免大文件占用token
                    for _ in range(20):
                        line = f.readline()
                        if not line:
                            break
                        if line.startswith("description:"):
                            desc = line.split(":", 1)[1].strip()
                            break
                skills.append(f"- {d}: {desc}")
            except Exception as e:
                skills.append(f"- {d}: 无描述")

    if not skills:
        return "暂无可用技能。"

    skills_text = "\n".join(skills)
    usage_note = f"\n\n使用说明：需要使用某个技能时，用file_read工具读取对应SKILL.md文件即可，例如：file_read(filepath='{SKILLS_DIR}/neuralbridge-operation-standard/SKILL.md')"

    return skills_text + usage_note


# ── 工具初始化 ──────────────────────────────────────────────
# 从basic_tools导入的ALL_TOOLS已经是@tool装饰的函数，直接使用即可




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
    ):
        self.ui = ui
        self.base_system_prompt = system_prompt
        self.max_iterations = max_iterations
        self.llm_config = llm_config or {}

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

            return "[环境状态感知] " + "；".join(descs) + "。据此调整回复语气。但不要反复重复提醒，避免用户反感。"
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
        skills_list = load_skills_list()

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

        # 持久化存储
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

    async def run_conversation(self, user_message: str) -> Tuple[str, bool, int]:
        """
        运行对话
        Args:
            user_message: 用户输入消息
        Returns:
            (响应内容, 是否使用了流式输出, 本次对话调用工具次数)
        """
        try:
            full_response = ""
            progress_display = None
            tool_call_count = 0  # 统计本次对话的工具调用次数
            start_time = datetime.now()  # 记录开始时间，用于总耗时

            # 初始化进度显示
            if self.ui and hasattr(self.ui, 'create_progress_display'):
                progress_display = self.ui.create_progress_display()
                progress_display.__enter__()
                progress_display.update("思考中")

            # 环境感知：使用缓存数据（后台异步刷新，不阻塞）
            # 首次对话无缓存时跳过，后续由后台任务自动刷新
            env_tag = getattr(self, '_cached_env_tag', None)
            enriched_message = f"{env_tag}\n\n{user_message}" if env_tag else user_message

            # 使用多种stream模式同时获取消息流和执行更新
            async for chunk in self.agent.astream(
                {"messages": [HumanMessage(content=enriched_message)]},
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
                        # 如果是首次收到内容，先关闭进度显示
                        if progress_display:
                            progress_display.__exit__(None, None, None)
                            progress_display = None

                        # 实时输出到UI
                        if self.ui and hasattr(self.ui, 'print_stream_chunk'):
                            self.ui.print_stream_chunk(message_chunk.content)
                        # 收集完整响应
                        full_response += message_chunk.content

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
                        elif source == "tools":
                            # 工具执行完成
                            message = update["messages"][-1]
                            tool_name = message.name if hasattr(message, 'name') else "工具"
                            progress_display.update(f"处理 {tool_name} 结果")

            # 关闭进度显示
            if progress_display:
                progress_display.__exit__(None, None, None)

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

    def clear_history(self) -> None:
        """清空对话历史"""
        # 生成新的thread_id，重置会话
        import uuid
        self.config = {
            "configurable": {
                "thread_id": str(uuid.uuid4())
            },
            "recursion_limit": self.max_iterations
        }
