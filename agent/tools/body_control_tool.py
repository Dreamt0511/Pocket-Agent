"""
Pocket Agent 3D - 身体控制工具定义
用于让Agent控制3D虚拟身体
"""

import os
import json
import time
import requests
import threading

# 部位名称 → 骨骼名称映射
BONE_MAP = {
    "head": "head",
    "right_arm": "right_hand",
    "left_arm": "left_hand",
    "right_forearm": "da_shou",
    "right_elbow": "da_shou",
    "left_forearm": "da_shou2",
    "left_elbow": "da_shou2",
    "right_ear": "you_ear",
    "left_ear": "zuo_ear2",
    "right_leg": "right_leg",
    "left_leg": "left_leg",
    "right_calf": "da_tui",
    "left_calf": "da_tui2",
    "body": "body",
    "root": "root",
}

# 服务器地址（可通过环境变量配置）
BODY_SERVER_URL = os.getenv("BODY_SERVER_URL", "http://localhost:18081")

# 尝试导入 langchain_core，如果失败则使用简单的装饰器
try:
    from langchain_core.tools import tool
except ImportError:
    # 简单的工具装饰器替代
    def tool(func):
        return func

# 服务器线程和服务器实例
_server_thread = None
_server_instance = None

def start_body_server(port=18081):
    """启动身体控制服务器（在后台线程运行）"""
    global _server_thread, _server_instance
    if _server_thread and _server_thread.is_alive():
        return

    from .body_server import ThreadedHTTPServer, BodyControlHandler

    # 清理旧实例
    stop_body_server()

    try:
        _server_instance = ThreadedHTTPServer(('0.0.0.0', port), BodyControlHandler)
    except OSError:
        time.sleep(0.2)
        try:
            _server_instance = ThreadedHTTPServer(('0.0.0.0', port), BodyControlHandler)
        except OSError as e:
            print(f"❌ 无法启动身体控制服务器: {e}")
            return

    _server_thread = threading.Thread(target=_server_instance.serve_forever, daemon=True)
    _server_thread.start()

def stop_body_server():
    """停止身体控制服务器，释放端口"""
    global _server_instance, _server_thread
    srv = _server_instance
    _server_instance = None
    _server_thread = None
    if srv:
        try:
            srv._BaseServer__shutdown_request = True
            srv.socket.close()
        except Exception:
            pass
        try:
            srv.server_close()
        except Exception:
            pass

@tool
def control_body(part: str, x: float = 0, y: float = 0, z: float = 0) -> str:
    """
    控制3D虚拟身体各部位的旋转。可以做挥手、点头、转身、跳舞等各种动作。

    重要规则：
    - 开始新动作前，必须先调用 body_idle() 归位
    - 完成动作后，根据场景自行判断是否需要归位（如打招呼后可保持，跳舞后应归位）

    各部位方向说明（已验证）：
    - "head": 头部。x正=低头前倾, x负=抬头后仰; y正=左转, y负=右转
    - "right_arm": 右臂。z正=抬起, z负=放下; y负=向前伸, y正=向后收
    - "left_arm": 左臂。z负=抬起, z正=放下; y正=向前伸, y负=向后收
    - "right_forearm" / "right_elbow": 右前臂/手肘。z负=弯曲, z正=伸直
    - "left_forearm" / "left_elbow": 左前臂/手肘。z正=弯曲, z负=伸直
    - "right_ear": 右耳天线。x正=前倾, x负=后仰
    - "left_ear": 左耳天线。x正=前倾, x负=后仰
    - "right_leg": 右腿。x负=向前抬, x正=向后收; z正=左摆, z负=右摆
    - "left_leg": 左腿。x负=向前抬, x正=向后收; z正=右摆, z负=左摆
    - "right_calf": 右小腿。x负=前伸, x正=后收
    - "left_calf": 左小腿。x负=前伸, x正=后收
    - "body": 躯干（上身整体，手臂和头跟着动）。x正=前倾, x负=后仰; y正=左转(拧腰), y负=右转; z正=右倾, z负=左倾
    - "root": 全身。y正=左转, y负=右转

    参考值（仅供参考，可自由组合）：
    - 举手：right_arm z=60
    - 弯手肘：right_elbow z=-60
    - 点头：head x=15
    - 耳朵前倾：right_ear x=30
    - 弯腰前倾：body x=30~60
    - 转身：root y=90
    - 走路交替抬腿：right_leg x=-20, left_leg x=20

    Args:
        part: 身体部位名称
        x: 绕x轴旋转角度（度），默认0
        y: 绕y轴旋转角度（度），默认0
        z: 绕z轴旋转角度（度），默认0
    """
    bone = BONE_MAP.get(part)
    if not bone:
        return f"错误：未知部位 '{part}'，可用部位：{', '.join(BONE_MAP.keys())}"

    # 发送HTTP请求到前端
    try:
        response = requests.post(
            f'{BODY_SERVER_URL}/api/set_bone',
            json={'bone': bone, 'x': x, 'y': y, 'z': z},
            timeout=5
        )
        if response.status_code == 200:
            result = response.json()
            return f"已设置 {part} 旋转为 ({x}, {y}, {z})"
        else:
            return f"错误：服务器返回状态码 {response.status_code}"
    except Exception as e:
        return f"错误：无法连接到身体控制服务器 - {str(e)}"


