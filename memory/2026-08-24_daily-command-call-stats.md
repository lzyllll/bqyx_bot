# 2026-08-24 每日指令调用统计

## 变更类型

feat

## 内容

- 为全部已放行的群指令增加按“上海自然日 + 主指令名”聚合的 SQLite 调用计数。
- 增加 `统计今日调用`（别名 `统计今日调用次数`）群指令，按调用次数降序展示当天各指令与总计。
- 仅在群级和全局限流均通过后计数；重启后统计保留，统计命令本身也会被计入。
- 保持既有的全局 30 RPM 上限，并让统计命令与其共用同一限流。
- 每天 00:10 通过插件定时任务清理早于最近两个自然月的统计记录。
- 修正一条依赖固定日期的成员采集测试，使其使用当前采集日期。

## 四位一体

- Code: `plugins/bqyx_bot/hooks.py`、`plugins/bqyx_bot/store.py`、各群命令 handler、`plugins/bqyx_bot/reply.py`
- Test: `tests/test_rate_limit.py`、`tests/test_store.py`、`tests/test_schedule.py`
- Docs: `README.md`、机器人 `帮助` 输出
- Skill: 未更新；本次仅改变项目内机器人行为，不影响通用 NcatBot Skill。

## 验证

- `uv run pytest tests -q`：71 passed
- `uv run ruff check --select F ...`：通过（本次涉及文件）
