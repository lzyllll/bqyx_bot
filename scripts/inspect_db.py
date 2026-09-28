import sqlite3

def check(db_path):
    print('===', db_path, '===')
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [row[0] for row in cur.fetchall()]
    print('Tables:', tables)
    for t in tables:
        cur.execute(f'SELECT count(*) FROM "{t}"')
        cnt = cur.fetchone()[0]
        print(f'  {t}: {cnt} rows')
        if 'union' in t or 'snapshot' in t:
            cur.execute(f'SELECT * FROM "{t}" LIMIT 1')
            cols = [desc[0] for desc in cur.description]
            print(f'    cols: {cols}')
            print(f'    sample: {cur.fetchone()}')
            # also check date range
            try:
                cur.execute(f'SELECT min(snapshot_date), max(snapshot_date) FROM "{t}"')
                print(f'    dates: {cur.fetchone()}')
            except Exception as e:
                print(f'    date query error: {e}')

check('/home/lzyllll/bqyx/bqyx_bot/data/bqyx_bot/bqyx.db')
check('/home/lzyllll/bqyx/astrbot/data/plugins/astrbot_plugin_bqyx/data/bqyx.db')
