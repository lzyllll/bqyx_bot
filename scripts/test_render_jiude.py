import asyncio
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# Ensure project root and lib/bqyx_api are in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT.parent))
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "lib" / "bqyx_api"))

from render.my_contribution_render import MyContributionRenderer

DB_PATH = Path("data/bqyx.db")
OUTPUT_DIR = Path("test/output")

async def render_for_player(cur, target_uid, target_army_id, target_name, prefix):
    year, month = 2026, 9
    start_date = f"{year:04d}-{month:02d}-01"
    end_date = f"{year:04d}-{month:02d}-30"
    
    cur.execute("""
        SELECT date, daily_contribution, end_of_day_total, nickname 
        FROM member_daily 
        WHERE uid = ? AND date >= ? AND date <= ?
        ORDER BY date ASC
    """, (str(target_uid), start_date, end_date))
    rows = cur.fetchall()
    
    daily_records = {}
    print(f"\n==========================================")
    print(f"目标角色: {target_name} (UID: {target_uid}, 军团ID: {target_army_id})")
    print(f"2026年9月历史真实贡献记录 ({len(rows)} 天):")
    for r in rows:
        d_str, contrib, total, nick = r
        daily_records[d_str] = contrib
        print(f"  日期: {d_str} | 贡献: {contrib:6d} | 当日结算总贡: {total:10d} | 昵称: {nick}")

    renderer = MyContributionRenderer()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    html = renderer.html(
        player_name=target_name,
        year=year,
        month=month,
        daily_records=daily_records,
        captured_at=now_str,
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_html = OUTPUT_DIR / f"my_contribution_{prefix}.html"
    out_html.write_text(html, encoding="utf-8")

    print(f"正在调用 Playwright 渲染 PNG ...")
    png_bytes = await renderer.to_png(html)
    out_png = OUTPUT_DIR / f"my_contribution_{prefix}.png"
    out_png.write_bytes(png_bytes)
    print(f"✅ PNG 渲染成功！文件大小: {len(png_bytes)} 字节")
    print(f"图片路径: {out_png.resolve()}")
    return out_png

async def main():
    if not DB_PATH.exists():
        print(f"Error: {DB_PATH} not found!")
        return

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    print("=== 1. 查找角色 '九德' 的数据 ===")
    
    cur.execute("SELECT DISTINCT army_id, uid, arch_index, nickname FROM member_snapshot WHERE nickname LIKE '%九德%'")
    snapshots = cur.fetchall()
    print("member_snapshot 匹配项:")
    for s in snapshots:
        print(f"  军团ID:{s[0]} UID:{s[1]} 存档:{s[2]} 昵称:{s[3]}")

    cur.execute("SELECT DISTINCT army_id, uid, nickname FROM member_daily WHERE nickname LIKE '%九德%'")
    dailies_match = cur.fetchall()
    print("\nmember_daily 匹配项:")
    for d in dailies_match:
        print(f"  军团ID:{d[0]} UID:{d[1]} 昵称:{d[2]}")

    # 分别为每一个匹配到的九德角色进行渲染
    seen_uids = set()
    targets = []
    for d in dailies_match:
        if d[1] not in seen_uids:
            seen_uids.add(d[1])
            targets.append((d[1], d[0], d[2]))

    for s in snapshots:
        if s[1] not in seen_uids:
            seen_uids.add(s[1])
            targets.append((s[1], s[0], s[3]))

    print(f"\n共找到 {len(targets)} 个匹配角色进行渲染测试:")
    for idx, (t_uid, t_army, t_name) in enumerate(targets, 1):
        prefix = f"jiude_{idx}"
        await render_for_player(cur, t_uid, t_army, t_name, prefix)

    conn.close()

if __name__ == "__main__":
    asyncio.run(main())
