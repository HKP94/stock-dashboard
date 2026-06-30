"""Apply migrations/*.sql to the DB (idempotent). Called by CI workflow steps."""
import glob
import sys
from pathlib import Path

# 스크립트 모드 실행 시 리포 루트를 path에 추가 (src 패키지 인식)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()

from src.db import get_conn  # noqa: E402 — dotenv must load first

files = sys.argv[1:] or sorted(glob.glob("migrations/*.sql"))
if not files:
    print("No migration files found — skipping.")
    sys.exit(0)

with get_conn() as conn:
    for path in files:
        sql = open(path).read()
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
        print(f"OK: {path}")
