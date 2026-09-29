# QQ 官方机器人交互标签 `qqbot-cmd-input` 参数解析失败排查与优化指南

本文档记录了在使用 QQ 官方机器人（QQ 开放平台 / `botpy`）发送 Markdown 交互指令标签 `<qqbot-cmd-input>` 时，触发 `qqbot-cmd-input参数解析失败 (code: 40034109)` 的根本原因、排查过程与最终解决方案。

---

## 一、异常现象

当用户在群聊中绑定军队（例如军队 ID `19345`），并执行全员快捷绑定指令 `绑定游戏名 ~` 时，AstrBot 控制台输出 400 接口请求异常：

```text
[botpy] 接口请求异常，请求连接: https://api.sgroup.qq.com/v2/groups/xxxx/messages, 错误代码: 400, 返回内容: {'message': 'qqbot-cmd-input参数解析失败', 'code': 40034109, 'err_code': 40034109, 'trace_id': '0b8b01cbc6a37cbe83569b46a628a982'}
[Core] [INFO]: [QQOfficial] 回复消息失败: qqbot-cmd-input参数解析失败, 尝试使用主动发送接口。
[botpy] 接口请求异常，返回内容: {'message': '主动消息失败, 无权限', 'code': 40034105, 'err_code': 40034105}
[Core] [ERRO]: Failed to send the message chain: chain = MessageChain(chain=[Plain(text='> 💡 **军团成员快捷绑定 (共 100 人)**\n> 点击下方蓝色游戏名，自动填入绑定指令：\n> \n> 01. <qqbot...<16304 chars>')]), error = qqbot-cmd-input参数解析失败
```

> **注意**：腾讯接口返回的错误信息仅有简略的 `40034109: qqbot-cmd-input参数解析失败`，未指明具体是哪一行、哪一个标签或哪一个参数有误。

---

## 二、根本原因剖析

通过抓取军队 `19345` 的 100 名成员实际数据并比对腾讯开放平台 Markdown 规范，确认了以下两项致命根因：

### 1. `text` 参数 URL 编码后长度硬性限制 100 字符

腾讯 QQ 官方开放平台对交互标签参数有严格的长度限制：
- `<qqbot-cmd-input text="..." show="..." reference="false" />`
- **`text` 字段必须经过 URL 编码（Percent-Encoding），且编码后的字符串总长度不能超过 100 字符**。

在 UTF-8 编码下：
- 每个中文字符和中文全角符号（如 `【`、`】`）占用 **3 个字节**；
- URL 编码会将每个字节转为 `%XX`（3 个 ASCII 字符）；
- 因此 **每个中文字符/全角符号经 URL 编码后占用 9 个字符**（$3 \times 3 = 9$）。

#### 军队 19345 的实际案例：
原实现采用完整指令前缀 `f"绑定游戏名 {p_name}"`：
- `"绑定游戏名 "`（5 个中文字符 + 1 个空格）编码后为 `%E7%BB%91%E5%AE%9A%E6%B8%B8%E6%88%8F%E5%90%8D%20`，占用 **48 字符**；
- 军队 `19345` 成员统一带有军团前缀 `【大招】`（4 个中文字符/全角符号），编码后占用 **36 字符**；
- 二者相加已达 **84 字符**，留给角色名本身的上限仅剩 **16 字符**（不足 2 个汉字！）；
- 当角色名为 `冷静`（2 个汉字 = 18 字符）时：
  $$48 + 36 + 18 = \mathbf{102 \text{ 字符}} > 100$$
- 当角色名为 `饮风卧雨`（4 个汉字 = 36 字符）时：
  $$48 + 36 + 36 = \mathbf{120 \text{ 字符}} > 100$$

统计显示：在军队 `19345` 的 100 名玩家中，**整整有 63 名玩家的指令长度超过了 100 字符**！腾讯网关在解析到第 1 个超长标签时直接中断并返回 `40034109`。

---

### 2. `show` 属性包含 XML 特殊字符未转义

