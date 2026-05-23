---
name: miui-browser-bookmark
description: 在MIUI系统浏览器（com.android.browser）中管理收藏夹/书签，包括查看书签列表、创建分组、将书签移动到对应分组。涉及多步UI操作，需严格按流程执行。
---

# MIUI浏览器收藏夹整理技能

> **前置条件**：执行前先查阅 `neuralbridge-operation-standard` 了解MCP工具调用规范（坐标计算、验证三原则等），本技能只描述浏览器书签管理的特有业务逻辑。

## 一、基础信息

| 项目 | 内容 |
|------|------|
| 包名 | `com.android.browser` |
| 启动方式 | `mcp_call(tool_name="android_launch_app", arguments={"package_name": "com.android.browser"})` |
| MCP地址 | `http://127.0.0.1:7474/mcp` |
| 适用设备 | Xiaomi/Redmi 手机（MIUI/HyperOS系统） |

## 二、核心流程

### 步骤1：打开浏览器并进入书签管理页

1. `mcp_call(tool_name="android_launch_app", arguments={"package_name": "com.android.browser"})`
2. `mcp_call(tool_name="android_wait_for_idle", arguments={"timeout_ms": 5000})`
3. `mcp_call(tool_name="android_get_ui_tree")` 获取首页UI，确认加载完成
4. 查找底部"我的"按钮（resource_id: `com.android.browser:id/action_person` 或 text="我的"），点击
5. `mcp_call(tool_name="android_wait_for_idle", arguments={"timeout_ms": 5000})`
6. 查找"书签"入口（text="书签"），点击
7. 等待进入书签管理页

### 步骤2：获取书签列表

1. `mcp_call(tool_name="android_get_ui_tree")` 获取书签列表的UI树
2. 遍历UI树提取所有书签条目的标题和链接
3. 如果列表较长需滑动查看更多，使用 `android_swipe` 从底部向顶部滑动
4. 每次滑动后 `android_wait_for_idle` → `android_get_ui_tree` 获取更多书签

### 步骤3：创建分组文件夹（循环为每个分组执行）

1. 查找并点击 `text="添加分组"` 按钮
2. `android_wait_for_idle` 等待弹窗出现
3. `android_get_ui_tree` 定位输入框（resource_id: `com.android.browser:id/edit_text`）
4. 计算中心坐标，用 `android_input_text` 输入分组名称
5. 查找并点击 `text="确定"` 按钮
6. `android_wait_for_idle` 等待分组创建完成

### 步骤4：将书签移动到对应分组

1. 在书签列表中找到目标书签，点击进入编辑
2. `android_wait_for_idle` 等待编辑界面
3. `android_get_ui_tree` 查找"编辑书签"按钮或书签条目的编辑入口
4. 点击后获取UI树，找到位置/分组选择区域
5. 滑动找到目标分组，从UI树获取分组元素的bounds，计算中心坐标点击
6. `android_wait_for_idle` 确认移动完成
7. 保存/返回，继续处理下一个书签

## 三、工具调用规范

所有 `mcp_call` 必须使用标准函数调用格式，**禁止**使用空格分隔参数：

```python
# ✅ 正确格式
mcp_call(tool_name="android_tap", arguments={"x": 315, "y": 1002})
mcp_call(tool_name="android_wait_for_idle", arguments={"timeout_ms": 5000})
mcp_call(tool_name="android_get_ui_tree", arguments={"max_depth": 50})
mcp_call(tool_name="android_swipe", arguments={"start_x": 610, "start_y": 2000, "end_x": 610, "end_y": 800, "duration_ms": 300})

# ❌ 错误格式（禁止使用）
mcp_call android_tap x=315 y=1002
mcp_call android_wait_for_idle timeout_ms=5000
```

## 四、错误处理

| 问题 | 处理方案 |
|------|---------|
| 找不到"我的"按钮 | 检查 `com.android.browser` 是否启动成功，尝试查找其他底部导航元素（如 text="菜单"） |
| 找不到"书签"入口 | 获取UI树查找所有可点击文本元素，可能入口名称不同（如"收藏夹"） |
| 添加分组按钮不存在 | 检查是否已存在分组，或查看是否有其他创建方式的入口 |
| `android_input_text` 无效 | 降级使用剪贴板+paste方案（`set_clipboard` → tap聚焦 → `press_key(paste)`） |
| 找不到目标分组 | 滑动列表后重新获取UI树，确认分组是否已创建成功 |

## 五、注意事项

- 所有点击坐标必须从 `android_get_ui_tree` 的 bounds 计算，**禁止硬编码坐标**
- 滑动参数中的坐标仅作为方向参考，具体数值需根据屏幕分辨率调整
- 每个操作后必须 `android_wait_for_idle` 再获取UI树验证
- 书签管理涉及多步操作，每一步都需验证上一步执行成功后再继续
- 如果浏览器UI版本差异大导致入口不同，以 `android_get_ui_tree` 返回的实际元素为准
