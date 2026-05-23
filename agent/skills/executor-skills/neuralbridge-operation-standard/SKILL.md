---
name: neuralbridge-operation-standard
description: 【降级方案】NeuralBridge MCP Server 操作规范，仅用于 Android Shell 命令和 Termux API 无法完成的 UI 自动化场景（点击、滑动、UI树定位、截图分析）。包含核心操作规范、性能优化指南、故障排查重试流程，一站式解决所有手机操控问题。执行手机操控任务前，必须先查阅 phone-control-guide skill 查找零 token 方案。
---

# NeuralBridge MCP 操作标准规范

> **使用前提**：执行手机操控任务前，先查阅 `phone-control-guide` skill，优先用 Shell/Termux API。确认零 token 方式不可行后再用 NeuralBridge。

## 工具速查表（32个，不需要调 tools/list）

| 工具名 | 功能 | 关键参数 |
|--------|------|---------|
| `android_get_ui_tree` | 获取UI结构树 | filter, include_invisible, max_depth |
| `android_screenshot` | 截屏 | quality, max_width |
| `android_find_elements` | 按条件查找元素 | text, resource_id, content_desc, class_name, clickable, scrollable, focusable, find_all |
| `android_get_screen_context` | UI树+截图一次获取 | include_all_elements |
| `android_get_notifications` | 获取通知栏 | active_only |
| `android_screenshot_diff` | 两张截图对比找差异 | reference_base64, threshold |
| `android_accessibility_audit` | 无障碍审计 | 无参数 |
| `android_get_recent_toasts` | 获取最近Toast消息 | since_ms |
| `android_tap` | 点击 | x, y, text, resource_id, content_desc |
| `android_long_press` | 长按 | x, y, text, resource_id, duration_ms |
| `android_double_tap` | 双击 | x, y, text, resource_id, content_desc |
| `android_swipe` | 滑动 | start_x, start_y, end_x, end_y, duration_ms |
| `android_pinch` | 双指缩放 | center_x, center_y, scale, duration_ms |
| `android_drag` | 拖拽 | from_x, from_y, to_x, to_y, duration_ms |
| `android_input_text` | 输入文本（仅标准EditText） | text, element_text, resource_id, append |
| `android_press_key` | 按键操作 | key |
| `android_global_action` | 系统操作 | action |
| `android_launch_app` | 启动应用 | package_name, activity, clear_task |
| `android_close_app` | 关闭应用 | package_name, force |
| `android_open_url` | 打开URL | url, browser_package |
| `android_set_clipboard` | 设置剪贴板 | text |
| `android_list_apps` | 列出已安装应用 | filter |
| `android_wait_for_element` | 等待元素出现 | text, resource_id, content_desc, timeout_ms |
| `android_wait_for_gone` | 等待元素消失 | text, resource_id, content_desc, timeout_ms |
| `android_wait_for_idle` | 等待界面稳定（替代sleep） | timeout_ms |
| `android_scroll_to_element` | 滚动到目标元素 | text, resource_id, content_desc, direction, max_scrolls, timeout_ms |
| `android_list_devices` | 列出设备 | 无参数 |
| `android_select_device` | 选择设备 | device_id, auto_enable_permissions |
| `android_search_tools` | 搜索工具 | query, category |
| `android_describe_tools` | 查看工具详情 | tools |
| `android_enable_events` | 启用/禁用事件 | enable, event_types |
| `android_get_device_info` | 获取设备信息 | 无参数 |

> 调用：`mcp_call(tool_name="工具名", arguments={参数})` ｜ 最新列表：`mcp_call(tool_name="tools/list")`

## 核心三原则

1. **坐标禁止猜测**：所有点击/长按/滑动的坐标必须 100% 来自 `android_get_ui_tree` 返回的 bounds，禁止通过截图估算
2. **每步必验证**：操作后先 `android_wait_for_idle`，再用 `android_get_ui_tree` 验证结果，确认成功才下一步
3. **专用工具优先**：启动应用用 `android_launch_app`、按键用 `android_press_key`、查找元素用 `android_find_elements`/`android_get_ui_tree`，禁止用通用点击/滑动模拟专用操作。全程自动执行，禁止半途而废让用户手动

## 常用按键

| key 值 | 说明 | key 值 | 说明 |
|--------|------|--------|------|
| `back` | 返回 | `home` | 桌面 |
| `recents` | 最近任务 | `notifications` | 通知栏 |
| `power` | 电源键 | `enter` | 回车确认 |
| `delete` | 删除/退格 | `space` | 空格 |
| `select_all` | 全选 | `copy` | 复制 |
| `paste` | 粘贴 | `cut` | 剪切 |

## 一、元素定位

1. 调 `android_get_ui_tree` 获取 UI 结构
2. 按 `resource_id` → `text` → `content_desc` 优先级匹配目标元素
3. 从 bounds `[left, top, right, bottom]` 计算中心点：`x=(left+right)//2, y=(top+bottom)//2`
4. 确认 bounds 在屏幕可见范围内，元素 flags 含可交互属性

## 二、验证与降级

- **优先**：操作 → `android_wait_for_idle` → `android_get_ui_tree` 验证状态变化
- **降级**：UI 树无法反映变化时用 `android_screenshot` 肉眼确认
- 验证不通过：重获 UI 树 → 分析原因 → 调整坐标/方案重试，禁止连续盲目点击

