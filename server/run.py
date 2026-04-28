import socket
import sys

from app import create_app


app = create_app()


if __name__ == "__main__":
    host = "127.0.0.1"
    port = 5000
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind((host, port))
    except OSError:
        print(f"[GuardStar] Порт {host}:{port} уже занят. Остановите старый сервер и запустите снова.")
        sys.exit(1)
    finally:
        try:
            s.close()
        except Exception:
            pass

    app.run(host=host, port=port, debug=True, use_reloader=False)
