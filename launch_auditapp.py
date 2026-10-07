"""Start AuditApp as a local Streamlit server (PyInstaller entry point)."""

from __future__ import annotations

import os
import socket
import sys
import traceback
import webbrowser


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def main() -> int:
    os.environ["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
    os.environ["STREAMLIT_SERVER_HEADLESS"] = "true"
    os.environ["STREAMLIT_GLOBAL_DEVELOPMENT_MODE"] = "false"
    os.environ["STREAMLIT_SERVER_FILE_WATCHER_TYPE"] = "none"

    import app_paths

    app_dir = app_paths.bundle_dir()
    os.chdir(str(app_paths.data_dir()))
    app_paths.ensure_bundled_excels()
    if str(app_dir) not in sys.path:
        sys.path.insert(0, str(app_dir))

    port = _free_port()
    webbrowser.open(f"http://127.0.0.1:{port}")

    from streamlit.web import cli as stcli

    sys.argv = [
        "streamlit",
        "run",
        str(app_dir / "app.py"),
        "--server.headless=true",
        f"--server.port={port}",
        "--server.address=127.0.0.1",
        "--server.fileWatcherType=none",
        "--browser.gatherUsageStats=false",
        "--global.developmentMode=false",
        "--client.toolbarMode=minimal",
    ]
    try:
        return int(stcli.main() or 0)
    except Exception:
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
