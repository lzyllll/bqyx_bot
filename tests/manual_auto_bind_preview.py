import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ncatbot.app import BotClient
from ncatbot.utils import get_log

from plugins.bqyx_bot.account import AccountService
from plugins.bqyx_bot.bind_match import match_members
from plugins.bqyx_bot.config import load_settings
from plugins.bqyx_bot.models import GameMember, QQMember
from plugins.bqyx_bot.store import SqliteStore

LOG = get_log("test")
settings = load_settings()
bot = BotClient(plugins_dir=None)
sqllite_store = SqliteStore(
    path=REPO_ROOT / "data" / "bqyx_bot" / "bqyx.db",
    retention_days=3,
    union_retention_days=15,
)
service = AccountService(settings=settings, store=sqllite_store, logger=LOG)


async def main():
    group_id = "917325789"
    union_id = 4927

    group_members = await bot.api.qq.query.get_group_member_list(int(group_id))
    qq_members = [
        QQMember(
            qq_id=str(member.user_id),
            nickname=(member.card or member.nickname or str(member.user_id)).strip(),
        )
        for member in group_members
        if "客串" not in (member.card or member.nickname or "")
    ]

    account = await service.get_user()
    raw_game_members = await account.get_members(union_id)
    game_members = []
    for member in raw_game_members:
        detail = getattr(member, "detail", None)
        nickname = getattr(detail, "playerName", None) or getattr(
            member, "nickname", None
        )
        if not nickname:
            continue
        game_members.append(
            GameMember(
                uid=str(member.uid),
                arch_index=int(member.index),
                nickname=str(nickname).strip(),
            )
        )
    resolved, auto_lines, unmatched_games = match_members(qq_members, game_members)

    print(f"QQ 成员: {len(qq_members)}，军队成员: {len(game_members)}")
    print(f"可自动绑定: {len(resolved)}")
    for line in auto_lines:
        print(line)
    print(f"未匹配军队成员: {len(unmatched_games)}")
    for nickname in unmatched_games:
        print(f"未匹配军队成员: {nickname}")


async def run_preview() -> None:
    await bot.run_async()
    try:
        await main()
    finally:
        await bot.shutdown()


if __name__ == "__main__":
    asyncio.run(run_preview())
