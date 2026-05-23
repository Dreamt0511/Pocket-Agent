---
name: phone-control-quickref
description: 手机操控速查——Termux API和Shell单步操作命令速查，适合主Agent无需子Agent即可执行的简单操作（查信息、通知、剪贴板、音量、启动应用等）。⚠️ 如果任务需要子Agent（涉及UI交互），不要自己做准备工作，全盘委托给子Agent
---

# 手机操控速查（主Agent用）

## 使用原则

- 本技能只包含**单步命令**，遇到此类需求直接用 `shell_exec` 执行，不需要派发给 executor
- ⚠️ 如果任务整体需要子Agent执行（涉及UI交互），不要先查包名或启动应用，全盘委托给子Agent处理
- 如果需要多步操控（点击、输入、滑动、UI分析等），派发给 executor 子Agent
- 命令执行失败直接告知用户，不需要重试方案

## 应用启动

```bash
# 搜索包名
pm list packages | grep <关键词>

# 启动应用
am start -p <包名>
```

### 常用包名
| 应用 | 包名 |
|------|------|
| 微信 | com.tencent.mm |
| 抖音 | com.ss.android.ugc.aweme |
| 支付宝 | com.eg.android.AlipayGphone |
| 淘宝 | com.taobao.taobao |
| 拼多多 | com.xunmeng.pinduoduo |
| B站 | tv.danmaku.bili |
| Chrome | com.android.chrome |
| 设置 | com.android.settings |

## Termux API（单步命令）

### 交互与通知
```bash
termux-tts-speak "文字"              # 语音朗读
termux-notification -t "标题" -c "内容"  # 发送通知
termux-clipboard-get                  # 读剪贴板
termux-clipboard-set "内容"           # 写剪贴板
termux-toast "提示文字"               # 短提示
termux-open-url <URL>                 # 打开链接
termux-open <文件路径>                # 打开文件
```

### 系统功能
```bash
termux-battery-status                 # 电池状态
termux-brightness <0-255>             # 调节亮度
termux-volume music 7                 # 调节音量(0-15)
termux-wifi-connectioninfo            # WiFi信息
termux-wifi-scaninfo                  # 扫描WiFi
termux-wifi-enable true/false         # 开关WiFi(需确认)
termux-torch on/off                   # 手电筒
termux-vibrate -d 1000                # 震动
termux-location -p network            # 位置
termux-wallpaper -f 图片路径          # 设置壁纸
termux-wake-lock / termux-wake-unlock # 唤醒锁
termux-download <URL>                 # 下载文件
```

### 媒体与传感器
```bash
termux-camera-photo /sdcard/photo.jpg # 拍照
termux-media-player play 文件         # 播放
termux-microphone-record -f 文件 -l 秒数 # 录音
termux-sensor -s "传感器名" -n 1      # 传感器
```

## 系统信息
```bash
getprop ro.product.model              # 设备型号
getprop ro.build.version.release      # Android版本
getprop persist.sys.timezone          # 时区
free -h                               # 内存
df -h /data                           # 存储
top -n 1                              # 进程
```
