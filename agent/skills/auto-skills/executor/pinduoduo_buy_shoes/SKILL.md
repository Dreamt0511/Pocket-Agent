---
name: pinduoduo_buy_shoes
description: 在拼多多APP上搜索商品、筛选价格、查看详情、联系客服、查看评价并下单购买
---

# 拼多多购物（以买黑色鞋子为例）

## 任务目标
去拼多多买黑色鞋子，包含打开APP、搜索、筛选、进详情、联系客服、看评价、下单、通知用户

## 执行步骤
- [completed] 打开拼多多APP（包名：com.xunmeng.pinduoduo）
- [completed] 搜索框输入关键词并搜索
- [completed] 筛选价格区间（85-110元）
- [completed] 选择商品进入详情页
- [completed] 联系客服询问尺码
- [completed] 查看评论区确认无差评
- [completed] 选择款式/颜色/尺码后下单
- [completed] 语音通知用户查看手机

## 关键操作

### 包名
- 拼多多：`com.xunmeng.pinduoduo`

### MCP工具与方法

#### 启动App
```
android_launch_app(package_name="com.xunmeng.pinduoduo")
```

#### 搜索输入
拼多多搜索框是WebView类型，无EditText，使用方案B（剪贴板+paste）：
1. `android_tap(x=搜索框中心x, y=搜索框中心y)` — 点击搜索框聚焦
2. `android_set_clipboard(text="黑色鞋子")` — 存入剪贴板
3. `android_press_key(key="paste")` — 粘贴
4. 点击搜索按钮执行搜索

#### 筛选价格
- 点击"筛选"按钮 → 选择价格区间（如85-110）→ 点击"完成"

#### 联系客服
- 在商品详情页底部点击"客服"按钮 → 在聊天界面选择快捷问题（如"鞋码标准吗？"）

#### 查看评价
- 滚动到评价区域 → 点击"查看全部" → 浏览评价内容

#### 下单购买
- 选择颜色分类（如"黑色"）
- 选择尺码（如39）
- 点击"立即支付"/"0元下单"

### 注意事项
- 拼多多输入框为WebView类型，不要用android_input_text（无效），用剪贴板+paste方案
- 筛选面板中"价格区间"的预设选项点击后需要点"完成"确认
- 下单时需先选择颜色和尺码，否则按钮不可用
- 使用"先用后付"（0元下单）功能可先下单后付款
- 联系客服时优先使用快捷问题按钮

## 适用场景
- 在拼多多APP上搜索和购买商品
- 需要筛选价格、查看评价、联系客服的完整购物流程