标签生成模板为：
```python
f'<qqbot-cmd-input text="{encoded}" show="{label}" reference="false" />'
```
军队 `19345` 中第 48 号玩家游戏名为 `佳&璐`。
拼接后得到：
```xml
<qqbot-cmd-input text="..." show="佳&璐" reference="false" />
```
在 XML 语法规范中，属性值里的 `&` 是实体引用的起始符。未转义的原始 `&` 直接导致 XML 解析器报错（`ParseError: not well-formed (invalid token)`），同样触发 `40034109` 错误。

---

## 三、解决方案与代码实现

### 1. 实现编码长度防护 `safe_quote_cmd`（[reply.py](file:///c:/Users/lzy/Desktop/bot/astrbot/data/plugins/astrbot_plugin_bqyx/reply.py)）

在 `reply.py` 中引入安全编码函数，严格保障编码后长度不超过 100 字符：

```python
def safe_quote_cmd(cmd: str, max_len: int = 100) -> str:
    """对命令进行 URL 编码，并严格保证编码后长度不超过 max_len（QQ 官方限制 100 字符）。"""
    cur_cmd = cmd.strip("\r\n")
    encoded = urllib.parse.quote(cur_cmd)
    if len(encoded) <= max_len:
        return encoded
    # 逐字从末尾截断直到 urlencode 后的长度不超过 max_len
    while cur_cmd and len(encoded) > max_len:
        cur_cmd = cur_cmd[:-1]
        encoded = urllib.parse.quote(cur_cmd)
    return encoded
```

### 2. 对 `show` 属性进行 XML/HTML 安全转义（[reply.py](file:///c:/Users/lzy/Desktop/bot/astrbot/data/plugins/astrbot_plugin_bqyx/reply.py)）

在 `md_cmd_input` 与 `md_cmd_example` 中使用 `html.escape(label.strip()[:50], quote=True)`：

```python
def md_cmd_example(label: str, full_cmd: str) -> str:
    """生成点击后将完整示例填入输入框的 QQ Markdown 交互标签。"""
    encoded = safe_quote_cmd(full_cmd.strip())
    safe_show = html.escape(label.strip()[:50], quote=True)
    return f'<qqbot-cmd-input text="{encoded}" show="{safe_show}" reference="false" />'
```
- `佳&璐` 被转义为 `佳&amp;璐`，在客户端正常渲染为 `佳&璐` 且符合 XML 语法规范。

### 3. 指令别名与智能自适应回退（[handlers/bind.py](file:///c:/Users/lzy/Desktop/bot/astrbot/data/plugins/astrbot_plugin_bqyx/handlers/bind.py)）

1. 为 `@filter.command("绑定游戏名")` 添加别名 `"绑定"`：
   ```python
   @filter.command("绑定游戏名", alias={"绑定角色名", "绑定角色", "绑定"})
   ```
2. 在全员列表渲染中智能选取指令前缀：
   - 优先使用完整前缀 `"绑定游戏名 {p_name}"`；
   - 若编码后超过 100 字符，自动回退采用紧凑等效的 `"绑定 {p_name}"`（前缀仅占 21 字符，立省 27 字符）。
   ```python
   cmd = f"绑定游戏名 {p_name}"
   if len(urllib.parse.quote(cmd)) > 100:
       cmd = f"绑定 {p_name}"
   link = md_cmd_example(p_name, cmd)
   ```
   **效果**：军队 `19345` 的全部 100 名玩家长度均成功降至 93 字符以内，无一超标，且完整保留角色原名无需截断。

---

## 四、排查与避坑指南

1. **单条消息中标签数量与体量**：
   - QQ Markdown 消息单条推荐在 2000~5000 字符以内。若成员列表极大，建议注意标签精简。
2. **QQ 开放平台主动消息权限限制**：
   - 当机器人被动回复触发报错（如 `40034109`）时，AstrBot 会尝试使用主动发送接口重试；但官方普通群聊机器人**无群内主动消息发送权限**（抛出 `40034105: 主动消息失败, 无权限`）。因此被动回复必须一次性构造合法，避免触发重试。
3. **单元测试验证**：
   - 在测试用例中加入 XML 格式验证（`xml.etree.ElementTree.fromstring`）与长度校验，防止后续重构引入回归问题。
