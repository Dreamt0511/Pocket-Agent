---
name: phone-control-guide
description: 手机操纵指南——Termux Shell命令 + Termux API，零ADB即可操控手机。Agent处理手机任务时优先查阅此技能，确认无法实现后再降级使用NeuralBridge。
---

# 手机操纵指南

**优先级**：本技能是手机操控首选方案（零 token 消耗）。只有本技能列出的方案都不行时，才降级到 NeuralBridge。

> ⚠️ **Android 16** 对 shell 命令权限收紧，`wm`、`dumpsys`、`settings`、`svc`、`input keyevent` **不可用**。Termux API 是最可靠的操控途径。

---

## 一、应用启动

**先查后启，禁止盲目猜测包名。**

### 常用应用包名对照表（直接使用，无需搜索）

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

### 搜索包名（对照表找不到时）
```bash
pm list packages | grep <关键词>    # 搜索已安装应用
pm list packages -3                 # 所有第三方应用
pm path <包名>                      # 查看APK路径
```

### 启动应用
```bash
am start -p <包名>                  # 推荐，Android 10+
am start -n <包名>/<Activity名>      # 精确启动
am start -a android.intent.action.VIEW -d <URL>  # 打开链接
```

> `am`/`pm` 是 Termux 包装版（位于 `/data/data/com.termux/files/usr/bin/`），已适配 SELinux。不支持 `force-stop`/`kill`。
> 失败重试：`am start -p` 失败 → `am start -n <包名>/.<Activity>`（先 `pm dump <包名> | grep -A 5 LAUNCHER` 查 Activity）→ 仍失败 → NeuralBridge `android_launch_app`。
> 启动后用 NeuralBridge UI 树验证（降级用截图）。

---

## 二、Shell命令速查

### 设备与系统信息
`getprop` 最可靠，无需权限。
```bash
getprop ro.product.model                   # 设备型号
getprop ro.product.manufacturer            # 制造商
getprop ro.build.version.release           # Android 版本
getprop ro.build.version.sdk               # SDK 版本
getprop ro.serialno                        # 序列号
getprop ro.build.fingerprint               # 完整构建标识
getprop persist.sys.timezone               # 时区
getprop persist.sys.miui_resolution        # 屏幕分辨率（小米MIUI）
getprop ro.sf.lcd_density                  # 屏幕密度

# 系统资源（标准Linux命令）
top -n 1                                   # 进程CPU/内存
ps -A                                      # 所有进程
free -h                                    # 内存
df -h /data                                # 存储
uptime                                     # 运行时间
```
> `dumpsys`、`wm` 等调试命令在 Android 16 Termux SSH 中**不可用**。

### 包管理
```bash
pm list packages                           # 所有已安装
pm list packages -3                        # 仅第三方
pm list packages -s                        # 仅系统
pm list packages | grep <关键词>            # 搜索
pm path <包名>                             # APK路径
pm clear <包名>                            # 清除数据（谨慎）
pm enable/disable <包名>                   # 启用/禁用
pm dump <包名>                             # 应用详情
pm list features                           # 硬件特性
```
> ❌ `pm grant/revoke` 在 Android 16 上不可用。

### 系统设置
> `settings get/put`（`INTERACT_ACROSS_USERS` 拒绝）和 `svc`（/system/bin 不可访问）**均不可用**。改用 Termux API 替代。
> 其他不可用命令：`screencap`、`screenrecord`、`content`、`cmd`、`ime` 在 Android 16 上**均不可用**。

---

## 三、Termux API 命令（Android 16 推荐方案）

**前提**：`pkg install termux-api` + 安装 Termux:API 应用。部分命令需首次使用时授权。

### 交互与通知
| 命令 | 功能 | 类型 |
|------|------|:----:|
| `termux-notification -t "标题" -c "内容"` | 发送通知 | ✅ |
| `termux-notification-remove <ID>` | 移除通知 | ✅ |
| `termux-notification-list` | 列出通知 | ✅ |
| `termux-notification-channel <ID> <名称>` | 通知频道管理 | ✅ |
| `termux-toast "文字"` | 短提示 | ✅ |
| `termux-dialog text` | 弹窗等待输入 | ⏳ |
| `termux-tts-speak "文字"` | 语音朗读 | ✅ |
| `termux-clipboard-get` | 读取剪贴板 | ✅ |
| `termux-clipboard-set "内容"` | 设置剪贴板 | ✅ |
| `termux-share <文件>` | 分享文件 | ⚠️ |
| `termux-storage-get <输出路径>` | 从文件选择器获取文件 | ⚠️ |
| `termux-open-url <URL>` | 浏览器打开链接 | ✅ |
| `termux-open <文件>` | 默认应用打开文件 | ✅ |

