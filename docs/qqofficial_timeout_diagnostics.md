# QQ 官方机器人（qq_official / botpy）接口超时排查与优化指南

本文档记录了在 Linux 服务器部署 AstrBot QQ 官方机器人适配器时，接口频繁超时并导致 `'NoneType' object is not subscriptable` 崩溃的根本原因、排查方法与解决方案。

---

## 一、异常现象

在启动 AstrBot (`astrbot run`) 加载 QQ 官方机器人适配器时，控制台连续输出超时警告并在约 40 秒后崩溃：

```text
[Core] [INFO]: Loading IM platform adapter qq_official(default) ...
...
请求超时，请求连接: https://api.sgroup.qq.com/users/@me
请求超时，请求连接: https://api.sgroup.qq.com/gateway/bot
[Core] [ERRO] [platform.manager:255]: ------- Task platform_qq_official_default failed: 'NoneType' object is not subscriptable
[Core] [ERRO] [platform.manager:257]: |    Traceback (most recent call last):
[Core] [ERRO] [platform.manager:257]: |      File ".../botpy/client.py", line 148, in start
[Core] [ERRO] [platform.manager:257]: |        await self._bot_login(token)
[Core] [ERRO] [platform.manager:257]: |      File ".../botpy/client.py", line 171, in _bot_login
[Core] [ERRO] [platform.manager:257]: |        max_async=self._ws_ap["session_start_limit"]["max_concurrency"],
[Core] [ERRO] [platform.manager:257]: |                  ~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^
[Core] [ERRO] [platform.manager:257]: |    TypeError: 'NoneType' object is not subscriptable
```

---

## 二、根本原因分析

### 1. 代码层原因
官方 `botpy` SDK 在登录阶段执行以下逻辑：
1. 请求 `GET /users/@me` 获取机器人身份信息；
2. 请求 `GET /gateway/bot` 获取 WebSocket 网关地址（存入 `self._ws_ap`）。

当网络请求遇到 `asyncio.TimeoutError` 时，SDK 捕获异常仅打印 `请求超时，请求连接: ...` 并返回 `None`。随后代码试图从 `self._ws_ap["session_start_limit"]` 取值，触发了 `TypeError: 'NoneType' object is not subscriptable`。

### 2. 网络层核心根因（DNS 跨域调度与 PMTU 黑洞）
通过在云服务器抓包与路由追踪，发现了两个核心网络冲突：

1. **云厂商内网 DNS 跨省调度与丢包**：
   - 例如服务器位于**京东云北京机房**，其默认内网 DNS（`169.254.169.240`）将 `api.sgroup.qq.com` 调度解析至腾讯云华东/上海节点（`175.27.13.145`、`175.27.8.158`）。
   - 该公网跨省链路质量极差（丢包率 50% ~ 100%）。
2. **Path MTU (PMTU) 黑洞导致 TLS 握手卡死**：
   - 云服务器网卡一般有虚拟网络封装（如 MTU=1450），而远程腾讯云节点发出的 TLS 证书包（`Server Certificate`）体积常达 3KB~8KB（多个满载 1500 字节数据包）。
   - 中间路由因 MTU 不匹配直接丢弃了分片包且未返回 ICMP 报错，导致 TCP 握手虽然成功，但 **TLS 握手在第 2 步永久卡死**，直到 20 秒超时断开。
3. **代理环境变量干扰**：
   - 若服务器安装了 Clash（`clashctl` / `watch_proxy`），终端会自动导出 `http_proxy`、`ALL_PROXY`。
   - 腾讯官方机器人接口（`api.sgroup.qq.com`）严格限制仅允许**中国大陆 IP** 访问，流量一旦流入海外代理节点会被直接阻断。

---

## 三、解决方案

### 方案 A：静态指定北京同城 Anycast 节点（推荐，立即生效）

在服务器 `/etc/hosts` 中加入腾讯云低延迟直连节点 IP：

```bash
sudo bash -c 'cat << "EOF" >> /etc/hosts
# QQ Official Bot API Endpoints (Beijing Anycast)
42.81.179.142 api.sgroup.qq.com
42.81.184.38 bots.qq.com
EOF'
```

> **原理**：Linux 系统优先使用 `/etc/hosts` 的静态解析（优先级高于 DNS），直接绕过云内网 DNS 的调度失常，直连同城北京 Anycast BGP VIP（延时约 3~5ms，0% 丢包，彻底避免 TLS 证书大包黑洞）。

---

### 方案 B：配置公共 DNS 服务器

若不想修改 hosts，可将系统的默认 DNS 替换为国内公共 DNS（如阿里 DNS、腾讯 DNSPod、114）：

1. 编辑 `/etc/systemd/resolved.conf`：
   ```ini
   [Resolve]
   DNS=223.5.5.5 223.6.6.6 114.114.114.114
   FallbackDNS=119.29.29.29
   ```

2. 若网卡通过 DHCP 自动获取了云厂商内网 DNS，可在 `/etc/netplan/` 配置文件中增加覆写：
   ```yaml
   network:
     ethernets:
       eth0:
         dhcp4: true
         dhcp4-overrides:
           use-dns: false
         nameservers:
           addresses: [223.5.5.5, 114.114.114.114]
   ```
   应用配置：
   ```bash
   sudo netplan apply
   sudo systemctl restart systemd-resolved
   ```

---

### 方案 C：排除代理环境变量

确保运行 AstrBot 的会话不受海外代理影响：

```bash
# 在启动前清除代理环境变量
unset http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY
```

或者在 AstrBot 的 `data/cmd_config.json` 中明确保持 `http_proxy` 为空。

---

## 四、验证方法

运行独立脚本验证与 QQ 开放平台网关的连通性：

```bash
python3 -c "
import asyncio, botpy
from botpy.robot import Token
from botpy.http import BotHttp, Route

async def main():
    token = Token(app_id='你的APPID', secret='你的SECRET')
    http = BotHttp(timeout=20, app_id='你的APPID', secret='你的SECRET')
    user = await http.login(token)
    print('登录成功:', user)
    ws_ap = await http.request(Route('GET', '/gateway/bot'))
    print('WebSocket 网关地址:', ws_ap)

asyncio.run(main())
"
```

若 1 秒内打印出机器人信息及 `wss://api.sgroup.qq.com/websocket` 网关地址，则代表网络已完全畅通，即可正常运行 AstrBot。
