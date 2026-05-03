import socket
import sys
import os

from app import create_app


app = create_app()


if __name__ == "__main__":
    host = "127.0.0.1"
    port = int(os.environ.get("PORT", "5000"))
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    except Exception:
        pass
    try:
        s.bind((host, port))
    except OSError:
        print(
            f"[GuardStar] Порт {host}:{port} уже занят. Остановите старый сервер и запустите снова."
        )
        sys.exit(1)
    finally:
        try:
            s.close()
        except Exception:
            pass

    # Автоперезапуск при правках `.py` (иначе новые маршруты не подхватятся, пока не остановите процесс).
    # На Windows встроенный `use_reloader=True` часто даёт WinError 10038 при остановке сервера —
    # перезагрузчик только по `set GUARDSTAR_USE_RELOADER=1`. В остальных ОС: выкл. через `GUARDSTAR_NO_RELOADER=1`.
    if sys.platform.startswith("win"):
        use_reloader = os.environ.get("GUARDSTAR_USE_RELOADER", "").lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
    else:
        use_reloader = os.environ.get("GUARDSTAR_NO_RELOADER", "").lower() not in (
            "1",
            "true",
            "yes",
            "on",
        )
    app.run(host=host, port=port, debug=True, use_reloader=use_reloader)
