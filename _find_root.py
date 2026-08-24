from pathlib import Path

base = Path(".venv/Lib/site-packages/ncatbot")
for p in base.rglob("*.py"):
    t = p.read_text(encoding="utf-8", errors="replace")
    if "root" not in t:
        continue
    for i, line in enumerate(t.splitlines(), 1):
        s = line.strip()
        if "root" in s and any(k in s for k in ("self.root", "root:", '"root"', "'root'", "root =", ".root")):
            print(f"{p.relative_to(base)}:{i}:{s}")
