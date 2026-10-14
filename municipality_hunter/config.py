import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str
    client_id: str
    client_secret: str
    refresh_token: str
    sync_interval_seconds: int
    max_segment_meters: float

    @classmethod
    def from_env(cls):
        env = os.environ
        return cls(
            db_host=env.get("DB_HOST", "localhost"),
            db_port=int(env.get("DB_PORT", "5432")),
            db_name=env.get("DB_NAME", "postgres"),
            db_user=env.get("DB_USER", "postgres"),
            db_password=env.get("DB_PASSWORD", ""),
            client_id=env.get("CLIENT_ID", ""),
            client_secret=env.get("CLIENT_SECRET", ""),
            refresh_token=env.get("REFRESH_TOKEN", ""),
            sync_interval_seconds=int(env.get("SYNC_INTERVAL_SECONDS", "3600")),
            # Segments longer than this are treated as GPS jumps: only their
            # end points count towards visited municipalities.
            max_segment_meters=float(env.get("MAX_SEGMENT_METERS", "500")),
        )
