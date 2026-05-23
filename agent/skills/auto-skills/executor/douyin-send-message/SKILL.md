---
name: douyin-send-message
description: 在抖音APP中给指定好友发送私信消息（支持文字+表情），涵盖打开应用、进入消息页、搜索好友、进入聊天窗口、输入文字、选择表情、发送消息全流程
---

# douyin-send-message

## 任务目标
给抖音好友"归零"发送消息（文字+表情包）

## 执行步骤
- [compled] 打开抖音APP（am start -p com.ss.android.ugc.aweme）
- [compled] 进入消息/私信页面（点击底部导航栏"消息"按钮）
- [compled] 在消息页面顶部推荐联系人中点击好友"归零."进入聊天窗口（若无推荐，需通过搜索找到好友）
- [compled] 点击输入框（EditText）聚焦，使用 android_input_text 输入文字内容
- [compled] 点击表情按钮打开表情面板，选择一个表情（如[微笑]）
- [compled] 点击发送按钮发送消息

## 关键操作
- **包名**：`com.ss.android.ugc.aweme`
- **启动命令**：`am start -p com.ss.android.ugc.aweme`
- **输入框类型**：原生 EditText（resource_id: `com.ss.android.ugc.aweme:id/msg_et`）
- **输入方案**：方案A（android_input_text），直接对 EditText 使用
- **发送按钮**：resource_id 为 `jb5` 或 `zcd`，content_desc="发送"

### 关键资源ID
| 元素 | 资源ID/描述 |
|------|------------|
| 底部导航"消息"按钮 | content_desc="消息，按钮" |
| 消息输入框 | `com.ss.android.ugc.aweme:id/msg_et` |
| 表情按钮 | content_desc="表情" |
| 发送按钮 | `jb5` 或 `zcd`，content_desc="发送" |
| 聊天头部"返回" | content_desc="返回" |

### MCP调用流程
1. `android_get_ui_tree` → 定位元素位置
2. `android_tap(x, y)` → 点击元素（导航、输入框、发送）
3. `android_input_text(text="内容", resource_id="...")` → 输入文字
4. `android_wait_for_idle(timeout_ms=5000)` → 每次操作后等待

## 注意事项
1. **启动弹窗**：如果系统弹出"选择要使用的应用"，需点击对应抖音应用并选择"仅一次"
2. **消息页布局**：消息页面顶部有推荐联系人列表，可直接点击进入聊天；如需搜索，使用顶部搜索按钮
3. **表情选择**：点击表情按钮后，在经典表情区域选择一个表情（如[微笑]），表情会自动拼接到输入框文本后
4. **发送验证**：发送后输入框清空恢复为"发送消息"提示，聊天区域出现新消息内容和时间戳"刚刚"
5. **输入框变化**：发送前输入框 text 会从"发送消息"变为输入的内容；发送后恢复为"发送消息"

## 适用场景
需要给抖音好友发送私信消息（文字+表情包）时使用，适用于日常聊天、通知、自动回复等场景
