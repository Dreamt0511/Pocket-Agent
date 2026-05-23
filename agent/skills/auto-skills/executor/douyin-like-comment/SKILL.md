---
name: douyin-like-comment
description: 抖音APP点赞评论技能——搜索用户、进入主页、给视频点赞、写评论
---

# 抖音点赞评论技能

## 一、基础信息
- **包名**：`com.ss.android.ugc.aweme`
- **启动命令**：`am start -p com.ss.android.ugc.aweme`
- **应用类型**：混合应用（原生 + WebView）
- **输入框类型**：原生 EditText（搜索框），评论框也是原生 EditText

## 二、核心操作流程

### 1. 启动抖音APP
```shell
am start -p com.ss.android.ugc.aweme
```
或使用 MCP：
```
mcp_call android_launch_app package_name="com.ss.android.ugc.aweme"
```
启动后 `android_wait_for_idle(timeout_ms=8000)` 等待加载完成。

### 2. 搜索用户
1. 先点击底部导航栏的**搜索**按钮或顶部搜索图标进入搜索页
2. 在UI树中找到搜索输入框（resource_id: `com.ss.android.ugc.aweme:id/et_search_kw`）
3. 搜索框是**原生 EditText**，使用**方案A**直接输入：
   ```
   mcp_call android_find_elements class_name="android.widget.EditText"
   mcp_call android_input_text text="目标用户名" resource_id="com.ss.android.ugc.aweme:id/et_search_kw"
   ```
4. 点击搜索按钮（通常在键盘右下角或旁边的搜索图标）

### 3. 进入用户主页
1. 在搜索结果中找到目标用户条目
2. 点击用户头像或用户名进入其主页
3. 等待页面加载完成

### 4. 给视频点赞
在用户主页中浏览视频：
1. 点击视频进入播放页，或直接在主页列表中找到视频
2. 点赞按钮通常位于视频右侧（心形图标），在UI树中查找 `content-desc` 包含"赞"或"喜欢"的元素
3. 点击点赞按钮（如果已点亮则无需操作）
4. 验证：检查按钮状态是否变为已赞

### 5. 滑动切换视频
使用下滑手势切换视频：
```
mcp_call android_swipe start_x=610 start_y=1800 end_x=610 end_y=800 duration_ms=500
```
- 从底部（y≈1800）向上滑到顶部（y≈800）切换到下一个视频
- 滑动后 `android_wait_for_idle(timeout_ms=3000)` 等待加载

### 6. 写评论
1. 点击视频右侧的**评论按钮**（气泡图标）进入评论区
2. 在UI树中找到评论输入框（通常 resource_id 包含 `comment` 或 `input`）
3. 评论输入框通常是**原生 EditText**，使用**方案A**输入：
   - `android_find_elements(class_name="EditText")` 找到输入框
   - `android_input_text(text="评论内容")` 输入文本
4. 点击发送按钮（通常 resource_id 包含 `send` 或 `post`）
5. 验证：检查评论是否已成功发布

### 7. 返回上一页
```
mcp_call android_press_key key="back"
mcp_call android_wait_for_idle timeout_ms=3000
```

## 三、关键资源ID
| 元素 | 资源ID |
|------|--------|
| 搜索输入框 | `com.ss.android.ugc.aweme:id/et_search_kw` |
| 搜索按钮 | 需从UI树中定位搜索图标/文字 |

## 四、失败经验
1. **启动可能弹出选择对话框**：如果有多个抖音应用（抖音、抖音极速版），需要点击选择对应应用
2. **搜索结果的标签页**：搜索后默认可能在"综合"标签，需切换到"用户"标签查找账号
3. **主页视频列表**：用户主页的视频可能不是全部可见，需要滑动加载更多
4. **点赞状态验证**：如果视频已点赞，点赞按钮不可点击，需跳过
5. **评论发送**：部分版本可能需要通过键盘的"发送"键而不是界面按钮

## 五、注意事项
- 所有坐标需从UI树实时获取，禁止猜测坐标
- 操作后调用 `android_wait_for_idle` 等待UI稳定
- 使用 `android_get_ui_tree` 验证结果
- 评论内容使用 `android_input_text`（方案A）输入，因为抖音评论框是原生 EditText
