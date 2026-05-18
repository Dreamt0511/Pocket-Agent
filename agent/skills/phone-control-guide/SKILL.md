---
name: phone-control-guide
description: 手机操纵指南——汇集所有可在Termux中直接执行的Android原生Shell命令和Termux API命令，零网络/零root/零ADB即可操控手机。Agent处理手机任务时优先查阅此技能，确认无法实现后再降级使用NeuralBridge。
---

# 手机操纵指南

## 🎯 适用场景（100%优先使用本技能）
✅ 所有不需要UI交互的系统操作：启动应用、查询系统信息、发送通知、读写剪贴板、调节音量/亮度、调用系统功能等
❌ 不需要UI交互的操作不要用NeuralBridge，避免浪费token

**优先级**：本技能是手机操控的**首选方案**（零 token 消耗）。只有当本技能列出的所有方案都无法完成任务时，才降级到 NeuralBridge。

**环境前提**：以下命令在 Android 16 (Termux) 中通过 SSH 实测验证。部分系统二进制命令受 SELinux 限制不可用，已标注。

> ⚠️ **重要注意**：Android 16 以上系统对 shell 命令权限收紧，大量传统的 `adb shell` 命令（如 `wm`、`dumpsys`、`settings`、`svc`、`input keyevent`）**不可用**。Termux API 命令是最可靠的操控途径。

---

## 第一部分：Android 原生 Shell 命令（实测可用）

### 一、应用启动

**核心原则**：先查后启，禁止盲目猜测包名。

#### 查找包名
✅ **重要提示**：应用包名是Android系统的全局唯一标识，所有手机上都是一样的，优先使用下方的常用应用包名对照表，不需要每次都搜索。

### 常用应用包名对照表（直接使用）
| 应用名称 | 包名 |
|---------|------|
| **社交类** | |
| 微信 | com.tencent.mm |
| QQ | com.tencent.mobileqq |
| 企业微信 | com.tencent.wework |
| 飞书 | com.ss.android.lark |
| 钉钉 | com.alibaba.android.rimet |
| 微博 | com.sina.weibo |
| 小红书 | com.xingin.xhs |
| 抖音 | com.ss.android.ugc.aweme |
| B站 | tv.danmaku.bili |
| **AI类** | |
| DeepSeek | com.deepseek.chat |
| ChatGPT | com.openai.chatgpt |
| Claude | com.anthropic.claude |
| Gemini | com.google.android.apps.bard |
| Copilot | com.microsoft.copilot |
| 豆包 | com.doubao.android |
| 通义千问 | com.alibaba.android.rimet |
| 文心一言 | com.baidu.searchbox |
| 月之暗面 | ai.x.grok |
| **工具类** | |
| Chrome | com.android.chrome |
| Edge | com.microsoft.emmx |
| 夸克浏览器 | com.quark.browser |
| 百度地图 | com.baidu.BaiduMap |
| 高德地图 | com.autonavi.minimap |
| 支付宝 | com.eg.android.AlipayGphone |
| 微信支付 | com.tencent.mm |
| **生活服务** | |
| 美团 | com.sankuai.meituan |
| 饿了么 | me.ele |
| 淘宝 | com.taobao.taobao |
| 京东 | com.jingdong.app.mall |
| 拼多多 | com.xunmeng.pinduoduo |
| 闲鱼 | com.taobao.idlefish |
| 菜鸟 | com.cainiao.wireless |
| 美团外卖 | com.sankuai.meituan.takeoutnew |
| 滴滴出行 | com.sdu.didi.psnger |
| 12306 | com.MobileTicket |
| **办公类** | |
| WPS | cn.wps.moffice_eng |
| 腾讯会议 | com.tencent.wemeet.app |
| 钉钉 | com.alibaba.android.rimet |
| 飞书 | com.ss.android.lark |
| QQ邮箱 | com.tencent.androidqqmail |
| 网易邮箱 | com.netease.mobimail |
| 有道词典 | com.youdao.dict |
| **系统类** | |
| 设置 | com.android.settings |
| 电话 | com.android.dialer |
| 短信 | com.android.mms |
| 通讯录 | com.android.contacts |
| 相机 | com.android.camera |
| 相册 | com.miui.gallery |
| 笔记 | com.miui.notes |
| 计算器 | com.miui.calculator |
| 时钟 | com.android.deskclock |
| 天气 | com.miui.weather2 |
| **其他** | |
| 网易云音乐 | com.netease.cloudmusic |
| QQ音乐 | com.tencent.qqmusic |
| 酷狗音乐 | com.kugou.android |
| 王者荣耀 | com.tencent.tmgp.sgame |
| 和平精英 | com.tencent.tmgp.pubgmhd |
| Termux | com.termux |
| MT管理器 | bin.mt.plus |

