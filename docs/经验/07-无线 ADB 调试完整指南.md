## 无线 ADB 调试完整指南

### 一、当前状态
- **连接方式**：电脑连接手机热点
- **手机 IP**：`10.143.89.72`
- **连接端口**：`5555`
- **状态**：✅ 已连接成功

---

### 二、日常使用命令

每次电脑连上手机热点后，执行：

```bash
adb connect 10.143.89.72:5555
adb shell
```

退出手机命令行：
```bash
exit
```

查看已连接设备：
```bash
adb devices
```

---

### 三、手机重启后的处理

如果手机重启了，无线调试会失效，需要重新用 USB 线配置一次：

1. **USB 线连接手机和电脑**
2. 执行：
   ```bash
   adb tcpip 5555
   ```
3. **拔掉 USB 线**
4. 执行：
   ```bash
   adb connect 10.143.89.72:5555
   ```

---

### 四、重要提醒

| 情况 | 是否需要重新操作 |
|------|----------------|
| 电脑断开热点重连 | 只需重新 `adb connect` |
| 手机重启 | 需要插 USB 线重配 `adb tcpip 5555` |
| 修改过开发者选项 | 可能需要重配 |
| 更换 WiFi 网络 | IP 会变，需要用新 IP 重新 `adb connect` |

---

### 五、常用 ADB 命令

```bash
# 安装 APK
adb install app.apk

# 卸载应用
adb uninstall 包名

# 查看日志
adb logcat

# 截图
adb exec-out screencap -p > screenshot.png

# 录屏
adb shell screenrecord /sdcard/demo.mp4

# 传输文件
adb push 本地文件 /sdcard/
adb pull /sdcard/文件 本地路径

# 查看当前 Activity
adb shell dumpsys window | grep mCurrentFocus
```

---

### 六、如果以后想用路由器 WiFi

换一个**没有 AP 隔离**的路由器（通常是家里的个人路由器），步骤相同：

1. 手机和电脑连同一个 WiFi
2. 查手机 IP
3. `adb connect 手机IP:5555`

如果连不上，说明该网络开启了 AP 隔离，换热点或换个路由器即可。




有了 ADB 连接，你可以在电脑上**直接控制手机**，做很多平时需要动手或需要 Root 才能做的事。以下是主要用途：

---

## 一、应用管理

```bash
# 安装 APK（即使是未发布的应用）
adb install app.apk

# 卸载应用
adb uninstall com.example.app

# 列出所有已安装应用
adb shell pm list packages

# 清除应用数据（相当于重装）
adb shell pm clear com.example.app
```

---

## 二、文件传输

```bash
# 电脑 → 手机
adb push 电脑文件 /sdcard/

# 手机 → 电脑
adb pull /sdcard/文件 电脑路径

# 示例：导出微信聊天数据库
adb pull /data/data/com.tencent.mm/MicroMsg/ ~/Desktop/
```

---

## 三、屏幕操作（自动化/脚本）

```bash
# 截图
adb exec-out screencap -p > screenshot.png

# 录屏
adb shell screenrecord /sdcard/video.mp4

# 模拟点击（坐标）
adb shell input tap 500 1000

# 模拟滑动
adb shell input swipe 300 1000 300 500

# 模拟输入文字
adb shell input text "hello"

# 模拟按键（返回、Home等）
adb shell input keyevent KEYCODE_BACK      # 返回
adb shell input keyevent KEYCODE_HOME      # Home
adb shell input keyevent KEYCODE_POWER     # 电源键
```

---

## 四、调试与分析

```bash
# 查看实时日志
adb logcat

# 过滤特定应用日志
adb logcat -s TAG_NAME

# 查看当前打开的 Activity（知道当前在哪个页面）
adb shell dumpsys window | grep mCurrentFocus

# 查看电池状态
adb shell dumpsys battery

# 查看内存使用
adb shell dumpsys meminfo

# 查看 CPU 使用
adb shell top
```

---

## 五、高级操作（无需 Root）

```bash
# 启用/关闭无线调试
adb shell svc wifi enable
adb shell svc data enable   # 开启移动数据

# 模拟来电
adb shell am broadcast -a android.intent.action.PHONE_STATE --es state "RINGING" --es number "10086"

# 打开任意 URL
adb shell am start -a android.intent.action.VIEW -d https://www.baidu.com

# 强制停止应用
adb shell am force-stop com.example.app

# 备份应用数据
adb backup -apk -shared -all -f backup.ab
```

---

## 六、开发调试必备

如果你在开发 Android 应用：

```bash
# 无线安装调试包（不用每次插线）
# Android Studio 配置无线调试后，点击 Run 直接走 WiFi

# 查看布局层级（类似 UI Automator）
adb shell uiautomator dump

# 性能分析
adb shell dumpsys gfxinfo   # 帧率
adb shell dumpsys cpuinfo   # CPU
```

---

## 七、实用脚本示例

**自动签到脚本：**
```bash
adb shell am start -n com.example.app/.MainActivity
sleep 2
adb shell input tap 500 1000   # 点击签到按钮
```

**批量截图：**
```bash
for i in {1..10}; do
    adb exec-out screencap -p > "screenshot_$i.png"
    sleep 1
done
```

**导出所有已安装应用列表：**
```bash
adb shell pm list packages | cut -d ":" -f2 > apps.txt
```

---

## 八、实际场景举例

| 场景 | 用 ADB 怎么做 |
|------|-------------|
| 手机屏幕碎了，想看内容 | `adb shell screencap` 截图到电脑看 |
| 测试 App 在不同网络下的表现 | `adb shell svc wifi disable` 关 WiFi |
| 批量安装 100 个 APK | 写个脚本循环 `adb install` |
| 监控 App 崩溃日志 | `adb logcat -e "FATAL"` |
| 不需要 Root 卸不掉的内置应用 | `adb shell pm uninstall -k --user 0 包名` |

---

## 总结

ADB 本质上是电脑控制手机的**后门**，你能做的事包括：
- 自动化操作（点击、滑动、输入）
- 调试分析（日志、性能、崩溃）
- 文件管理（拉取、推送）
- 应用管理（安装、卸载、清除数据）
- 系统控制（开关 WiFi、模拟按键）
