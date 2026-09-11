# BQYX Bot (爆枪英雄 QQ 机器人)

基于 NcatBot 框架与 `bqyx_api` 开发的爆枪英雄军队与账号管理 QQ 机器人。

---

## 快速部署指南

### 1. 环境准备

- **Python**: `>= 3.13`
- **[uv](https://docs.astral.sh/uv/)**: 推荐的 Python 包管理器
  - Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`
  - Windows: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
- **Git & GitHub SSH Key**:
  - 由于项目子模块 `lib/bqyx_api` 采用 SSH 协议拉取，请确保部署机器已配置好 GitHub SSH Key。
  - 测试连通性：`ssh -T git@github.com`（出现 `Hi username!` 即表示配置成功）。
- **OneBot11 服务**: 如 [NapCat](https://napneko.github.io/)，需开启正向 WebSocket 服务。

---

### 2. 克隆项目与子模块

**方式 A：克隆时直接初始化子模块（推荐）**
```bash
git clone --recursive git@github.com:lzyllll/bqyx_bot.git
cd bqyx_bot
```

**方式 B：若已克隆主仓库，补拉子模块**
```bash
cd bqyx_bot
git submodule sync
git submodule update --init --recursive
```

---

### 3. 配置修改

#### (1) 机器人与 OneBot 配置：`config.yaml`
```bash
cp config.example.yaml config.yaml
```
根据实际环境编辑 `config.yaml`：
- `bot_uin`: 机器人 QQ 号
- `root`: 管理员 QQ 号
- `adapters[type=napcat]`:
  - `ws_uri`: NapCat 的 WebSocket 连接地址（如 `ws://127.0.0.1:3001`）
  - `ws_token`: 若 NapCat 设置了 token，在此填写

#### (2) 游戏账号与数据配置：`.env`
```bash
cp .env.example .env
```
根据实际账号编辑 `.env`：
- `BQYX_USERNAME`: 4399 账号用户名
- `BQYX_PASSWORD`: 4399 账号密码
- `BQYX_ARCH_INDEX`: 存档槽位（默认 `4`，取值 `0-7`）
- `BQYX_RESOURCE_DIR` / `BQYX_ASSETS_DIR`: 静态资源及素材路径（如有需渲染图片）

---

### 4. 安装依赖

根据是否需要语义匹配选择安装命令：

```bash
# 默认安装（仅使用 RapidFuzz 快速文本匹配）
uv sync

# 推荐：启用语义匹配（首次使用会自动下载语义模型）
uv sync --extra semantic-bind
```

---

### 5. 运行机器人

#### 本地 / 前台测试运行
```bash
uv run python main.py
```

#### Linux 服务器后台运行 (推荐 Systemd 服务)

创建服务文件 `/etc/systemd/system/bqyx_bot.service`：
```ini
[Unit]
Description=BQYX QQ Bot Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/home/lzyllll/bqyx/bqyx_bot
ExecStart=/root/.local/bin/uv run python main.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```
> 注：请将上述 `User`、`WorkingDirectory` 和 `uv` 执行路径替换为服务器实际路径（可用 `which uv` 查看路径）。

管理服务命令：
```bash
# 重载服务
systemctl daemon-reload

# 启动并设置开机自启
systemctl enable --now bqyx_bot

# 查看运行状态与日志
systemctl status bqyx_bot
journalctl -u bqyx_bot -f
```

---

### 6. 日常更新与维护

当主仓库或 `bqyx_api` 子模块有代码更新时，在服务器根目录执行以下步骤：

```bash
cd /home/lzyllll/bqyx/bqyx_bot

# 1. 拉取主仓库最新提交
git pull origin main

# 2. 同步并更新子模块（主仓库已锁定对应的子模块版本）
git submodule sync
git submodule update --init --recursive

# 3. （可选）如果想直接跟踪并拉取 bqyx_api 的最新 main 分支代码
# git submodule update --remote --merge

# 4. 同步依赖
uv sync

# 5. 重启服务
systemctl restart bqyx_bot
```

---

## 目录总览

| 路径 | 说明 |
|------|------|
| `main.py` | 机器人启动入口 |
| `plugins/bqyx_bot/` | BQYX Bot 业务插件及各类指令处理器 |
| `lib/bqyx_api/` | 游戏底层接口与存档解析核心库（Submodule） |
| `.agents/skills/` | AI Agent 技能文件，配合 AI 助手使用 |
| `docs/docs/notes/guide/` | NcatBot 框架入门到进阶指南 |
| `docs/docs/notes/reference/` | NcatBot 模块 API 参考文档 |

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