### 搜索包名（对照表找不到时使用）
```bash
# 搜索已安装应用（推荐）
pm list packages | grep <关键词>
# 示例：搜索微信
pm list packages | grep wechat
# 输出示例：package:com.tencent.mm

# 列出所有第三方应用
pm list packages -3

# 查看应用安装路径
pm path <包名>
```

#### 启动应用（确认包名后三选一）

```bash
# 方案一：通过包名启动（Android 10+，推荐）
am start -p <包名>
# 示例：am start -p com.tencent.mm

# 方案二：通过包名+Activity 精确启动
am start -n <包名>/<Activity名>

# 方案三：通过 Intent 打开链接
am start -a android.intent.action.VIEW -d <URL>
# 示例：am start -a android.intent.action.VIEW -d https://www.baidu.com
```

> `am` 和 `pm` 是 Termux 包装版（位于 `/data/data/com.termux/files/usr/bin/`），已适配 SELinux 策略。Termux 版 `am` **不支持** `force-stop`、`kill` 等管理命令。

#### 验证启动结果

由于 `dumpsys` 在 Android 16 上不可用，建议通过截图或 NeuralBridge 的 UI 树来确认应用是否启动成功。

**失败重试策略**：若 `am start -p` 失败 → 尝试 `am start -n <包名>/.<Activity>`（需先查 Activity）→ 若仍失败，降级到 NeuralBridge 使用 `android_launch_app`。

#### 查询应用 Activity（需预先了解）

```bash
# 通过包名查询 Activity 信息
pm dump <包名> | grep -A 5 "MainLauncher\|LAUNCHER"
```

---

### 二、系统导航

> **Android 16 限制**：`input keyevent/tap/swipe/text` 需要 `INJECT_EVENTS` 系统权限，**无法**在 Termux SSH 环境中使用。所有系统导航操作需要通过 NeuralBridge 完成。

```bash
# ❌ 以下命令均不可用：
# input keyevent KEYCODE_HOME         # 回桌面 - INJECT_EVENTS 权限拒绝
# input keyevent KEYCODE_BACK         # 返回 - 同上
# input tap 500 1000                  # 点击 - 同上
# input swipe 300 1000 300 300        # 滑动 - 同上
# input text "Hello"                  # 输入 - 同上
```

导航操作请使用 **NeuralBridge**（降级方案）。

---

### 三、设备与系统信息（推荐用 getprop）

`getprop` 是**最可靠**的系统信息源，无需任何权限即可读取。

```bash
# 设备信息
getprop ro.product.model                   # 设备型号
getprop ro.product.manufacturer            # 制造商
getprop ro.build.version.release           # Android 版本
getprop ro.build.version.sdk               # SDK 版本
getprop ro.serialno                        # 序列号
getprop ro.build.fingerprint               # 完整构建标识
getprop persist.sys.timezone               # 时区

# 屏幕信息（替代 wm size/density）
getprop persist.sys.miui_resolution        # 屏幕分辨率（小米MIUI）
# 输出示例：1220,2656,520（宽,高,密度）
getprop ro.sf.lcd_density                  # 屏幕密度
getprop vendor.display.default_resolution  # 默认分辨率（部分设备）

# 编译属性文件（包含完整设备信息）
cat /system/build.prop                     # 需确认可读

# 系统资源（标准 Linux 命令）
top -n 1                                   # 进程 CPU/内存占用
ps -A                                      # 所有运行进程
free -h                                    # 内存使用
df -h /data                                # 存储空间
uptime                                     # 运行时间
```

