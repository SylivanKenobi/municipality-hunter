import argparse
import logging

from .config import Settings
from .db import apply_schema, get_connection, get_state, set_state
from .municipalities import load_municipalities, municipalities_loaded, source_versions
from .sync import run_sync, run_sync_loop


def init(settings, force):
    conn = get_connection(settings)
    try:
        apply_schema(conn)
        versions = source_versions()
        if force or not municipalities_loaded(conn) or get_state(conn, "municipality_sources") != versions:
            load_municipalities(conn)
            set_state(conn, "municipality_sources", versions)
        else:
            logging.info("Municipalities are up to date (use --force to reload)")
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(prog="municipality_hunter")
    commands = parser.add_subparsers(dest="command", required=True)

    init_cmd = commands.add_parser("init", help="create the schema and load the municipality boundaries")
    init_cmd.add_argument("--force", action="store_true", help="reload the boundaries even if already loaded")

    sync_cmd = commands.add_parser("sync", help="fetch activities from Strava and compute visited municipalities")
    sync_cmd.add_argument("--loop", action="store_true", help="keep running every SYNC_INTERVAL_SECONDS")

    web_cmd = commands.add_parser("web", help="run the map in the Flask development server")
    web_cmd.add_argument("--host", default="127.0.0.1")
    web_cmd.add_argument("--port", type=int, default=5001)

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = Settings.from_env()

    if args.command == "init":
        init(settings, args.force)
    elif args.command == "sync":
        (run_sync_loop if args.loop else run_sync)(settings)
    elif args.command == "web":
        from .web import app
        app.run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
