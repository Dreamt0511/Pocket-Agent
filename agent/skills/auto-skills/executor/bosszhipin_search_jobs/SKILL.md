---
name: bosszhipin_search_jobs
description: 在Boss直聘APP中切换城市并搜索岗位，查看岗位详情和JD信息
---

# bosszhipin_search_jobs

## 任务目标
在Boss直聘APP上搜集特定地区特定岗位的JD信息，包括切换地区、搜索关键词、查看多家公司岗位详情。

## 执行步骤
- [completed] 打开Boss直聘APP（com.hpbr.bosszhipin）
- [completed] 将地区切换为深圳
- [completed] 搜索agent开发实习相关岗位
- [completed] 查看搜索结果中多家公司的岗位详情和JD
- [completed] 截图或复制保存搜集到的岗位JD信息
- [completed] 汇报完成情况

## 关键操作
- **包名**：com.hpbr.bosszhipin
- **启动**：android_launch_app(package_name="com.hpbr.bosszhipin")
- **获取UI**：android_get_ui_tree(filter="all")
- **等待**：android_wait_for_idle(timeout_ms=2000)
- **点击**：android_tap(x, y) - 坐标从UI树bounds计算
- **返回**：android_press_key(key="back")
- **剪贴板输入**：android_set_clipboard → android_press_key("paste")
- **截图**：android_screenshot(quality=80)

### 详细操作流程
1. **启动APP** → android_launch_app → wait_for_idle(2000)
2. **切换城市**：点击筛选栏的"城市"按钮 → 在搜索框中输入城市名（剪贴板粘贴） → 点击搜索结果中的城市 → 点击"确定"
3. **搜索岗位**：点击搜索框 → 输入关键词（可直接点击搜索建议） → 等待搜索结果
4. **查看岗位详情**：点击岗位卡片 → 查看JD详情 → 截图保存 → 返回
5. **切换城市注意事项**：搜索结果页中的城市筛选可能需要单独设置，点击城市筛选按钮 → 点"切换城市" → 搜索城市 → 选择

### 注意事项
- 首页切换城市后，搜索页的筛选城市可能不会同步更新，需要在搜索结果页单独切换城市
- 在搜索结果页切换城市时，需要点击城市筛选项 → 点击右上角"切换城市" → 搜索城市 → 选择
- 搜索框中的历史搜索建议可以直接点击，快速输入关键词
- 同一页面内的连续操作（如查看多个岗位详情）可以用back键快速返回

## 适用场景
- 需要在Boss直聘上搜集特定城市、特定岗位的JD信息
- 需要对比多家公司的招聘要求
