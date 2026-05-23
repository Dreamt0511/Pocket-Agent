---
name: chinamobile_query_balance
description: 在中国移动APP（com.greenpoint.android.mc10086.activity）中查询话费余额、流量使用情况及历史账单对比
---

# chinamobile_query_balance

## 任务目标
查询中国移动APP中的话费、流量及历史流量对比

## 执行步骤
- [compled] 步骤1：打开中国移动APP（com.greenpoint.android.mc10086.activity）
- [compled] 步骤2：等待APP加载，处理开屏广告或更新弹窗（点击"暂不更新"、关闭广告）
- [compled] 步骤3：在首页查看话费余额（71.80元）
- [compled] 步骤4：通过"我的"→"余量查询"查看剩余流量和本月已用流量
- [compled] 步骤5：通过"我的"→"账单查询"查看历史月份费用对比
- [compled] 步骤6：汇总所有信息

## 关键操作
- **包名**：`com.greenpoint.android.mc10086.activity`
- **启动方式**：`am start -p com.greenpoint.android.mc10086.activity`
- **弹窗处理**：
  - 首次启动可能弹出"选择要使用的应用"选择器 → 点击第一个"中国移动"→ 点击"仅一次"
  - 更新弹窗 → 点击"暂不更新"
  - 广告弹窗 → 找到 close_btn（resource_id: `com.greenpoint.android.mc10086.activity:id/close_btn`）点击关闭
- **主要MCP工具**：android_wait_for_idle, android_get_ui_tree, android_tap, android_screenshot
- **关键信息获取路径**：
  - 首页顶部卡片直接显示：话费余额、通用流量剩余、通话剩余
  - "我的"页面 → "余量查询" 查看详细流量使用（国内通用/定向/其他流量）
  - "我的"页面 → "账单查询" 查看历史月份消费对比（支持2025.11~2026.5）
- **注意事项**：
  - 首次启动可能弹出应用选择器，需要处理
  - 启动后可能有更新弹窗和广告弹窗两个弹窗需要依次关闭
  - "余量查询"和"账单查询"都在"我的"页面的"我的服务"功能区

## 适用场景
需要查询中国移动手机号的话费余额、套餐余量（流量/通话）、本月已用流量明细、历史月份账单对比时使用
