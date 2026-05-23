---
name: cainiao-check-and-calendar-reminder
description: 在菜鸟APP查看未取快递信息（取件码、运单号等），并在系统日历中添加取件提醒事件。涉及两个APP间的跳转，需严格按流程执行。
---

# 菜鸟快递查看 + 日历提醒技能

> **前置条件**：执行前先查阅 `neuralbridge-operation-standard` 了解MCP工具调用规范（坐标计算、验证三原则等），本技能只描述业务逻辑流程。

## 一、基础信息

| 项目 | 内容 |
|------|------|
| 菜鸟包名 | `com.cainiao.wireless` |
| 日历包名 | `com.android.calendar` |
| MCP地址 | `http://127.0.0.1:7474/mcp` |
| 启动方式 | `mcp_call(tool_name="android_launch_app", arguments={"package_name": "包名"})` |

## 二、核心流程

### 步骤1：打开菜鸟APP并处理开屏广告

1. 调用 `android_launch_app` 启动菜鸟
2. 调用 `android_wait_for_idle`（超时3000ms）等待界面稳定
3. 调用 `android_get_ui_tree` 检查是否有开屏广告
   - 如果找到 "跳过" 按钮 → 用 `android_find_elements` 定位其 bounds → 计算中心坐标 → `android_tap` 点击
   - 如果没有广告 → 继续下一步

### 步骤2：查找未取快递信息

1. 调用 `android_get_ui_tree` 获取首页UI树
2. 查找"到站包裹"或"待取件"区域的元素
3. 查找包裹卡片中的关键信息：
   - **取件码**（如 `501-1-4007`，通常格式为数字+数字组合）
   - **快递公司**（如极兔速递、中通等）
   - **状态**（如已入站3天）
   - **驿站名称**
4. **点击包裹卡片**进入详情页查看运单号
5. 详情页调用 `android_get_ui_tree`，查找包含"运单号"或"JT"等格式的文本
   - 运单号格式示例：`JT5487030073720`
6. 记录所有信息

### 步骤3：返回桌面并打开日历

1. `android_press_key(key="home")` 返回桌面
2. `android_wait_for_idle` 等待桌面稳定
3. `android_launch_app` 启动日历

### 步骤4：创建日历事件

1. 调用 `android_wait_for_idle` 等待日历加载
2. 调用 `android_get_ui_tree` 查找"新建"或"+"按钮
3. 点击新建按钮
4. 再次 `android_get_ui_tree` 查找输入框
5. **输入自然语言内容**：`{"text": "5月25日11:55取快递"}`（日期根据实际调整）
   - 使用 `android_input_text` 工具，参数 `text` 为日期+时间+事件描述
6. 等待建议弹出（`android_wait_for_idle`）
7. 调用 `android_get_ui_tree` 查找系统建议内容区域
8. **点击建议内容区域**使系统自动填表
9. 验证开始时间已更新为目标时间
10. 查找并点击"确定"/"保存"按钮

### 步骤5：验证

1. `android_wait_for_idle` 等待
2. `android_get_ui_tree` 或 `android_screenshot` 确认日期上有日程标记
3. 记录验证结果

## 三、错误处理

| 问题 | 处理方案 |
|------|---------|
| 菜鸟打不开/闪退 | 重试1次，仍失败则跳过菜鸟步骤，告知用户APP问题 |
| 找不到未取快递 | 检查UI树中是否有"暂无包裹"或类似空状态提示，有则告知用户无待取件 |
| 日历找不到新建按钮 | 尝试查找FloatingActionButton，或使用 `android_find_elements(clickable=True)` 查找可点击元素 |
| 智能输入不识别自然语言 | 降级方案：手动设置各字段（标题、日期、时间），通过UI树找到对应输入框逐个填写 |
| 保存后验证失败 | 重新获取UI树确认事件是否存在，必要时截图确认 |

## 四、注意事项

- 菜鸟APP可能有开屏广告，每次启动都需检查
- 日历智能输入框支持自然语言解析，优先使用此方式
- **必须点击系统弹出的建议内容**，仅输入文字不会自动更新时间和日期
- 操作间注意加 `android_wait_for_idle` 确保界面稳定
- 如果系统日历包名不匹配（MIUI等定制系统），尝试 `com.miui.calendar` 或 `com.android.calendar`
