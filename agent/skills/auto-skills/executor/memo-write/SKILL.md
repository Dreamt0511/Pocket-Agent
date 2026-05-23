---
name: memo-write
description: 在小米备忘录（com.miui.notes）中创建新笔记并写入文本内容。涉及WebView编辑器的粘贴操作，需严格按流程执行。
---

# 小米备忘录写入技能

> **前置条件**：执行前先查阅 `neuralbridge-operation-standard` 了解MCP工具调用规范（坐标计算、验证三原则等），本技能只描述备忘录特有的业务逻辑。

## 一、基础信息

| 项目 | 内容 |
|------|------|
| 包名 | `com.miui.notes` |
| 启动方式 | `mcp_call(tool_name="android_launch_app", arguments={"package_name": "com.miui.notes"})` |
| MCP地址 | `http://127.0.0.1:7474/mcp` |
| 编辑器类型 | WebView（不可用 `android_input_text`，需用剪贴板+粘贴方案） |

## 二、核心流程

### 步骤1：启动备忘录

1. `mcp_call(tool_name="android_launch_app", arguments={"package_name": "com.miui.notes"})`
2. `mcp_call(tool_name="android_wait_for_idle", arguments={"timeout_ms": 5000})`

### 步骤2：创建新笔记

1. 调用 `android_get_ui_tree` 获取主界面UI树
2. 查找资源ID为 `com.miui.notes:id/note_add`（content_desc="创建笔记"）的按钮
3. 从 bounds 计算中心坐标并点击
4. `android_wait_for_idle` 等待编辑界面加载

### 步骤3：输入内容（WebView粘贴方案）

小米笔记编辑器是 **WebView** 类型，`android_input_text` 无效，必须使用剪贴板+粘贴：

1. **设置剪贴板内容**：
   ```
   mcp_call(tool_name="android_set_clipboard", arguments={"text": "要写入的完整内容"})
   ```
   （或用 shell_exec：`termux-clipboard-set '内容'`）

2. **获取UI树**，定位内容编辑区（通常是 `android.widget.EditText` 或可聚焦的 WebView 区域），计算中心坐标

3. **点击编辑区聚焦**：
   ```
   mcp_call(tool_name="android_tap", arguments={"x": 中心x, "y": 中心y})
   ```

4. **立即调用粘贴**：
   ```
   mcp_call(tool_name="android_press_key", arguments={"key": "paste"})
   ```

5. 验证内容是否写入：`android_find_elements(class_name="android.widget.EditText", find_all=true)` 检查 text 字段

### 步骤4：保存并返回

1. 查找"完成"或"✓"按钮（通常 resource_id 含 `done` 或 content_desc 为"完成编辑"）
2. 点击保存
3. `android_wait_for_idle` 等待保存完成
4. `android_press_key(key="back")` 返回笔记列表

## 三、错误处理

| 问题 | 处理方案 |
|------|---------|
| paste 报 "no focused input field" | 重新点击编辑区聚焦后再试 paste，最多重试2次 |
| 找不到创建笔记按钮 | 检查是否是不同版本UI，尝试查找 FloatingActionButton 或 content_desc 含"新建"/"写笔记"的元素 |
| 验证内容为空 | 重新设置剪贴板 → 聚焦 → paste，可能是内容太长或剪贴板未设置成功 |
| 找不到保存按钮 | 尝试 `android_press_key(key="back")`，系统可能自动保存草稿 |

## 四、注意事项

- 坐标必须从UI树获取，**禁止硬编码**（不同分辨率设备坐标不同）
- WebView 编辑器不支持 `android_input_text`，优先用剪贴板+paste
- paste 前必须点击编辑区聚焦，两次操作之间加 `android_wait_for_idle`（300ms即可）
- 内容较长时建议分批粘贴，或确保一次完整设置到剪贴板