> 注意：`dumpsys`、`wm` 等 Android 调试命令在 Android 16 Termux SSH 中**不可用**（无权限访问系统服务）。

---

### 四、包管理

```bash
pm list packages                           # 所有已安装包
pm list packages -3                        # 仅第三方应用
pm list packages -s                        # 仅系统应用
pm list packages | grep <关键词>            # 搜索特定应用
pm path <包名>                             # 查看 APK 安装路径
pm clear <包名>                            # 清除应用数据（谨慎使用）
pm enable <包名>                           # 启用应用
pm disable <包名>                          # 禁用应用
pm dump <包名>                             # 应用详细信息
pm list features                           # 硬件特性（是否有NFC/摄像头等）

# ❌ 不可用（Android 16 权限阻止）：
# pm grant <包名> <权限>                    # 无法授予运行时权限
# pm revoke <包名> <权限>                   # 无法撤销运行时权限
```

---

### 五、系统设置控制

> **Android 16 限制**：`settings get/put`（`INTERACT_ACROSS_USERS` 拒绝）和 `svc`（/system/bin 不可访问）**均不可用**。系统设置控制请使用 Termux API 命令替代。

```bash
# ❌ 以下命令均不可用：
# settings get global airplane_mode_on     # INTERACT_ACROSS_USERS 拒绝
# settings put system screen_brightness 200 # 同上
# svc wifi enable/disable                  # /system/bin 不可访问
# svc bluetooth enable/disable             # 同上
# svc data enable/disable                  # 同上

# 替代方案（见第二部分 Termux API）：
# termux-brightness <0-255>                # 调节亮度（需WRITE_SETTINGS权限）
# termux-volume <stream> <level>           # 调节音量
# termux-wifi-enable true/false            # 开关WiFi
```

---

### 六、其他实用命令

```bash
# ❌ 以下命令在Android 16上均不可用：
# screencap /sdcard/screenshot.png         # 截屏失败
# screenrecord /sdcard/record.mp4          # 推测不可用
# content query --uri=content://...        # content命令不存在
# cmd notification post ...                # 权限拒绝
# cmd wifi set-wifi-enabled enabled        # /system/bin不可访问
# cmd status-bar click-tile ...            # 同上
# ime list -s                              # ime命令不存在
```

---

## 第二部分：Termux API 命令（实测推荐）

**前提**：需安装 `pkg install termux-api` 并在应用商店安装 Termux:API 应用。部分命令需要对应 Android 运行时权限（首次使用时会在手机上弹出授权请求）。

> Termux API 是 Android 16 上**最可靠的手机操控方式**，大部分系统类操作只有通过 Termux API 才能实现。

### 一、交互与通知

| 命令 | 功能 | 交互方式 |
|------|------|----------|
| `termux-notification -t "标题" -c "内容"` | 发送通知 | ✅ 静默执行 |
| `termux-notification-remove <ID>` | 移除通知 | ✅ 静默执行 |
| `termux-notification-list` | 列出所有通知 | ✅ 静默执行 |
| `termux-notification-channel <ID> <名称>` | 创建/删除通知频道 | ✅ 静默执行 |
| `termux-toast "提示文字"` | 短提示（Toast） | ✅ 静默执行 |
| `termux-dialog text` | 弹出对话框等待用户输入 | ⏳ 阻塞等待（弹窗直到用户操作） |
| `termux-tts-speak "文字"` | 语音合成朗读（支持中文） | ✅ 静默执行 |
| `termux-clipboard-get` | 获取剪贴板内容 | ✅ 静默执行 |
| `termux-clipboard-set "内容"` | 设置剪贴板内容 | ✅ 静默执行 |
| `termux-share 文件路径` | 分享文件（弹窗选应用） | ⚠️ 弹窗选择分享目标 |
| `termux-storage-get 输出路径` | 从文件选择器获取外部文件 | ⚠️ 弹窗选文件 |
| `termux-open-url <URL>` | 用默认浏览器打开链接 | ✅ 静默执行 |
| `termux-open <文件路径>` | 用默认应用打开文件 | ✅ 静默执行 |

