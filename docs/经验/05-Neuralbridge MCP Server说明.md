Neuralbridge MCP Server 是专门用于 **Android 设备自动化控制** 的工具集，提供了全面的UI交互、应用管理、设备状态查询、测试辅助等能力，主要用于Android自动化测试、RPA、UI自动化、移动端爬虫等场景。

所有工具按功能分类如下：

### 📱 设备与系统基础工具
| 工具名                    | 功能描述                                                       | 核心参数                                                                                                                                       |
| ------------------------- | -------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| `android_get_device_info` | 获取设备基础信息：厂商、型号、Android版本、SDK等级、屏幕尺寸等 | 无                                                                                                                                             |
| `android_list_devices`    | 列出所有已连接的设备                                           | 无                                                                                                                                             |
| `android_select_device`   | 选择要操作的设备（嵌入式服务端默认使用当前设备）               | `device_id` 设备ID                                                                                                                             |
| `android_global_action`   | 执行系统全局操作                                               | `action` 可选：`back`/`home`/`recents`/`notifications`/`quick_settings`                                                                        |
| `android_press_key`       | 按键操作                                                       | 全局键：`back`/`home`/`recents`/`notifications`/`power`<br>输入框键：`enter`/`delete`/`tab`/`escape`/`space`/`select_all`/`cut`/`copy`/`paste` |

### 📱 应用管理工具
| 工具名               | 功能描述        | 核心参数                                                        |
| -------------------- | --------------- | --------------------------------------------------------------- |
| `android_list_apps`  | 列出已安装应用  | `filter` 可选：`all`/`third_party`/`system`                     |
| `android_launch_app` | 启动应用        | `package_name` 包名，可选`activity`、`clear_task`（清空任务栈） |
| `android_close_app`  | 将应用退到后台  | `package_name` 包名                                             |
| `android_open_url`   | 打开URL或深链接 | `url` 链接地址，可选`browser_package`指定浏览器                 |

### 🖱️ UI交互操作工具
| 工具名                  | 功能描述                                | 核心参数                                                                      |
| ----------------------- | --------------------------------------- | ----------------------------------------------------------------------------- |
| `android_tap`           | 点击操作                                | 支持坐标`x`/`y`点击，或通过`text`/`resource_id`/`content_desc`查找元素点击    |
| `android_double_tap`    | 双击操作                                | 同上                                                                          |
| `android_long_press`    | 长按操作（默认1000ms）                  | 同上，可选`duration_ms`自定义时长                                             |
| `android_swipe`         | 滑动操作（默认300ms，<200ms为快速滑动） | `start_x`/`start_y`/`end_x`/`end_y` 滑动起止坐标                              |
| `android_drag`          | 拖拽操作（默认500ms）                   | `from_x`/`from_y`/`to_x`/`to_y` 拖拽起止坐标                                  |
| `android_pinch`         | 捏合缩放                                | `center_x`/`center_y` 中心点，`scale` 缩放比例（>1放大，<1缩小）              |
| `android_input_text`    | 输入文本                                | `text` 输入内容，可选`element_text`/`resource_id`定位输入框，`append`追加文本 |
| `android_set_clipboard` | 设置剪贴板内容                          | `text` 要设置的文本                                                           |

### 🔍 UI元素与页面分析工具
| 工具名                       | 功能描述                       | 核心参数                                                                                                   |
| ---------------------------- | ------------------------------ | ---------------------------------------------------------------------------------------------------------- |
| `android_find_elements`      | 查找UI元素                     | 支持按`text`/`resource_id`/`content_desc`/`class_name`查找，可过滤`clickable`/`scrollable`/`focusable`属性 |
| `android_get_ui_tree`        | 获取当前屏幕完整UI树           | 可过滤显示`all`/`interactive`/`text`类型元素，返回元素ID、文本、边界、语义类型                             |
| `android_get_screen_context` | 一站式获取页面上下文           | 返回前台应用信息、简化UI树、缩略图截图，适合AI分析场景                                                     |
| `android_scroll_to_element`  | 滚动查找屏幕外元素             | 自动滚动直到找到元素或到达内容末尾，支持上下左右方向                                                       |
| `android_wait_for_element`   | 等待元素出现（默认超时5000ms） | 用于等待加载完成、页面跳转等场景                                                                           |
| `android_wait_for_gone`      | 等待元素消失                   | 用于等待加载框、闪屏、进度条消失                                                                           |
| `android_wait_for_idle`      | 等待UI稳定（300ms无变化）      | 确保页面完全加载后再操作                                                                                   |

### 📸 截图与视觉测试工具
| 工具名                    | 功能描述     | 核心参数                                                     |
| ------------------------- | ------------ | ------------------------------------------------------------ |
| `android_screenshot`      | 捕获屏幕截图 | `quality` 可选`full`/`thumbnail`，`max_width`指定最大宽度    |
| `android_screenshot_diff` | 视觉对比测试 | `reference_base64` 参考截图base64，返回相似度评分（0.0-1.0） |

### 📢 通知与事件工具
| 工具名                      | 功能描述            | 核心参数                                  |
| --------------------------- | ------------------- | ----------------------------------------- |
| `android_get_notifications` | 获取系统通知        | 返回通知标题、内容、包名、时间戳等信息    |
| `android_get_recent_toasts` | 获取最近的Toast消息 | 默认查询最近5000ms内的Toast               |
| `android_enable_events`     | 启用事件流监听      | 可监听UI变化、通知、Toast、应用崩溃等事件 |

