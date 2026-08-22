from __future__ import annotations


class BotError(Exception):
    """可直接回复给用户的业务错误。"""


class ArmyNotBoundError(BotError):
    def __init__(self) -> None:
        super().__init__("当前群未绑定军队，请使用『绑定军队 <ID>』进行绑定。")


class UserNotBoundError(BotError):
    def __init__(self) -> None:
        super().__init__("您尚未绑定游戏 UID，请使用『绑定uid <UID> [存档]』或『绑定账号 <4399账号>』进行绑定。")


class AccountNotConfiguredError(BotError):
    def __init__(self) -> None:
        super().__init__("代理账号未配置，请在 .env 中设置 BQYX_USERNAME 和 BQYX_PASSWORD。")
