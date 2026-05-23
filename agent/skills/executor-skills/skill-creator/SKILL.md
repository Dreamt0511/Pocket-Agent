---
name: skill-creator
description: 子Agent执行完毕后沉淀技能，将执行路径编写为SKILL.md供后续复用。每个多步骤任务完成后都应调用此技能。
---

# Skill Creator (Executor 版)

任务完成后，用 file_write 将执行路径沉淀为技能文档：

## 技能目录
写入 `agent/skills/auto-skills/executor/<技能名称>/SKILL.md`

## 技能名称
从任务目标提取关键词，最多3个词用下划线连接（如 `pinduoduo_buy_shoes`）

## SKILL.md 格式
```markdown
---
name: <技能名称>
description: <一句话描述，100字以内>
---

# <技能名称>

## 任务目标
<原始任务目标>

## 执行步骤
- [compled] 步骤1描述
- [compled] 步骤2描述
...

## 关键操作
- 包名：记录用到的APP包名
- MCP工具：记录用到的MCP方法和参数
- 注意事项：执行过程中的坑和解决方桇

## 适用场景
什么情况下可以使用这个技能
```

## 规则
- 不足3步的任务跳过，不沉淀
- 失败的任务跳过，不沉淀
- 沉淀不阻塞汇报：先生成skill，再返回最终摘要
