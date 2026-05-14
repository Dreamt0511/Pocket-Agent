---
name: neuralbridge-android-setup
description: 当用户需要配置 NeuralBridge MCP 服务器以实现 Android 设备自动化、解决连接失败问题（如 "Failed to connect" 或 "WAITING FOR CONNECTION"）、或配置 Claude/GPT/Gemini 通过 MCP 控制 Android 设备时，使用此技能。此技能解决 IP 不匹配、网络连通性问题，并提供从构建 App 到测试自动化工具的完整配置流程。
---

# NeuralBridge Android 自动化配置

每当用户需要设置 NeuralBridge MCP 服务器、连接 Android 设备进行 AI 自动化，或排查连接失败问题时，遵循以下步骤。

## 前置条件

- Android SDK（API 24+）
- Java JDK 17
- Android 设备或模拟器（7.0+）
- 已安装 Claude Code 或支持 MCP 的客户端

## 完整配置流程

### 第一步：构建并安装 App

```bash
git clone https://github.com/dondetir/NeuralBridge_mcp.git
cd NeuralBridge_mcp/android
./gradlew assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

### 第二步：启用无障碍服务

```bash
adb shell settings put secure enabled_accessibility_services \
  com.neuralbridge.companion/.service.NeuralBridgeAccessibilityService
adb shell settings put secure accessibility_enabled 1
```

**Android 15+ 额外步骤**：设置 → 应用 → NeuralBridge → 启用「允许受限设置」

### 第三步：获取正确的设备 IP（关键步骤）

**常见问题**：App 显示的 IP 可能是错误的（如缓存旧 IP），导致连接失败。

在 Android 设备上通过 Termux 执行以下命令获取真实 IP：

```bash
# 安装网络工具
pkg install net-tools

# 查看所有网络接口
ifconfig
```

从输出中识别正确的 IP：
- `wlan0` / `wlan2` 接口：WiFi 或热点连接的 IP
- `rmnet_data*` 接口：移动数据网络 IP
- 忽略 `lo`（本地回环）和 `10.2.0.2` 等可疑地址

**在电脑上验证 IP 连通性**：

```powershell
ping <设备显示的IP>
```

只有能 ping 通的 IP 才是正确的。

### 第四步：配置 MCP 连接

使用能 ping 通的 IP 配置 Claude：

```powershell
# 添加 MCP 服务器
claude mcp add --transport http neuralbridge http://<正确IP>:7474/mcp

# 验证连接状态
claude mcp list
```

预期输出应显示 `✓ Connected`。

## 故障排除

### 问题 1：App 显示 "WAITING FOR CONNECTION" 且连接失败

**原因**：App 显示的 IP 与实际网络接口 IP 不匹配。

**解决方案**：
1. 在 Termux 中执行 `ifconfig` 获取真实 IP
2. 在电脑上 `ping` 该 IP 确认连通性
3. 使用真实 IP 重新配置 MCP

### 问题 2：ping 不通手机 IP

**可能原因**：
- 电脑和手机不在同一局域网
- 手机热点未正确连接
- IP 地址已变化

**解决方案**：
1. 确认电脑连接的是手机热点
2. 重启手机热点或 NeuralBridge App
3. 使用 USB 网络共享（更稳定）

### 问题 3：权限不足无法执行 ifconfig

在 Termux 中执行：

```bash
pkg install net-tools
```

### 问题 4：连接成功后工具调用失败

验证 App 状态：
- 确认无障碍服务已启用
- Android 15+ 确认「允许受限设置」已开启
- 尝试重新授权 MediaProjection 权限

## 连接验证

配置成功后，在 Claude 中测试以下命令：

> "截取 Android 设备的屏幕截图"
> "获取当前屏幕的 UI 树结构"
> "在坐标 (500, 1000) 处点击"

## 重要提醒

- **IP 会变化**：设备重启或网络重连后 IP 可能改变，需要重新获取
- **忽略 App 显示的 IP**：App 显示的 IP 可能不准确，始终用 `ifconfig` 验证
- **USB 网络共享更稳定**：如果频繁断连，使用 USB 数据线 + USB 网络共享

## 参考资源

- 项目地址：https://github.com/dondetir/NeuralBridge_mcp
- MCP 文档：https://www.mcpworld.com/zh/detail/ecae1eba3c5ab6b22a2fbcb7230a8025