@tool
def move_body(x: float = 0, y: float = 0, z: float = 0) -> str:
    """
    移动3D虚拟身体的整体位置（位移，不是旋转）。

    配合 control_body 旋转可以做出更多动作，比如趴下、蹲下、跳跃等。
    开始新动作前必须先调用 body_idle() 归位。

    位移方向：
    - x：正=向右，负=向左
    - y：正=向上，负=向下（降低身体可以蹲下/趴下）
    - z：正=向前，负=向后

    示例：
    - 蹲下：y=-0.5
    - 趴下：y=-1.0（配合身体前倾旋转）
    - 跳跃：y=0.5
    - 向前走：z=0.3

    Args:
        x: 左右位移，默认0
        y: 上下位移（负=向下），默认0
        z: 前后位移，默认0
    """
    try:
        response = requests.post(
            f'{BODY_SERVER_URL}/api/set_position',
            json={'x': x, 'y': y, 'z': z},
            timeout=5
        )
        if response.status_code == 200:
            return f"已移动身体到 ({x}, {y}, {z})"
        else:
            return f"错误：服务器返回状态码 {response.status_code}"
    except Exception as e:
        return f"错误：无法连接到身体控制服务器 - {str(e)}"


@tool
def body_script(moves: str) -> str:
    """
    执行一段身体动作脚本，可以连续快速控制多个部位，适合跳舞、表演等复杂动作。

    moves 是一个JSON数组，每个元素包含：
    - action: "bone"（旋转）或 "pos"（位移）或 "idle"（归位）
    - part: 部位名（action=bone时需要）
    - x, y, z: 角度或位移值
    - delay: 等待秒数（可选，默认0.2）

    示例 - 挥手打招呼：
    [{"action":"bone","part":"right_arm","z":60,"delay":0.3},
     {"action":"bone","part":"right_arm","y":-20,"z":60,"delay":0.3},
     {"action":"bone","part":"right_arm","y":20,"z":60,"delay":0.3},
     {"action":"idle"}]

    示例 - 蹲下：
    [{"action":"bone","part":"body","x":30,"delay":0.2},
     {"action":"bone","part":"right_leg","x":-30,"delay":0.2},
     {"action":"bone","part":"left_leg","x":-30,"delay":0.2},
     {"action":"pos","x":0,"y":-0.4,"z":0}]

    Args:
        moves: JSON格式的动作序列
    """
    try:
        sequence = json.loads(moves)
    except json.JSONDecodeError as e:
        return f"错误：JSON格式无效 - {e}"

    results = []
    for i, step in enumerate(sequence):
        action = step.get("action", "bone")
        delay = step.get("delay", 0.2)

        try:
            if action == "idle":
                requests.post(f'{BODY_SERVER_URL}/api/idle', timeout=5)
                requests.post(f'{BODY_SERVER_URL}/api/set_position',
                            json={'x':0,'y':0,'z':0}, timeout=5)
            elif action == "pos":
                requests.post(f'{BODY_SERVER_URL}/api/set_position',
                            json={'x':step.get('x',0),'y':step.get('y',0),'z':step.get('z',0)},
                            timeout=5)
            elif action == "bone":
                part = step.get("part", "")
                bone = BONE_MAP.get(part)
                if not bone:
                    results.append(f"步骤{i}: 未知部位 '{part}'")
                    continue
                requests.post(f'{BODY_SERVER_URL}/api/set_bone',
                            json={'bone':bone,'x':step.get('x',0),'y':step.get('y',0),'z':step.get('z',0)},
                            timeout=5)
        except Exception as e:
            results.append(f"步骤{i}: {e}")

        if delay > 0 and i < len(sequence) - 1:
            time.sleep(delay)

    return f"已执行{len(sequence)}步动作" + (f"（错误：{'; '.join(results)}）" if results else "")


@tool
def body_idle() -> str:
    """
    让3D虚拟身体恢复待机状态（原版动画）。

    当你想结束当前动作，让身体自然待机时调用此函数。
    会同时重置所有骨骼旋转和整体位移。
    """
    try:
        requests.post(f'{BODY_SERVER_URL}/api/set_position',
                     json={'x': 0, 'y': 0, 'z': 0}, timeout=5)
        response = requests.post(f'{BODY_SERVER_URL}/api/idle', timeout=5)
        if response.status_code == 200:
            return "已恢复待机状态"
        else:
            return f"错误：服务器返回状态码 {response.status_code}"
    except Exception as e:
        return f"错误：无法连接到身体控制服务器 - {str(e)}"


# 导出工具列表
BODY_TOOLS = [control_body, move_body, body_script, body_idle]
