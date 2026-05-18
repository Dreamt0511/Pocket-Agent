<<<<<<< Updated upstream
# Termux SSH 远程连接技能

## 技能概述

本技能用于在电脑上通过 SSH 远程连接手机 Termux 终端，实现电脑端操作手机命令行环境，支持 USB 网络共享和 WiFi 热点两种连接方式。

## 适用场景

- 在电脑上开发、调试 Termux 中的脚本或程序
- 手机屏幕太小，键盘输入不便，希望在电脑上操作
- 需要在手机上运行模型、编译代码，但希望使用电脑的编辑器和终端
- 批量管理多台手机的 Termux 环境

---

## 前置条件

| 条件 | 说明 |
|------|------|
| 手机 | 已安装 Termux，与电脑在同一网络（USB 或 WiFi） |
| 电脑 | Windows / macOS / Linux，安装 OpenSSH 客户端 |
| 连接 | USB 数据线 或 手机开启 WiFi 热点 |

---

## 核心步骤

### 第一步：手机 Termux 端配置

```bash
# 1. 安装 OpenSSH
pkg update && pkg install openssh -y

# 2. 设置登录密码（必须）
passwd
# 输入密码（屏幕不显示），回车确认

# 3. 启动 SSH 服务
sshd

# 4. 确认服务运行
ps aux | grep sshd
# 应看到类似：u0_a391  xxxx  ...  sshd

# 5. 查看手机 IP 地址
ifconfig
# 记录 wlan（热点）或 rndis（USB）接口的 inet 地址

# 6.查看用户名
whoami
```

### 第二步：电脑端连接

**Windows PowerShell / macOS / Linux 终端：**

```bash
ssh 用户名@手机IP -p 8022
```

**实际命令示例：**
```bash
# USB 连接（rndis0 接口）
ssh u0_a391@10.234.109.196 -p 8022

# WiFi 热点连接（wlan2 接口）
ssh u0_a391@10.143.89.72 -p 8022
```

**首次连接会提示：**
```
The authenticity of host '[...]:8022' can't be established.
Are you sure you want to continue connecting (yes/no/[fingerprint])?
```
输入 `yes` 回车，然后输入 `passwd` 设置的密码。

### 第三步：连接成功

成功后电脑终端显示 Termux 命令行提示符 `~ $`，可正常执行 Termux 命令。

---

## 两种连接方式对比

| 特性 | USB 网络共享 | WiFi 热点 |
|------|-------------|-----------|
| **手机接口** | `rndis0` / `usb0` | `wlan2` / `wlan0` |
| **稳定性** | ⭐⭐⭐⭐⭐ 非常稳定 | ⭐⭐⭐ 受信号影响 |
| **速度** | 快 | 中等 |
| **充电** | 同时充电 | 不充电 |
| **适用场景** | 长时间开发、调试 | 快速操作、无数据线时 |
| **IP 示例** | `10.234.109.196` | `10.143.89.72` |

---

## 常见问题与解决

### Q1: `Permission denied` 连接失败

**原因**：服务未启动或网络不通  
**解决**：
```bash
# 手机 Termux 中确认 sshd 在运行
ps aux | grep sshd

# 如未运行，启动它
sshd
```

### Q2: 连接卡住无响应

**原因**：主机密钥确认未完成  
**解决**：运行 `ssh -o PubkeyAuthentication=no 用户名@IP -p 8022` 或添加 `-vvv` 调试

### Q3: 手机重启后需要重新操作

**解决**：每次重启后重新运行 `sshd`。可设置开机自启或习惯性检查。

### Q4: 手机 IP 每次都变

**解决**：连接前在 Termux 运行 `ifconfig` 查看当前 IP。部分手机热点支持静态 IP 设置。

### Q5: 免密登录（可选）

```bash
# 电脑生成密钥（如已有跳过）
ssh-keygen -t rsa -b 4096

# 复制公钥到手机
ssh-copy-id 用户名@手机IP -p 8022
```

之后连接不再需要输入密码。

### Q6: Termux 后台被杀死（MIUI 等系统）

**解决**：
- 设置 → 应用 → Termux → 省电策略 → 设为"无限制"
- 多任务界面长按 Termux → 锁定应用
- Termux 中运行 `termux-wake-lock`

---

## 网络诊断命令

| 测试项 | 电脑命令 | 手机命令 |
|--------|---------|---------|
| 网络连通性 | `ping 手机IP` | - |
| 端口开放 | `Test-NetConnection 手机IP -Port 8022` | `netstat -an \| grep 8022` |
| 服务运行 | - | `ps aux \| grep sshd` |
| 查看 IP | `ipconfig` / `ifconfig` | `ifconfig` |

---

## 高级技巧

### 反向 SSH（手机主动连电脑）

适用于手机热点有客户端隔离、无法直接连接的情况：

```bash
# 电脑端（需开启 SSH 服务）
# Windows: 管理员 PowerShell 运行 Start-Service sshd

# 手机 Termux
ssh -R 8022:localhost:8022 电脑用户名@电脑IP
```

### 端口转发测试

手机 Termux 中启动 HTTP 服务测试网络连通性：
```bash
python -m http.server 8080
```
电脑浏览器访问 `http://手机IP:8080`，能打开说明网络正常。

### SCP 文件传输

```bash
# 电脑 → 手机
scp -P 8022 本地文件路径 用户名@手机IP:/目标路径/

# 手机 → 电脑
scp -P 8022 用户名@手机IP:/文件路径 ./本地目录/
```

---

## 快速参考卡片

```bash
# === 手机 Termux ===
sshd                          # 启动 SSH 服务
passwd                        # 设置/修改密码
ifconfig                      # 查看 IP 地址
ps aux | grep sshd            # 检查服务状态

# === 电脑连接 ===
ssh 用户名@手机IP -p 8022     # 标准连接
ssh -v 用户名@手机IP -p 8022  # 调试模式

# === 常用场景 ===
# USB 连接示例
ssh u0_a391@10.234.109.196 -p 8022

# 热点连接示例
ssh u0_a391@10.143.89.72 -p 8022
```

---

*版本：1.0 | 适用平台：Termux (Android) + Windows/macOS/Linux*

ssh u0_a391@10.40.148.132 -p 8022