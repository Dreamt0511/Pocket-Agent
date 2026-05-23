# MIUI浏览器收藏夹整理技能

## 概述
用于自动整理 MIUI 系统浏览器（`com.android.browser`）的收藏夹/书签，自动创建分组并按主题归类书签。

## 应用信息
- **包名**: `com.android.browser`
- **应用名**: MIUI系统浏览器（MIUI Browser）
- **适用设备**: Xiaomi/Redmi 手机（MIUI/HyperOS系统）

## 操作步骤

### 第一步：打开浏览器并进入书签管理页
```shell
# 启动MIUI系统浏览器
am start -p com.android.browser

# 等待加载
mcp_call android_wait_for_idle timeout_ms=5000

# 获取UI树确认
mcp_call android_get_ui_tree max_depth=50

# 点击底部"我的"按钮（resource_id: com.android.browser:id/action_person）
mcp_call android_tap text="我的"

# 等待
mcp_call android_wait_for_idle timeout_ms=5000

# 点击"书签"入口
mcp_call android_tap text="书签"

# 等待进入书签管理页
mcp_call android_wait_for_idle timeout_ms=5000
```

### 第二步：浏览并获取所有书签列表
```python
# 滑动浏览所有书签（屏幕分辨率1080x2400左右适用）
mcp_call android_swipe start_x=610 start_y=2000 end_x=610 end_y=800 duration_ms=300

# 多次滑动获取完整列表
mcp_call android_wait_for_idle timeout_ms=3000
mcp_call android_get_ui_tree max_depth=60
```

### 第三步：创建分组文件夹

**关键元素**：
- 添加分组按钮：`text="添加分组"`
- 分组名称输入框：`resource_id="com.android.browser:id/edit_text"`
- 确定按钮：`text="确定"`

**操作流程**（循环为每个分组执行）：
```python
# 1. 点击"添加分组"
mcp_call android_tap text="添加分组"
mcp_call android_wait_for_idle timeout_ms=3000

# 2. 输入分组名称
mcp_call android_input_text text="分组名称" resource_id="com.android.browser:id/edit_text"

# 3. 点击确定
mcp_call android_tap text="确定"
mcp_call android_wait_for_idle timeout_ms=3000
```

### 第四步：将书签移动到对应分组

**关键元素**：
- 书签条目：每个书签有长按/点击操作
- 编辑书签按钮：`text="编辑书签"`
- 位置选择器：目标分组列表

**操作流程**：
```python
# 1. 在书签列表中找到目标书签，点击进入编辑
mcp_call android_tap text="编辑书签"  # 或点击书签条目后出现的编辑按钮
mcp_call android_wait_for_idle timeout_ms=3000

# 2. 滑动找到位置选择区域
mcp_call android_swipe start_x=610 start_y=2300 end_x=610 end_y=600 duration_ms=400

# 3. 点击选择目标分组（坐标根据UI树获取）
# HuggingFace模型分组：x=1089, y=577（示例，需从UI树获取准确坐标）
# 开发工具分组：x=1089, y=1273（示例）
# 魔搭ModelScope分组：x=1089, y=1969（示例）
mcp_call android_tap x=1089 y=577

# 4. 等待完成
mcp_call android_wait_for_idle timeout_ms=3000
mcp_call android_get_ui_tree max_depth=40
```

## 关键坐标参考（1080×2400分辨率）

| 元素 | 坐标/标识 |
|------|-----------|
| 底部"我的" | `resource_id="com.android.browser:id/action_person"` 或 `text="我的"` |
| "书签"入口 | `text="书签"` |
| "添加分组"按钮 | `text="添加分组"` |
| 分组名称输入框 | `resource_id="com.android.browser:id/edit_text"` |
| "确定"按钮 | `text="确定"` |
| "编辑书签"按钮 | `text="编辑书签"` |
| 返回按钮 | `content_desc="返回"` 或 `android_press_key key="back"` |

### 位置选择坐标（分组选择器中的选项）
- HuggingFace模型：`x=1089, y=577`
- 开发工具：`x=1089, y=1273` 或 `x=1089, y=1312`
- Ollama：`x=1089, y=1312`
- 魔搭ModelScope：`x=1089, y=1969`

> ⚠️ 坐标因屏幕分辨率和滚动位置而异，执行前必须通过 `android_get_ui_tree` 获取准确坐标。

## 文本输入方案

MIUI浏览器的文本输入框（创建分组时）支持 `android_input_text` 直接输入，优先级：
1. **方案A** ✅ `android_input_text` — 直接向 `com.android.browser:id/edit_text` 输入文本，成功率最高
2. **方案B** `android_set_clipboard` + `android_press_key paste` — 兜底方案
3. **方案C** 逐字符模拟键盘输入

## 失败经验与注意事项

### 常见错误
1. **包名错误**：MIUI浏览器包名是 `com.android.browser`，不是 `com.android.chrome` 或 `com.miui.browser`
2. **坐标硬编码**：不同分辨率手机坐标不同，必须每次从UI树获取
3. **多浏览器选择弹窗**：首次打开可能弹出"选择浏览器"弹窗，需选择"仅一次"并确认

### 性能优化建议
- 书签数量较多时（如20+），逐个编辑移动耗时较长（约600s），可考虑批量操作
- 分组名称输入后，用 `android_wait_for_idle(timeout_ms=3000)` 代替 `sleep`
- 每次点击后只需要一次 `wait_for_idle` + 一次 `get_ui_tree`，不要重复调用

### 已知问题
- MIUI浏览器书签管理的UI元素层级较深（max_depth需设到50-80才能完整获取）
- 创建分组时，输入框有时需点击两次才能聚焦（先tap坐标再input_text）
- Android 16+ 上 `settings get secure default_browser_package` 可能被限制访问

## 执行流程模板
```
1. am start -p com.android.browser
2. android_wait_for_idle + android_get_ui_tree
3. android_tap "我的" → 等待 → android_tap "书签"
4. 滑动浏览所有书签，收集标题列表
5. 分析书签内容 → 规划分组方案
6. 循环创建分组：点击"添加分组" → input_text → 确定
7. 循环移动书签：点击书签 → "编辑书签" → 选择分组 → 确认
8. 截图验证整理结果
9. task.json 标记 completed + 写入总结
```