## 三、弹窗处理（操作前必须检查）

- **权限申请**：通知/存储等非敏感点"允许"，相机/麦克风等敏感权限询问用户
- **广告/更新**：找"关闭/跳过/×"按钮，没有则按 back 键
- **其他弹窗**：找"确认/知道了"，没有则 back 键
- 弹窗不处理会挡住后续所有操作，必须先处理

## 四、通用输入方案（三步法，优先使用）

适用于所有输入场景（原生 EditText、标准 WebView、自定义渲染等）。核心思路：**剪贴板 + paste 按键**，无需猜测坐标。

### 第一步：识别输入框类型

| 输入类型 | 判断方法 | 代表应用 |
|---------|---------|---------|
| 原生 EditText | `android_find_elements(class_name="android.widget.EditText")` 能找到 | 拼多多客服、闲鱼搜索 |
| 标准 WebView | 无 EditText，但有输入框元素（flags: cf，带 placeholder） | DeepSeek、ChatGPT |
| UCWebView/Rax | 无 EditText，输入框在特殊容器内 | 闲鱼聊天 |

### 第二步：输入方案

**方案A：原生 EditText → `android_input_text`（最简单）**
```python
android_input_text(text="目标内容", resource_id="EditText的resource_id")
```
直接在输入框中填入文本，无需剪贴板。

**方案B：通用三步法（EditText + 标准 WebView + 大部分自定义输入）**

1. `android_tap(x=输入框中心x, y=输入框中心y)` — 点击输入框聚焦
2. `android_set_clipboard(text="目标文本")` — 存入系统剪贴板
3. `android_press_key(key="paste")` — 发送粘贴按键事件（**关键步骤**）
4. 验证：重新获取 UI 树，**检查输入框元素的 text 是否已变化**
5. 点击发送/搜索按钮

> 验证技巧：别在 UI 树找"粘贴"按钮，直接看输入框的 text 从 placeholder 变成了你的内容就说明成功了

**方案C：UCWebView/Rax（`press_key paste` 无效时的降级方案）**

当 `android_press_key(key="paste")` 返回 "no focused input field" 时用此方案。

**核心思路：从 UI 树拿输入框 bounds → 相对坐标计算粘贴按钮位置。** 粘贴按钮在键盘建议栏左上角，紧贴输入框下方，不同设备位置不同但相对关系固定。

1. `android_get_ui_tree` — 获取 UI 树，找到输入框元素的 bounds `[left, top, right, bottom]`
2. 计算坐标：`paste_x = left + 40`（输入框左侧微偏右），`paste_y = bottom + 50`（输入框正下方）
3. `android_set_clipboard(text="目标文本")` — 存入剪贴板
4. `android_tap(x=输入框中心x, y=输入框中心y)` — 点击输入框弹出键盘（若键盘已弹出可跳过）
5. 等待 1 秒，键盘检测到剪贴板内容后会在顶部建议栏显示"粘贴"按钮
6. `android_tap(x=paste_x, y=paste_y)` — 点击粘贴按钮
7. 验证：重新获取 UI 树，检查输入框 text 是否变化
8. 点击发送按钮

> **坐标校准**：若粘贴失败，按 `paste_y += 20` 递增重试（最多 2 次），因为不同键盘的建议栏高度略有差异。禁止无限制重复点击。

### 执行流程（优先级从高到低）

```
Try 方案A: android_input_text
  ├─ 成功 → 继续
  └─ 失败 → Try 方案B: 三步法
              ├─ press_key paste 成功 → 继续
              └─ press_key paste 失败 → Try 方案C: 键盘粘贴建议
```

**禁止**：
- 禁止反复调用 `android_input_text`，失败 1 次就切换方案
- 禁止用 `android_long_press` 尝试触发粘贴菜单（WebView 不弹系统粘贴菜单）
- 禁止直接调用系统 `input` 命令（Android 16 无 INJECT_EVENTS 权限）

## 五、高效接口替代（减少调用次数）

| 场景 | 优先 | 避免 |
|------|------|------|
| 查找特定元素 | `android_find_elements` | get_ui_tree 全量+手动过滤 |
| 需要UI树+截图 | `android_get_screen_context` | 分两次调用 |
| 滚动找元素 | `android_scroll_to_element` | 循环 swipe |
| 等待元素出现 | `android_wait_for_element` | 循环 find_elements |

## 六、故障排查流程

1. 分析错误 → 重试 1-2 次确认不是偶发
2. 换方案再试（调整坐标、换定位方式、换专用工具）
3. 所有方案都失败 → 人工介入 tts_speak 通知用户

**分场景排查：**
- **点不动**：重获 UI 树 → 检查可点击属性 → 换点击位置（角/中心）→ 改长按/双击
- **找不到元素**：检查弹窗遮挡 → 确认页面正确 → 滚动后重获 → `scroll_to_element` / `wait_for_element`
- **输入失败**：确认聚焦 → 清空旧内容 → 剪贴板粘贴 → 非标准输入框直接点搜索按钮
- **启动失败**：`list_apps` 验证包名 → `am start` shell 命令 → 桌面找图标点击

**失败报告要求**：必须说明尝试过的所有方法及错误信息。
