# 2026-08-24 群指令限流与 RPM 统计

## 变更类型

feat

## 内容

- 为全部 BQYX 群指令补齐按“群 + 指令”的滑动窗口限流：默认 30 秒 1 次，`我的信息` 为 5 秒 1 次。
- 增加所有已放行群指令共用的 30 RPM 全局上限。
- 增加 `统计RPM` 群指令，并在帮助和项目说明中记录限流规则。

## 四位一体

- Code: `plugins/bqyx_bot/hooks.py`, `plugins/bqyx_bot/handlers/help.py` 及各 handler。
- Test: `tests/test_rate_limit.py`。
- Docs: `README.md`、机器人 `帮助` 输出。
- Skill: 未更新；本次仅改变项目内机器人指令，不影响通用 NcatBot Skill。

## 备注

- 限流额度统一为默认 30 秒 1 次；`我的信息` 是唯一例外。