### 二、传感器与外设

| 命令 | 功能 | 交互方式 |
|------|------|----------|
| `termux-camera-info` | 查询摄像头信息 | ✅ 静默执行 |
| `termux-camera-photo /sdcard/photo.jpg` | 拍照（一键拍摄，极速完成） | ✅ 静默执行 |
| `termux-sensor -s "传感器名称" -n 1` | 读取传感器数据 | ✅ 静默执行 |
| `termux-torch on/off` | 开关手电筒 | ✅ 静默执行 |
| `termux-vibrate -d 1000` | 震动（持续毫秒） | ✅ 静默执行 |
| `termux-fingerprint` | 指纹认证 | 🚫 禁止使用（SSH环境无法完成指纹交互） |
| `termux-infrared-transmit -f <频率> <模式>` | 红外发射 | ⚠️ 需硬件支持 |
| `termux-nfc` | NFC 操作 | ⚠️ 需硬件支持 |
| `termux-usb -l` | USB 设备列表 | ⚠️ 需弹窗确认 |

### 三、通讯与联系人

| 命令 | 功能 | 交互方式 |
|------|------|----------|
| `termux-sms-send -n 10086 "内容"` | 发送短信 | ❌ 系统阻止 SEND_SMS 权限（Android 16） |
| `termux-sms-list` | 列出短信会话 | ❌ 系统阻止 READ_SMS 权限（Android 16） |
| `termux-telephony-call 10086` | 拨打电话 | ⚠️ 需弹窗确认拨号 |
| `termux-telephony-deviceinfo` | 设备网络信息（网络制式/运营商） | ✅ 静默执行 |
| `termux-telephony-cellinfo` | 基站信息 | ✅ 静默执行 |
| `termux-call-log` | 通话记录 | ✅ 静默执行（已有权限时） |
| `termux-contact-list` | 联系人列表 | ✅ 静默执行（已有权限时） |

> 权限需在手机上通过系统设置或首次运行时的弹窗授予。

### 四、媒体与音频

| 命令 | 功能 | 交互方式 |
|------|------|----------|
| `termux-media-player play 文件.mp3` | 播放媒体 | ⏳ 需手动停止（持续播放） |
| `termux-media-scan 文件路径` | 扫描媒体文件 | ✅ 静默执行 |
| `termux-microphone-record -f 输出.m4a -l 秒数 -e aac` | 录音 | ⚠️ 需要 RECORD_AUDIO 权限 |
| `termux-audio-info` | 音频信息（采样率/缓冲区/蓝牙等） | ✅ 静默执行 |
| `termux-tts-engines` | 列出 TTS 引擎 | ✅ 静默执行 |
| `termux-speech-to-text` | 语音转文字 | ⏳ 等待用户说话结束 |

### 五、系统功能

