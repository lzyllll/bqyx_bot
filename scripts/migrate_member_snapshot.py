import shutil
import sqlite3
from datetime import datetime

SOURCE_DB = "/home/lzyllll/bqyx/bqyx_bot/data/bqyx_bot/bqyx.db"
TARGET_DB = "/home/lzyllll/bqyx/astrbot/data/plugins/astrbot_plugin_bqyx/data/bqyx.db"

def inspect():
    print(f"[{datetime.now()}] 检查 member_snapshot 表结构与记录数 ...")
    for name, path in [('Source', SOURCE_DB), ('Target', TARGET_DB)]:
        conn = sqlite3.connect(path)
        cur = conn.cursor()
        cur.execute("SELECT sql FROM sqlite_master WHERE name='member_snapshot'")
        sql = cur.fetchone()
        cur.execute("SELECT count(*) FROM member_snapshot")
        cnt = cur.fetchone()[0]
        cur.execute("SELECT min(snapshot_date), max(snapshot_date) FROM member_snapshot")
        dates = cur.fetchone()
        print(f"=== {name} ({path}) ===")
        print(f"  Record count: {cnt}")
        print(f"  Date range: {dates}")
        print(f"  DDL: {sql[0] if sql else 'None'}\n")
        conn.close()

def migrate():
    # 1. 备份目标数据库
    backup_file = f"{TARGET_DB}.bak_member_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(TARGET_DB, backup_file)
    print(f"✅ 目标数据库已备份至: {backup_file}")

    # 2. 执行迁移
    tgt_conn = sqlite3.connect(TARGET_DB)
    tgt_cur = tgt_conn.cursor()

    tgt_cur.execute(f"ATTACH DATABASE '{SOURCE_DB}' AS src_db")
    tgt_cur.execute("""
        INSERT OR REPLACE INTO member_snapshot (
            army_id, snapshot_date, uid, arch_index, nickname, contribution, con_day, this_week, captured_at
        )
        SELECT 
            army_id, snapshot_date, uid, arch_index, nickname, contribution, con_day, this_week, captured_at
        FROM src_db.member_snapshot
    """)
    tgt_conn.commit()
    tgt_cur.execute("DETACH DATABASE src_db")

    # 3. 验证迁移后数据
    tgt_cur.execute("SELECT count(*), min(snapshot_date), max(snapshot_date) FROM member_snapshot")
    cnt, min_d, max_d = tgt_cur.fetchone()
    print(f"✅ 迁移后目标库 member_snapshot 记录数: {cnt}, 日期范围: {min_d} ~ {max_d}")

    # 查看军队数量与样本
    tgt_cur.execute("SELECT count(DISTINCT army_id), count(DISTINCT snapshot_date) FROM member_snapshot")
    armies, days = tgt_cur.fetchone()
    print(f"  涵盖军队数: {armies}, 涵盖天数: {days}")

    tgt_conn.close()
    print("🎉 member_snapshot 数据迁移成功完成！")

if __name__ == "__main__":
    inspect()
    migrate()
