import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT.parent))
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "lib" / "bqyx_api"))

from render.union_rank_render import UnionRankRenderer

async def main():
    renderer = UnionRankRenderer()

    # 完全还原用户图片 media_1790656092664.jpg 中的真实数据
    rows = [
        {
            "rank": 23,
            "union_id": 40787,
            "name": "雨夜带刀不带伞",
            "contribution": 80715020,
            "today_contribution": 138500,
            "members_num": 100,
            "member_change": None,
            "highlight": False,
        },
        {
            "rank": 24,
            "union_id": 10549,
            "name": "血域",
            "contribution": 196984440,
            "today_contribution": 138080,
            "members_num": 100,
            "member_change": "+1",
            "highlight": False,
        },
        {
            "rank": 25,
            "union_id": 4927,
            "name": "屠龙：一剑问天！",
            "contribution": 249016060,
            "today_contribution": 137200,
            "members_num": 100,
            "member_change": None,
            "highlight": False,
        },
        {
            "rank": 26,
            "union_id": 24816,
            "name": "小可爱们集合",
            "contribution": 171716250,
            "today_contribution": 137200,
            "members_num": 100,
            "member_change": None,
            "highlight": False,
        },
        {
            "rank": 27,
            "union_id": 15093,
            "name": "RMB无解",
            "contribution": 138940640,
            "today_contribution": 137200,
            "members_num": 100,
            "member_change": None,
            "highlight": False,
        },
        {
            "rank": 28,
            "union_id": 20054,
            "name": "神域之都",
            "contribution": 127442110,
            "today_contribution": 137200,
            "members_num": 100,
            "member_change": None,
            "highlight": False,
        },
        {
            "rank": 29,
            "union_id": 29802,
            "name": "茗人堂",
            "contribution": 100655840,
            "today_contribution": 137200,
            "members_num": 100,
            "member_change": None,
            "highlight": True,  # 本军高亮
        },
        {
            "rank": 30,
            "union_id": 26077,
            "name": "梦忆",
            "contribution": 65608460,
            "today_contribution": 137200,
            "members_num": 100,
            "member_change": None,
            "highlight": False,
        },
        {
            "rank": 31,
            "union_id": 1761,
            "name": "煞龙·天战",
            "contribution": 204346910,
            "today_contribution": 137010,
            "members_num": 100,
            "member_change": None,
            "highlight": False,
        },
        {
            "rank": 32,
            "union_id": 46861,
            "name": "重铸",
            "contribution": 28661960,
            "today_contribution": 137010,
            "members_num": 100,
            "member_change": None,
            "highlight": False,
        },
        {
            "rank": 33,
            "union_id": 9343,
            "name": "渡鸦军团",
            "contribution": 118281720,
            "today_contribution": 136260,
            "members_num": 98,
            "member_change": "-2",
            "highlight": False,
        },
        {
            "rank": 34,
            "union_id": 40895,
            "name": "新火",
            "contribution": 79398790,
            "today_contribution": 136100,
            "members_num": 100,
            "member_change": None,
            "highlight": False,
        },
        {
            "rank": 35,
            "union_id": 11193,
            "name": "炫风王者军队",
            "contribution": 194097020,
            "today_contribution": 135800,
            "members_num": 100,
            "member_change": None,
            "highlight": False,
        },
    ]

    html = renderer.html(
        title="昨日贡献排行",
        date_label="2026-09-28",
        rows=rows,
        captured_at="2026-09-28 23:59:50",
        show_daily=True,
        score_label="日贡",
    )

    output_dir = PROJECT_ROOT / "test" / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    out_html = output_dir / "union_rank_test.html"
    out_html.write_text(html, encoding="utf-8")
    print(f"HTML saved to {out_html}")

    print("Rendering PNG with Playwright...")
    png_bytes = await renderer.to_png(html)
    out_png = output_dir / "union_rank_test.png"
    out_png.write_bytes(png_bytes)
    print(f"PNG generated successfully! Size: {len(png_bytes)} bytes")
    print(f"Image saved to: {out_png}")

if __name__ == "__main__":
    asyncio.run(main())
