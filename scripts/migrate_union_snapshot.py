import shutil
import sqlite3
import sys
from datetime import datetime

SOURCE_DB = "/home/lzyllll/bqyx/bqyx_bot/data/bqyx_bot/bqyx.db"
TARGET_DB = "/home/lzyllll/bqyx/astrbot/data/plugins/astrbot_plugin_bqyx/data/bqyx.db"

def migrate():
    print(f"[{datetime.now()}] 开始迁移 union_snapshot ...")
    
    # 1. 备份目标数据库
    backup_file = f"{TARGET_DB}.bak_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(TARGET_DB, backup_file)
    print(f"已创建目标数据库备份: {backup_file}")

    # 2. 检查源数据库 union_snapshot 数据
    src_conn = sqlite3.connect(SOURCE_DB)
    src_cur = src_conn.cursor()
    src_cur.execute("SELECT count(*), min(snapshot_date), max(snapshot_date) FROM union_snapshot")
    src_count, min_date, max_date = src_cur.fetchone()
    print(f"源库 union_snapshot: {src_count} 条记录, 日期范围: {min_date} ~ {max_date}")
    src_conn.close()

    # 3. 执行迁移到目标数据库
    tgt_conn = sqlite3.connect(TARGET_DB)
    tgt_cur = tgt_conn.cursor()
    
    tgt_cur.execute("SELECT count(*) FROM union_snapshot")
    tgt_count_before = tgt_cur.fetchone()[0]
    print(f"目标库当前 union_snapshot 记录数: {tgt_count_before}")

    tgt_cur.execute(f"ATTACH DATABASE '{SOURCE_DB}' AS src_db")
    tgt_cur.execute("""
        INSERT OR REPLACE INTO union_snapshot (
            snapshot_date, rank, union_id, name, level, members_num, contribution, today_contribution, captured_at
        )
        SELECT 
            snapshot_date, rank, union_id, name, level, members_num, contribution, today_contribution, captured_at
        FROM src_db.union_snapshot
    """)
    tgt_conn.commit()
    tgt_cur.execute("DETACH DATABASE src_db")

    # 4. 验证迁移结果
    tgt_cur.execute("SELECT count(*), min(snapshot_date), max(snapshot_date) FROM union_snapshot")
    tgt_count_after, tgt_min_date, tgt_max_date = tgt_cur.fetchone()
    print(f"目标库迁移后 union_snapshot: {tgt_count_after} 条记录, 日期范围: {tgt_min_date} ~ {tgt_max_date}")

    # 检查 2026-09-27 的军队数量
    tgt_cur.execute("SELECT count(*) FROM union_snapshot WHERE snapshot_date = '2026-09-27'")
    latest_count = tgt_cur.fetchone()[0]
    print(f"目标库中 2026-09-27 快照记录数: {latest_count}")

    tgt_conn.close()
    print("✅ union_snapshot 数据迁移成功完成！")

if __name__ == "__main__":
    migrate()
