"""
Скриншот дашборда Superset для README: docs/dashboard.png.

Работает через headless-браузер на базе Chromium (Edge или Chrome) по протоколу
Chrome DevTools: вход в Superset, ожидание отрисовки всех графиков, снимок,
обрезка пустого места внизу.

Запуск (стенд поднят, дашборд создан):
    python scripts/dashboard_screenshot.py [docs/dashboard.png]
Путь к браузеру можно задать переменной BROWSER_PATH.
Зависимости: requests, websocket-client, Pillow, numpy.
"""
import base64, json, os, re, shutil, subprocess, sys, tempfile, time

import numpy as np
import requests
import websocket
from PIL import Image

CANDIDATES = [
    os.environ.get("BROWSER_PATH", ""),
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    shutil.which("chromium") or "", shutil.which("google-chrome") or "",
]
EDGE = next((p for p in CANDIDATES if p and os.path.exists(p)), None) or sys.exit("Не найден Edge/Chrome: задайте BROWSER_PATH")
BASE = os.environ.get("SUPERSET_URL", "http://localhost:8088")
USER = os.environ.get("SUPERSET_ADMIN_USER", "admin")
PASSWORD = os.environ.get("SUPERSET_ADMIN_PASSWORD", "admin")
URL = f"{BASE}/superset/dashboard/oil-production/?standalone=1&expand_filters=0"
OUT = sys.argv[1] if len(sys.argv) > 1 else "docs/dashboard.png"
WIDTH = 1400

# 1. Вход в Superset через форму — получаем cookie сессии
s = requests.Session()
html = s.get(f"{BASE}/login/").text
csrf = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html) or re.search(r'value="([^"]+)"[^>]*name="csrf_token"', html)
r = s.post(f"{BASE}/login/", data={"username": USER, "password": PASSWORD, "csrf_token": csrf.group(1)})
session_cookie = s.cookies.get("session")
assert session_cookie, "нет cookie сессии"
print("вход в Superset: OK")

# 2. Edge в фоновом режиме с временным профилем
profile = tempfile.mkdtemp(prefix="edge-shot-")
edge = subprocess.Popen([EDGE, "--headless=new", "--remote-debugging-port=9333", f"--user-data-dir={profile}",
                         "--disable-gpu", "--hide-scrollbars", f"--window-size={WIDTH},2000", "about:blank"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(50):
        try:
            pages = [p for p in requests.get("http://127.0.0.1:9333/json", timeout=2).json() if p["type"] == "page"]
            if pages: break
        except Exception: pass
        time.sleep(0.2)
    ws = websocket.create_connection(pages[0]["webSocketDebuggerUrl"], timeout=60, suppress_origin=True)
    msg_id = 0
    def cdp(method, **params):
        global msg_id
        msg_id += 1
        ws.send(json.dumps({"id": msg_id, "method": method, "params": params}))
        while True:
            m = json.loads(ws.recv())
            if m.get("id") == msg_id:
                if "error" in m: raise RuntimeError(m["error"])
                return m.get("result", {})

    cdp("Network.enable")
    cdp("Network.setCookie", name="session", value=session_cookie, domain="localhost", path="/")
    cdp("Emulation.setDeviceMetricsOverride", width=WIDTH, height=2000, deviceScaleFactor=1.5, mobile=False)
    cdp("Page.enable")
    cdp("Page.navigate", url=URL)

    # 3. Ждём, пока на всех графиках пропадут индикаторы загрузки
    for i in range(90):
        time.sleep(1)
        state = cdp("Runtime.evaluate", returnByValue=True, expression="""
            JSON.stringify({
              canvases: document.querySelectorAll('canvas').length,
              tables: document.querySelectorAll('table').length,
              markdown: document.querySelectorAll('.dashboard-markdown, .markdown-container').length,
              errors: [...document.querySelectorAll('[role="alert"]')].map(e => e.innerText.slice(0, 120))
            })""")["result"]["value"]
        st = json.loads(state)
        # 3 KPI-тренда + 4 графика ECharts = 7 холстов, плюс таблица эффекта ГТМ
        if st["canvases"] >= 7 and st["tables"] >= 1:
            break
    print("состояние страницы:", st)
    time.sleep(2)  # анимации ECharts
    height = cdp("Runtime.evaluate", returnByValue=True,
                 expression="Math.max(document.body.scrollHeight, document.documentElement.scrollHeight)")["result"]["value"]
    shot = cdp("Page.captureScreenshot", format="png", captureBeyondViewport=False,
               clip={"x": 0, "y": 0, "width": WIDTH, "height": min(height, 4000), "scale": 1})
    open(OUT, "wb").write(base64.b64decode(shot["data"]))

    # Обрезаем пустой фон под последним графиком
    im = Image.open(OUT).convert("RGB")
    a = np.asarray(im).astype(int)
    bg = a[-5, a.shape[1] // 2]
    rows = np.where((np.abs(a[:, 100:-100] - bg).sum(axis=2) > 30).any(axis=1))[0]
    im.crop((0, 0, im.width, min(a.shape[0], rows.max() + 40))).save(OUT, optimize=True)
    print(f"сохранено: {OUT}, {im.width}x{min(a.shape[0], rows.max() + 40)}")
finally:
    edge.terminate()