### 传感器与外设
| 命令 | 功能 | 类型 |
|------|------|:----:|
| `termux-camera-info` | 摄像头信息 | ✅ |
| `termux-camera-photo /sdcard/photo.jpg` | 拍照 | ✅ |
| `termux-sensor -s "名称" -n 1` | 传感器数据 | ✅ |
| `termux-torch on/off` | 手电筒 | ✅ |
| `termux-vibrate -d 1000` | 震动 | ✅ |
| `termux-fingerprint` | 指纹认证 | 🚫 |
| `termux-infrared-transmit -f <频率> <模式>` | 红外发射 | ⚠️ 需硬件 |
| `termux-nfc` | NFC操作 | ⚠️ 需硬件 |
| `termux-usb -l` | USB设备列表 | ⚠️ 弹窗确认 |

### 通讯
| 命令 | 功能 | 类型 |
|------|------|:----:|
| `termux-telephony-deviceinfo` | 设备网络信息 | ✅ |
| `termux-telephony-cellinfo` | 基站信息 | ✅ |
| `termux-call-log` | 通话记录 | ✅ |
| `termux-contact-list` | 联系人 | ✅ |
| `termux-telephony-call 10086` | 拨打电话 | ⚠️ |
| `termux-sms-send -n 10086 "内容"` | 发短信 | ❌ |
| `termux-sms-list` | 短信列表 | ❌ |

### 媒体与音频
| 命令 | 功能 | 类型 |
|------|------|:----:|
| `termux-media-player play 文件.mp3` | 播放媒体 | ⏳ |
| `termux-media-scan <路径>` | 扫描媒体文件 | ✅ |
| `termux-microphone-record -f 文件 -l 秒 -e aac` | 录音 | ⚠️ |
| `termux-audio-info` | 音频信息 | ✅ |
| `termux-tts-engines` | TTS引擎列表 | ✅ |
| `termux-speech-to-text` | 语音转文字 | ⏳ |

### 系统功能
| 命令 | 功能 | 类型 |
|------|------|:----:|
| `termux-battery-status` | 电池状态 | ✅ |
| `termux-brightness <0-255>` | 调节亮度 | ⚠️ |
| `termux-volume music 7` | 调节音量（music/ring/notification/alarm/call，0-15） | ✅ |
| `termux-wifi-connectioninfo` | WiFi连接信息 | ✅ |
| `termux-wifi-scaninfo` | 扫描WiFi | ✅ |
| `termux-wifi-enable true/false` | 开关WiFi | ⚠️ |
| `termux-wallpaper -f <图片>` | 设置壁纸 | ✅ |
| `termux-location -p network` | 网络定位 | ✅ |
| `termux-location -p gps` | GPS定位 | ⏳ |
| `termux-download <URL>` | 下载文件 | ⚠️ |
| `termux-wake-lock` | 阻止设备休眠 | ✅ |
| `termux-wake-unlock` | 释放唤醒锁 | ✅ |
| `termux-job-scheduler -s <脚本> --job-id ID --period-ms <毫秒>` | 定时任务 | ✅ |
| `termux-keystore list` | 密钥存储 | ✅ |
| `termux-setup-storage` | 授权存储权限 | ⚠️ |

> **类型说明**：✅ 静默执行 ｜ ⚠️ 需弹窗确认 ｜ ⏳ 阻塞等待 ｜ ❌ 系统阻止 ｜ 🚫 禁止使用

> **权限提示**：Termux API 首次使用时会弹窗授权。部分命令（如 `termux-brightness`）需在系统设置中手动开启对应权限。

---

## 四、降级场景（→ NeuralBridge）

以下操作 Shell / Termux API **无法完成**，直接使用 NeuralBridge：
- **截图/分析截图**：`android_screenshot`
- **获取UI树**：`android_get_ui_tree`（优先于截图，零图片token）
- **点击/滑动/长按/输入**：通过UI树获取坐标后操作
- **系统导航**：返回、桌面、最近任务等
- **启动失败兜底**：`android_launch_app`
- **等待元素/滚动找元素**：`android_wait_for_element`、`android_scroll_to_element`

> 详细操作规范见 `neuralbridge-operation-standard` skill。

---

## 五、执行规则

1. **Shell > Termux API > NeuralBridge**：优先零依赖 Shell，其次 Termux API，最后 NeuralBridge
2. **启动应用**：先查包名（对照表→pm search）→ 启动 → 验证，禁止猜包名
3. **失败处理**：一种失败换另一种，最多2次后降级 NeuralBridge
4. **破坏性操作先询问**：修改壁纸/亮度/网络、发短信、删文件等有副作用的操作必须先询问用户