| 命令 | 功能 | 交互方式 |
|------|------|----------|
| `termux-battery-status` | 电池状态（温度/电量/充电） | ✅ 静默执行 |
| `termux-brightness <0-255>` | 调节屏幕亮度 | ⚠️ 需在系统设置中手动授权 WRITE_SETTINGS |
| `termux-volume <stream> <level>` | 调节音量，stream可选值：music(媒体)/ring(铃声)/notification(通知)/alarm(闹钟)/call(通话)，level范围0-15 | ✅ 静默执行 |
| `termux-wifi-connectioninfo` | WiFi 连接信息（SSID/信号） | ✅ 静默执行 |
| `termux-wifi-scaninfo` | 扫描附近 WiFi（含BSSID/信号强度/频段） | ✅ 静默执行 |
| `termux-wifi-enable true/false` | 开关 WiFi | ⚠️ 弹窗需用户点击确认 |
| `termux-wallpaper -f 图片路径` | 设置壁纸 | ✅ 直接设置（无弹窗，谨慎使用） |
| `termux-location -p network` | 获取位置（网络定位，推荐） | ✅ 静默执行（需先授权位置权限） |
| `termux-location -p gps` | 获取位置（GPS定位） | ⏳ 室内可能长时间无结果 |
| `termux-download <URL>` | 下载文件（触发系统下载管理器） | ⚠️ 通知栏提示+WLAN限制 |
| `termux-job-scheduler -s 脚本路径 --job-id ID --period-ms 毫秒` | 定时任务 | ✅ 静默执行 |
| `termux-wake-lock` | 阻止设备休眠（保持唤醒） | ✅ 静默执行 |
| `termux-wake-unlock` | 释放唤醒锁 | ✅ 静默执行 |
| `termux-keystore list` | 密钥存储（列出/生成/签名） | ✅ 静默执行 |
| `termux-setup-storage` | 授予存储权限（首次使用） | ⚠️ 弹窗确认 |

> 交互方式说明：
> - ✅ **静默执行**：后台直接执行，无需用户干预
> - ⚠️ **需要确认**：会在手机上弹窗，需要用户手动点击确认
> - ⏳ **阻塞等待**：命令会一直阻塞，直到用户在手机上完成操作
> - ❌ **系统阻止**：Android 16 权限策略阻止，SSH 环境无法使用
> - 🚫 **禁止使用**：该操作不适合 SSH 自动化场景，禁止在代码中调用

---

## 第三部分：场景速查表

| 你想做什么 | 最优方案 | 交互 | 来源 |
|-----------|---------|:---:|------|
| **打开应用** | `pm list packages \| grep 关键词` → `am start -p 包名` | ✅ 静默 | Shell |
| **查设备型号** | `getprop ro.product.model` | ✅ 静默 | Shell |
| **查 Android 版本** | `getprop ro.build.version.release` | ✅ 静默 | Shell |
| **查屏幕分辨率** | `getprop persist.sys.miui_resolution` | ✅ 静默 | Shell |
| **查电池状态** | `termux-battery-status` | ✅ 静默 | Termux API |
| **查已安装应用** | `pm list packages -3` | ✅ 静默 | Shell |
| **查内存/存储** | `free -h` / `df -h /data` | ✅ 静默 | Shell |
| **发送通知** | `termux-notification -t "标题" -c "内容"` | ✅ 静默 | Termux API |
| **读/写剪贴板** | `termux-clipboard-get / set` | ✅ 静默 | Termux API |
| **打开链接** | `termux-open-url <URL>` | ✅ 静默 | Termux API |
| **打开文件** | `termux-open <文件路径>` | ✅ 静默 | Termux API |
| **短信/电话** | `termux-sms-send / telephony-call` | ❌系统阻止/⚠️需确认 | Termux API |
| **拍照** | `termux-camera-photo /sdcard/photo.jpg` | ✅ 静默 | Termux API |
| **开关手电筒** | `termux-torch on/off` | ✅ 静默 | Termux API |
| **震动** | `termux-vibrate -d 1000` | ✅ 静默 | Termux API |
| **TTS 朗读** | `termux-tts-speak "文字"` | ✅ 静默 | Termux API |
| **调节亮度** | `termux-brightness <0-255>` | ⚠️ 需手动授权 WRITE_SETTINGS | Termux API |
| **调节音量** | `termux-volume music 7` | ✅ 静默 | Termux API |
| **开关 WiFi** | `termux-wifi-enable true/false` | ⚠️ 需确认 | Termux API |
| **扫描附近WiFi** | `termux-wifi-scaninfo` | ✅ 静默 | Termux API |
| **获取位置** | `termux-location -p network` | ✅ 静默（先授权位置） | Termux API |
| **播放媒体** | `termux-media-player play 文件` | ⏳ 需手动停止 | Termux API |
| **保持唤醒** | `termux-wake-lock / wake-unlock` | ✅ 静默 | Termux API |
| **录音** | `termux-microphone-record -f 文件 -l 秒数` | ⚠️ 需授权 | Termux API |
| **语音转文字** | `termux-speech-to-text` | ⏳ 等用户说话 | Termux API |
| **下载文件** | `termux-download <URL>` | ⚠️ 通知栏提示 | Termux API |
| **设置壁纸** | `termux-wallpaper -f 图片路径` | ✅ 直接改（谨慎使用） | Termux API |
| **通话记录** | `termux-call-log` | ✅ 静默 | Termux API |
| **联系人** | `termux-contact-list` | ✅ 静默（先授权） | Termux API |
| **回桌面/返回** | 使用 NeuralBridge | 降级方案 |
| **点击/滑动/输入** | 使用 NeuralBridge | 降级方案 |
| **获取 UI 树** | 使用 NeuralBridge | 降级方案 |
| **分析截图** | 使用 NeuralBridge | 降级方案 |
| **截图** | 使用 NeuralBridge（`android_screenshot`） | 降级方案 |

