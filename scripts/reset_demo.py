from pathlib import Path

from app.core.config import get_settings


settings = get_settings()
if not settings.database_url.startswith("sqlite:///"):
    raise SystemExit("为避免误删生产数据，reset_demo 只允许用于 SQLite 开发数据库。")

path = Path(settings.database_url.removeprefix("sqlite:///"))
if not path.is_absolute():
    path = Path.cwd() / path

for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
    if candidate.exists():
        candidate.unlink()
        print(f"removed {candidate}")

print("数据库已清空。重新启动应用后将自动生成演示数据。")
