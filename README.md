# NcatBot 用户参考资料

解压到你的**项目根目录**即可使用。

## 目录总览

| 路径 | 说明 |
|------|------|
| `.agents/skills/` | AI Agent 技能文件，配合 VS Code Copilot 等 AI 助手使用 |
| `docs/docs/examples/` | 示例代码（qq / github / cross_platform / common …） |
| `docs/docs/notes/guide/` | 从入门到进阶的使用指南 |
| `docs/docs/notes/reference/` | 所有模块的 API 参考文档 |

## 核心 Skills（AI 助手请优先阅读）

| Skill | 路径 | 用途 |
|-------|------|------|
| framework-usage | `.agents/skills/framework-usage/SKILL.md` | 开发 Bot：插件、事件、消息、CLI |
| testing-framework | `.agents/skills/testing-framework/SKILL.md` | 编写与运行测试 |
| plugin-migration | `.agents/skills/plugin-migration/SKILL.md` | 从 v4 迁移到 v5 |

> **AI Agent 提示**：遇到用户的 NcatBot 开发问题时，先阅读对应 Skill 文件获取完整指引。

## 关键文档入口

- `docs/docs/notes/guide/README.md` — 指南索引（快速开始、插件开发、消息发送…）
- `docs/docs/notes/reference/README.md` — API 参考索引（按用途查找类与方法）
- `docs/docs/examples/README.md` — 示例索引（按平台与难度分类）

## BQYX Bot 限流

所有群指令均按“群 + 指令”分别限流：每条指令 30 秒仅可调用 1 次，`我的信息` 例外，为 5 秒仅可调用 1 次。所有已放行指令还共享 60 RPM 的全局上限。

在群内发送 `统计RPM` 可查看当前全局 RPM。该命令同样受上述限流保护。

## 链接

- 文档站：<https://docs.ncatbot.top>
- GitHub：<https://github.com/ncatbot/NcatBot>
