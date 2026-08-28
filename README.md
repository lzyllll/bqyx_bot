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

群内发送 `一键绑定` 后，机器人会依据 QQ 群昵称与军队角色名自动建立绑定。默认使用快速文本匹配：RapidFuzz 计算文本相似度，再由 `linear_sum_assignment` 做全局一对一分配。此模式不需要下载语义模型。

### 安装模式

`semantic-bind` 是可选依赖（extra），不会被默认安装。根据需要选择以下一种命令：

| 目标 | 命令 | 一键绑定行为 |
|------|------|-------------|
| 仅使用默认依赖 | `uv sync` | 仅文本匹配，不加载模型 |
| 启用语义匹配 | `uv sync --extra semantic-bind` | 文本匹配 + SentenceTransformer 语义匹配 |
| 安装全部可选依赖 | `uv sync --all-extras` | 启用所有 extras，包含语义匹配 |

启用语义匹配的服务器应使用：

```powershell
uv sync --extra semantic-bind
```

安装后，机器人会在一键绑定时自动补充语义匹配；第一次使用会下载 `paraphrase-multilingual-MiniLM-L12-v2` 模型。该 extra 同时安装 `httpx[socks]`（含 `socksio`），因此可通过 SOCKS 代理下载模型。

### `uv sync` 卸载模型包的原因

`uv sync` 会将虚拟环境严格同步到命令指定的依赖集合。单独执行 `uv sync` 时，该集合只包含默认依赖，不包含 `semantic-bind`，因此 uv 会卸载 `sentence-transformers`、`torch`、`transformers` 等语义匹配包。这表示 extra 没有被删除，只是本次同步没有要求安装它。

需要恢复语义匹配时，再运行一次 `uv sync --extra semantic-bind` 即可。该命令不会影响其他默认依赖；已下载的 Hugging Face 模型缓存通常也不会被 `uv sync` 删除，重新安装 Python 包后可继续使用缓存。

## BQYX Bot 限流

所有群指令均按“群 + 指令”分别限流：每条指令 30 秒仅可调用 1 次，`我的信息` 例外，为 5 秒仅可调用 1 次。所有已放行指令还共享 30 RPM 的全局上限。

在群内发送 `统计RPM` 可查看当前全局 RPM；发送 `统计今日调用` 可查看各指令当日的调用次数（按上海自然日统计，重启后保留）。统计数据保留最近两个月，由插件每天 00:10 自动清理过期记录。这两个命令同样受上述限流保护，且统计命令自身也会被计入。

## 链接

- 文档站：<https://docs.ncatbot.top>
- GitHub：<https://github.com/ncatbot/NcatBot>
