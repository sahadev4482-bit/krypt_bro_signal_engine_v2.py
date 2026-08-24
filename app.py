from backend.app_core import app, scanner_loop, eng, delta_ws
import os, threading

if __name__ == "__main__":
    delta_ws.start()
    threading.Thread(target=scanner_loop, daemon=True).start()
    threading.Thread(target=eng.keep_alive_ping, daemon=True).start()
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
