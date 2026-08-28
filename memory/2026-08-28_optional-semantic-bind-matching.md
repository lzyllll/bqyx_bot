# 2026-08-28 可选语义一键绑定

## 变更类型

feat

## 内容

- SentenceTransformer 改为 `semantic-bind` 可选依赖，默认安装不下载模型。
- 未安装 extra 时，保留 RapidFuzz 文本评分与 `linear_sum_assignment` 一对一分配。
- 移除军团前缀自动剥离，避免将前缀不同的昵称直接当作相同名称。

## 四位一体

- Code: `plugins/bqyx_bot/bind_match.py`
- Test: `tests/test_bind_match.py`
- Docs: `README.md`
- Skill: 不适用

## 备注

- 安装语义额外依赖：`uv sync --extra semantic-bind`；其中包含 `httpx[socks]`，支持 SOCKS 代理下载模型。
