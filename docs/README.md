# BQYX Bot 插件文档与设计手册

`bqyx_bot` 是基于 [NcatBot](https://github.com/liuzhengyang/ncatbot) 框架与 [bqyx_api](https://github.com/lzyllll/bqyx_api) 构建的 4399《爆枪英雄》QQ 机器人插件，专注于**军队管理、成员贡献追踪、日历热力墙、争霸/修罗战况查询以及角色面板分析**。

---

## 目录

- [一、核心功能与指令体系](#一核心功能与指令体系)
- [二、系统架构与模块划分](#二系统架构与模块划分)
- [三、核心设计专题](#三核心设计专题)
- [四、配置与部署](#四配置与部署)
- [五、数据库表设计](#五数据库表设计)

---

## 一、核心功能与指令体系

### 1. 个人绑定与基础查询

| 指令 | 说明 | 示例 |
|---|---|---|
| `绑定游戏名 <名称片段/全名>` | 包含匹配绑定（支持片段模糊匹配，无需输全名；唯一时直绑且**不暴露 UID**；重名时会话选择） | `绑定游戏名 战神` |
| `绑定uid <UID>` | 按游戏数字 UID 绑定 | `绑定uid 123456` |
| `绑定账号 <4399账号>` | 按 4399 平台账号绑定 | `绑定账号 user_abc` |
| `我的信息` / `我` | 查询当前已绑定的游戏账号信息与状态 | `我的信息` |
| `我的贡献` / `贡献墙` / `我的日贡` | 渲染当月每日日贡贡献日历热力墙（支持指定历史月份） | `我的贡献` / `我的贡献 2026-08` / `我的贡献 8月` / `我的贡献 上月` |
| `我的战力` / `查战力` | 解析角色装备、军衔、加成并生成战力面板长图 | `我的战力` |
| `我的物品 <名称>` / `查物品` | 检索背包/仓库中的指定装备与道具 | `我的物品 冰雪` |
| `查修罗` | 查看当前账号或指定群友绑定的修罗路线图 | `查修罗` / `查修罗 @张三` |

### 2. 本群军队查询

| 指令 | 说明 | 示例 |
|---|---|---|
| `绑定军队 <军队ID>` | 将本群与游戏内的军队建立关联（管理员专属） | `绑定军队 1234` |
| `军队信息` | 查看当前群绑定军队的基本信息与等级 | `军队信息` |
| `查成员` | 查看当前军队全员名单、今日日贡与状态排行长图 | `查成员` |
| `查争霸` | 查看军队城池分布与争霸状态 | `查争霸` |
| `查PK` | 查看军队内部 PK 战力排行 | `查PK` |
| `昨日贡献 [阈值]` | 查询昨日日贡达标情况；带阈值仅列出未达标成员 | `昨日贡献 1400` |
| `一键绑定` | 纯算法模糊匹配群昵称与军团成员名并批量绑定 | `一键绑定` |

### 3. 全服排行长图

| 指令 | 说明 | 示例 |
|---|---|---|
| `实时军队排行 [数量]` | 全服军队总贡献实时排名（前 1000 名，每页 100 递增） | `实时军队排行 100` |
| `今日日贡排行 [数量]` | 全服军队当日新增日贡排名（相邻快照差值计算） | `今日日贡排行 50` |
| `昨日日贡排行 [数量]` | 全服军队昨日日贡排名 | `昨日日贡排行 100` |
| `本周周贡排行 [数量]` | 全服军队本周累计周贡排名 | `本周周贡排行 100` |
| `上周周贡排行 [数量]` | 全服军队上周周贡历史排行 | `上周周贡排行 100` |

---

## 二、系统架构与模块划分

```
plugins/bqyx_bot/
├── plugin.py             # BqyxPlugin 插件入口、生命周期与定时任务注册
├── context.py            # BqyxServices 服务依赖注入基类
├── config.py             # Settings 配置与环境变量读取
├── models.py             # 数据模型 (UserBind, MemberSnapshot, MemberDaily, UnionSnapshot)
├── store.py              # SqliteStore 数据库访问层
├── reply.py              # 回复构造与图片/卡片发送服务
├── schedule.py           # 时间计算、自然日转换与 0 点总贡献计算工具
├── parsing.py            # 参数解析、正则提取、会话序号解析
├── errors.py             # 业务异常定义 (ArmyNotBoundError, UserNotBoundError 等)
├── handlers/             # 业务 Handler Mixin
│   ├── bind.py           # 账号绑定与重名会话交互处理
│   ├── query.py          # 战力、修罗、贡献墙与成员查询
│   ├── schedule.py       # 每日定时采集与昨日贡献计算
│   ├── union_rank.py     # 全服军队排行拉取与缓存
│   ├── things.py         # 背包物品检索
│   └── admin.py          # 军队解绑与群管指令
├── render/               # 图片渲染模块 (Jinja2 + Playwright)
│   ├── my_contribution_render.py # 贡献热力墙 HTML/图片渲染
│   ├── union_rank_render.py      # 排行榜长图渲染
│   ├── help_render.py            # 指令帮助卡片渲染
│   └── templates/                # Jinja2 HTML 模板
└── assets/               # 静态资源 (预渲染的 help.png 等)
```

---

## 三、核心设计专题

### 1. 每日真实贡献与快照两表分离设计

详细架构、数学推导与运行机制参见专章文档：
👉 **[每日贡献计算与快照架构设计 (contribution_and_snapshot_design.md)](./contribution_and_snapshot_design.md)**

**核心要点：**
- **两表职责分离**：`member_snapshot` 存储 4399 接口原貌，只负责基线采样；`member_daily` 专门记录 24 小时真实完整日贡。
- **0 点总贡献差值算法**：利用「0 点总贡献 = contribution - conDay」在自然日内严格恒定的数学性质，通过两日 0 点总贡献的差值精确计算，**彻底解决 23:40 晚捐款丢失问题**。
- **今日实时获取**：在查询当月时，今日数据永远通过 API 实时拉取最新 `conDay`。
- **懒计算写穿缓存**：若前一日数据尚未入库（如夜间关机），查询时自动以昨日快照 + 今日在线数据计算并单次落库；再次查询直接读取数据库，不再重复触发计算。
- **统一两月保留窗口**：`member_snapshot` 与 `member_daily` 共享同一个环境变量 `BQYX_SNAPSHOT_RETENTION_DAYS`（默认 63 天约两个月）进行自动过期清理。

### 2. 会话式游戏名绑定设计

- 支持别名：`绑定游戏名` / `绑定角色名` / `绑定角色`。
- 采用包含（`in`）模糊匹配（`name.lower() in m.detail.playerName.lower()`），用户**输入名称片段即可，无需准确全名**。
- **唯一匹配**：若军队成员中满足模糊包含的角色名仅有 1 个，直接完成绑定，**回复中绝不暴露 UID**。
- **多重名匹配**：当匹配到多个候选角色时，使用 NcatBot 官方会话组件 `wait_session_reply` 向用户展示序号候选列表，30 秒内等待序号输入，支持“取消/退出”，保证多重名场景下的准确性。

### 3. 排行榜分层扩展与缓存

- 全服前 1000 名军队排行，采用“先小查、超额渐进拉取”的分页策略（每页 100 条逐步扩容），兼顾首屏速度与大排行完整度。
- 排行快照每天 23:59:50 采集，通过前后两天总贡献差值计算当日军队日贡。

---

## 四、配置与部署

### 环境变量 (`.env`)

```ini
# 4399 登录凭证与默认存档
BQYX_USERNAME=your_username
BQYX_PASSWORD=your_password
BQYX_ARCH_INDEX=4

# 成员快照与每日日贡保留天数 (默认 63 天，覆盖两个自然月)
BQYX_SNAPSHOT_RETENTION_DAYS=63

# 军队排行快照保留天数 (默认 15 天)
BQYX_UNION_SNAPSHOT_RETENTION_DAYS=15
```

### 插件加载方式

在 NcatBot 主入口（如 `main.py`）中加载：
```python
from ncatbot.core import Bot

bot = Bot()
bot.load_plugin("bqyx_bot")
bot.run()
```

---

## 五、数据库表设计

数据库默认存储于插件工作目录下的 SQLite 数据库 `bqyx.db` 中：

1. **`user_bind`**：QQ 用户与游戏账号存档绑定表
   - 主键：`(group_id, qq_id)`
   - 字段：`uid`, `arch_index`, `updated_at`
2. **`group_army`**：QQ 群与军队关联表
   - 主键：`group_id`
   - 字段：`army_id`, `updated_at`
3. **`member_snapshot`**：军队成员原始快照表（每天 23:30 采样）
   - 主键：`(army_id, snapshot_date, uid, arch_index)`
   - 字段：`nickname`, `contribution`, `con_day`, `this_week`, `captured_at`
4. **`member_daily`**：成员每日真实完整贡献表（基于前后两日 0 点总贡献差值计算，保留 63 天）
   - 主键：`(army_id, date, uid)`
   - 字段：`nickname`, `daily_contribution`, `end_of_day_total`, `computed_at`
5. **`union_snapshot`**：军队排行榜快照表（每天 23:59 采样前 1000 名，保留 15 天）
   - 主键：`(snapshot_date, union_id)`
   - 字段：`rank`, `name`, `level`, `members_num`, `contribution`, `today_contribution`, `captured_at`
6. **`command_call_stat`**：群指令每日调用统计表（保留 2 个月）
   - 主键：`(stat_date, command_name)`
   - 字段：`call_count`
