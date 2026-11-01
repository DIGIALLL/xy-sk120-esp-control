"""XY-SK120 web version: backend + UI in a standalone browser window (Edge/Chrome --app).

Run:    python server.py [--host xy-sk120.local] [--port 8765] [--no-browser] [--keep] [--demo]
No browser needed? Use desktop.py instead.
"""
import argparse
import asyncio
import json
import os
import subprocess
from pathlib import Path

import aiohttp
from aiohttp import web

from core import Controller, DemoController, handle
from i18n import tr, trf

STATIC = Path(__file__).resolve().parent / "static"


async def ws_handler(request):
    ctl = request.app["ctl"]
    ws = web.WebSocketResponse(heartbeat=15)
    await ws.prepare(request)

    async def sink(obj):
        await ws.send_str(json.dumps(obj, ensure_ascii=False))

    await sink(ctl.init_msg())
    ctl.sinks.add(sink)
    try:
        async for msg in ws:
            if msg.type != aiohttp.WSMsgType.TEXT:
                continue
            try:
                await handle(ctl, json.loads(msg.data))
            except Exception as e:
                await ctl.toast(trf("Ошибка команды: {}", e), "err")
    finally:
        ctl.sinks.discard(sink)
    return ws


async def index(request):
    return web.FileResponse(STATIC / "index.html")


def find_browser():
    cands = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    ]
    return next((p for p in cands if os.path.exists(p)), None)


def open_window(url):
    b = find_browser()
    if b:
        subprocess.Popen([b, f"--app={url}", "--window-size=1240,860"])
    else:
        import webbrowser
        webbrowser.open(url)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=None)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--keep", action="store_true", help="keep running after the window is closed")
    ap.add_argument("--demo", action="store_true", help="simulated module, no hardware needed")
    a = ap.parse_args()

    ctl = DemoController(a.host) if a.demo else Controller(a.host)
    ctl.keep = a.keep
    app = web.Application()
    app["ctl"] = ctl
    app.add_routes([web.get("/", index), web.get("/ws", ws_handler), web.static("/static", STATIC)])
    runner = web.AppRunner(app)
    await runner.setup()
    url = f"http://127.0.0.1:{a.port}"
    try:
        await web.TCPSite(runner, "127.0.0.1", a.port).start()
    except OSError:
        if not a.no_browser:       # уже запущен — просто открываем окно
            open_window(url)
        return
    if not a.no_browser:
        open_window(url)
    tasks = [asyncio.create_task(ctl.esp_loop()), asyncio.create_task(ctl.ticker())]
    await ctl.stop.wait()
    for t in tasks:
        t.cancel()
    await runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
