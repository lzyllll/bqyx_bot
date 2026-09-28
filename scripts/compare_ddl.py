import sqlite3

def compare_ddl():
    p1 = '/home/lzyllll/bqyx/bqyx_bot/data/bqyx_bot/bqyx.db'
    p2 = '/home/lzyllll/bqyx/astrbot/data/plugins/astrbot_plugin_bqyx/data/bqyx.db'
    for p in [p1, p2]:
        conn = sqlite3.connect(p)
        cur = conn.cursor()
        cur.execute("SELECT sql FROM sqlite_master WHERE name='union_snapshot'")
        print(p, '=>\n', cur.fetchone()[0])
        cur.execute("PRAGMA table_info(union_snapshot)")
        print('Columns:', cur.fetchall())

if __name__ == '__main__':
    compare_ddl()