---

## 实操工作流范例

### 例 1：打开微信并发送消息

```
1. 查包名:     pm list packages | grep wechat
   → package:com.tencent.mm

2. 启动应用:   am start -p com.tencent.mm

3. 确认启动:   用 NeuralBridge 截图或 UI 树验证

4. 找联系人:   使用 NeuralBridge 获取 UI 树，找到搜索框
               → android_tap(x, y) → android_input_text("联系人名")

5. 输入消息:   使用 NeuralBridge 找到输入框，输入内容

6. 发送:      找到发送按钮并点击
```

### 例 2：查询手机信息

```
从下往上按优先级尝试：

getprop ro.product.model          # ✅ 直接可用
getprop ro.build.version.release  # ✅ 直接可用
termux-battery-status             # ✅ Termux API
termux-telephony-deviceinfo       # ✅ Termux API
free -h && df -h /data            # ✅ 标准 Linux
```

---

## 重要限制（Android 16 实测）

| 命令类别 | 可用性 | 说明 |
|---------|--------|------|
| `getprop` | ✅ 全部可用 | 最可靠的系统信息源 |
| `am start` | ✅ 可用 | Termux 包装版，支持 start/broadcast |
| `am force-stop/kill` | ❌ 不可用 | Termux 包装版不支持 |
| `pm list/path/clear/enable/disable` | ✅ 可用 | 包管理全功能 |
| `pm grant/revoke` | ❌ 不可用 | Android 16 阻止运行时权限授予 |
| `input keyevent/tap/swipe/text` | ❌ 不可用 | 需要 `INJECT_EVENTS` 系统权限 |
| `wm/dumpsys/settings/svc` | ❌ 不可用 | `/system/bin` 不可访问 |
| `screencap/screenrecord` | ❌ 不可用 | 多显示器+权限双重限制 |
| `content/ime/cmd` | ❌ 不可用 | 系统二进制不可访问 |
| `termux-*` (Termux API) | ✅ 大部分可用 | Android 16 上最可靠的操控途径 |

---

## 使用原则

1. **查询优先**：接到手机操作任务，先查本技能是否有对应方案
2. **Shell > Termux API > NeuralBridge**：优先零依赖的 Shell 命令，其次 Termux API，最后降级到 NeuralBridge
3. **启动应用四步**：查包名 → 确认 → 启动 → 验证，禁止猜测包名
4. **失败处理**：一种方案失败，换另一种方案重试，最多 2 次后降级
5. **权限提示**：Termux API 命令需要对应 Android 运行时权限，部分需在系统设置中手动开启
6. **破坏性操作先询问**：涉及修改系统设置（壁纸/亮度/网络）、发送短信/拨打电话、删除文件等有副作用的操作，必须先询问用户确认
