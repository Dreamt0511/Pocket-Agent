---
name: code-review
description: 执行全面的代码审查，包括安全、性能和可维护性分析。
tags:
  - 开发
  - 代码质量
  - 审查
---

# 代码审查技能

您现在具备了进行全面的代码审查的专业知识。请按照以下结构化方法操作：

## 审查清单

### 1. 安全性 (关键)

检查以下项目：
- [ ] **注入漏洞**: SQL注入、命令注入、XSS、模板注入
- [ ] **认证问题**: 硬编码凭证、弱认证机制
- [ ] **授权缺陷**: 缺失访问控制、IDOR
- [ ] **数据泄露**: 日志和错误消息中的敏感信息
- [ ] **加密安全**: 弱算法、不当密钥管理
- [ ] **依赖项**: 已知漏洞（使用 `npm audit`、`pip-audit` 检查）

```bash
# 快速安全检查
npm audit                    # Node.js
pip-audit                    # Python
cargo audit                  # Rust
grep -r "password\\|secret\\|api_key" --include="*.py" --include="*.js"
```

### 2. 正确性

检查以下项目：
- [ ] **逻辑错误**: 越界、空值处理、边界情况
- [ ] **竞态条件**: 无同步的并发访问
- [ ] **资源泄漏**: 未关闭的文件、连接、内存
- [ ] **错误处理**: 吞没异常、缺失错误路径
- [ ] **类型安全**: 隐式转换、任意类型

### 3. 性能

检查以下项目：
- [ ] **N+1查询**: 循环中的数据库调用
- [ ] **内存问题**: 大分配、保留引用
- [ ] **阻塞操作**: 异步代码中的同步I/O
- [ ] **低效算法**: 本可用O(n)却用了O(n^2)
- [ ] **缺失缓存**: 重复的昂贵计算

### 4. 可维护性

检查以下项目：
- [ ] **命名规范**: 清晰、一致、描述性强
- [ ] **复杂度**: 函数>50行、嵌套深度>3层
- [ ] **代码重复**: 复制粘贴的代码块
- [ ] **死代码**: 未使用的导入、不可达分支
- [ ] **注释**: 过时的、冗余的或缺失的

### 5. 测试

检查以下项目：
- [ ] **覆盖率**: 关键路径已测试
- [ ] **边界情况**: 空值、边界值
- [ ] **模拟**: 外部依赖隔离
- [ ] **断言**: 有意义的、具体的检查

## 审查输出格式

```markdown
## 代码审查: [文件/组件名称]

### 总结
[1-2句概述]

### 关键问题
1. **[问题]** (第X行): [描述]
   - 影响: [可能导致的后果]
   - 修复: [建议解决方案]

### 改进建议
1. **[建议]** (第X行): [描述]

### 积极评价
- [做得好的地方]

### 结论
[ ] 可以合并
[ ] 需要小修改
[ ] 需要重大修订
```

## 常见模式警示

### Python
```python
# 错误: SQL注入
cursor.execute(f"SELECT * FROM users WHERE id = {user_id}")
# 正确:
cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))

# 错误: 命令注入
os.system(f"ls {user_input}")
# 正确:
subprocess.run(["ls", user_input], check=True)

# 错误: 可变默认参数
def append(item, lst=[]):  # 错误: 共享的可变默认值
# 正确:
def append(item, lst=None):
    lst = lst or []
```

### JavaScript/TypeScript
```javascript
// 错误: 原型污染
Object.assign(target, userInput)
// 正确:
Object.assign(target, sanitize(userInput))

// 错误: eval使用
eval(userCode)
// 正确: 绝不要对用户输入使用eval

// 错误: 回调地狱
getData(x => process(x, y => save(y, z => done(z))))
// 正确:
const data = await getData();
const processed = await process(data);
await save(processed);
```

## 审查命令

```bash
# 显示最近的更改
git diff HEAD~5 --stat
git log --oneline -10

# 查找潜在问题
grep -rn "TODO\\|FIXME\\|HACK\\|XXX" .
grep -rn "password\\|secret\\|token" . --include="*.py"

# 检查复杂度 (Python)
pip install radon && radon cc . -a

# 检查依赖项
npm outdated  # Node
pip list --outdated  # Python
```

## 审查流程

1. **理解上下文**: 阅读PR描述、相关issue
2. **运行代码**: 构建、测试、如有条件本地运行
3. **自上而下阅读**: 从主入口点开始
4. **检查测试**: 是否已测试？测试是否通过？
5. **安全扫描**: 运行自动化工具
6. **手动审查**: 使用上述清单
7. **编写反馈**: 具体、提出修复建议、友善