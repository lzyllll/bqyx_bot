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

## BQYX Bot 一键绑定

群内发送 `一键绑定` 后，机器人会依据 QQ 群昵称与军队角色名自动建立绑定。默认使用快速文本匹配，不会安装或下载语义模型。

如需启用 SentenceTransformer 语义匹配，可安装可选依赖：

```powershell
uv sync --extra semantic-bind
```

安装该 extra 后，机器人会在一键绑定时自动补充语义匹配；第一次使用会下载 `paraphrase-multilingual-MiniLM-L12-v2` 模型。该 extra 同时安装 `httpx[socks]`，支持配置 SOCKS 代理下载模型。未安装 extra 时会自动回退到 RapidFuzz 文本评分与 `linear_sum_assignment` 全局一对一分配，不影响一键绑定功能。

## BQYX Bot 限流

所有群指令均按“群 + 指令”分别限流：每条指令 30 秒仅可调用 1 次，`我的信息` 例外，为 5 秒仅可调用 1 次。所有已放行指令还共享 30 RPM 的全局上限。

在群内发送 `统计RPM` 可查看当前全局 RPM；发送 `统计今日调用` 可查看各指令当日的调用次数（按上海自然日统计，重启后保留）。统计数据保留最近两个月，由插件每天 00:10 自动清理过期记录。这两个命令同样受上述限流保护，且统计命令自身也会被计入。

## 链接

- 文档站：<https://docs.ncatbot.top>
- GitHub：<https://github.com/ncatbot/NcatBot>