### ♿ 无障碍工具
| 工具名                        | 功能描述       | 核心参数                                                                |
| ----------------------------- | -------------- | ----------------------------------------------------------------------- |
| `android_accessibility_audit` | 页面无障碍审计 | 自动检测：缺失内容描述、触摸目标过小（<48dp）、可交互元素不可聚焦等问题 |

### 🛠️ 工具管理
| 工具名                   | 功能描述               | 核心参数             |
| ------------------------ | ---------------------- | -------------------- |
| `android_describe_tools` | 获取指定工具的详细描述 | `tools` 工具名称数组 |
| `android_search_tools`   | 按关键词搜索工具       | `query` 搜索关键词   |

---

## 一、实现原理

Neuralbridge MCP Server 基于 Android **无障碍服务（AccessibilityService）** 实现，无需 root 权限即可实现对 Android 设备的完全控制，整体架构分为三层：

### 1. 通信层
- 基于 Ktor 实现 HTTP 服务器，默认监听 7474 端口
- 采用 JSON-RPC 2.0 协议进行通信，支持 CORS 跨域访问
- 提供标准化的 MCP 工具接口，兼容 Claude Code 等支持 MCP 协议的客户端

### 2. 控制核心层
所有控制能力都通过 Android 系统的无障碍服务 API 实现：
- **手势控制**：通过 `AccessibilityService.dispatchGesture()` API 模拟用户触摸操作，支持点击、长按、双击、滑动、捏合缩放、拖拽等所有标准手势，精度可达像素级。
- **文本输入**：通过 `AccessibilityNodeInfo.ACTION_SET_TEXT` 直接设置输入框内容，失败时自动降级为剪贴板粘贴方案。
- **系统操作**：通过 `performGlobalAction()` 执行返回、主页、最近任务、打开通知、快速设置等系统级操作。
- **应用管理**：通过 PackageManager 实现应用启动、关闭、URL 打开等功能。

### 3. 感知能力层
- **UI 结构解析**：通过 `UiTreeWalker` 遍历无障碍节点树，获取当前屏幕所有 UI 元素的 ID、文本、坐标、可点击状态等信息，支持按文本、ID、内容描述等方式查找元素。
- **截图能力**：优先使用 `MediaProjection` API 实现高速截图（<60ms），Android 14+ 授权失效时自动降级为 `AccessibilityService.takeScreenshot()` 方案（无需额外授权）。
- **通知监听**：通过 `NotificationListenerService` 获取系统通知和 Toast 消息。

---

## 二、已知问题与不足

### 1. 截图相关问题
- **Android 14+ 权限问题**：Android 14 及以上版本的 MediaProjection 是单次授权，应用重启或设备重启后需要用户手动重新确认授权，无法实现完全自动化。
- **屏幕旋转适配问题**：VirtualDisplay 创建后如果屏幕发生旋转，分辨率不匹配会导致截图变形或失败，目前没有动态重建 VirtualDisplay 的逻辑。
- **资源泄漏风险**：ImageReader 超时后虽然会释放资源，但频繁超时场景下可能出现资源泄漏，导致后续截图失败。
- **硬件位图转换问题**：无障碍服务 fallback 截图返回的硬件缓冲区在部分设备上转换为软件位图时可能失败。

### 2. 输入相关问题
- **剪贴板污染**：文本输入 fallback 方案会覆盖用户当前剪贴板内容，影响用户体验。
- **Tab 键实现不可靠**：`pressKey()` 中 Tab 键通过查找下一个兄弟节点实现，在复杂布局中可能无法正确移动焦点。
- **自定义输入框兼容性差**：对于不支持 `ACTION_SET_TEXT` 的自定义输入框，没有模拟按键输入的 fallback 方案。

### 3. 稳定性问题
- **节点泄漏风险**：部分场景下 `AccessibilityNodeInfo` 对象没有正确回收，长时间运行可能导致内存泄漏。
- **UI 树遍历性能**：当界面节点数量过多时（比如长列表），全量遍历 UI 树可能导致卡顿甚至 ANR。
- **缺少限流机制**：HTTP 服务器没有请求限流，短时间内大量并发请求可能导致服务崩溃。

### 4. 安全性问题
- **无身份认证**：HTTP 接口没有任何认证机制，同一局域网内的任意设备都可以控制手机，存在严重安全风险。
- **CORS 配置过宽**：`Access-Control-Allow-Origin` 设置为 `*`，允许任意网站跨域调用接口，容易被恶意网页利用。

### 5. 功能局限性
- **多窗口适配不足**：对分屏、自由窗口等多窗口模式适配不好，获取 UI 元素坐标时可能出现偏差。
- **多用户不支持**：Android 多用户模式下，无法获取其他用户的界面信息和进行控制。
- **参数校验不严格**：部分工具的输入参数没有做范围校验，比如传入超出屏幕范围的坐标会导致手势执行失败但没有明确提示。

### 6. 性能优化空间
- **轮询效率低**：`wait_for_element` 等轮询方法默认间隔 300ms，对快速变化的界面响应不够及时，且频繁遍历 UI 树占用 CPU 资源。
- **截图优化不足**：缩略图模式没有进一步降低分辨率，截图速度还有提升空间。
- **缺少手势重试机制**：手势被系统拦截时没有自动重试逻辑，某些场景下操作成功率低。