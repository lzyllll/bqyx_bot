from __future__ import annotations


class BotError(Exception):
    """可直接回复给用户的业务错误。"""


class ArmyNotBoundError(BotError):
    def __init__(self) -> None:
        super().__init__(
            "当前群尚未绑定军队，请管理员先使用『绑定军队 <军队ID>』进行绑定。\n"
            "例如：绑定军队 1234"
        )


class UserNotBoundError(BotError):
    def __init__(self) -> None:
        super().__init__(
            "您尚未绑定游戏角色，请先使用以下任一方式进行绑定：\n"
            "• 『绑定游戏名 <角色名>』（推荐，支持重名选择。例如：绑定游戏名 张三）\n"
            "• 『绑定uid <UID>』（例如：绑定uid 123456）\n"
            "• 『绑定账号 <4399账号>』（例如：绑定账号 my_user）"
        )


class AccountNotConfiguredError(BotError):
    def __init__(self) -> None:
        super().__init__("代理账号未配置，请在 .env 中设置 BQYX_USERNAME 和 BQYX_PASSWORD。")
