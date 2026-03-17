from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
SCREENSHOT_DIR = ROOT / "软著申请材料_拆分版" / "运行截图"
PORT = 8502
URL = f"http://127.0.0.1:{PORT}"


def wait_for_server(timeout: float = 30.0) -> None:
    import urllib.request

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(URL, timeout=2) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("Streamlit 服务启动超时。")


def start_server() -> subprocess.Popen[str]:
    command = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        "streamlit_app.py",
        "--server.headless",
        "true",
        "--server.port",
        str(PORT),
        "--browser.gatherUsageStats",
        "false",
    ]
    return subprocess.Popen(
        command,
        cwd=str(ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )


def capture() -> list[Path]:
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            headless=True,
        )
        page = browser.new_page(viewport={"width": 1480, "height": 2200}, device_scale_factor=1)
        page.goto(URL, wait_until="networkidle", timeout=60000)
        page.get_by_text("松辽流域河道变迁与植被响应原型系统", exact=True).wait_for(timeout=20000)
        page.wait_for_timeout(1200)

        page.screenshot(path=str(SCREENSHOT_DIR / "01_首页参数区.png"), full_page=True)
        paths.append(SCREENSHOT_DIR / "01_首页参数区.png")

        analyze_button = page.get_by_role("button", name="开始分析")
        analyze_button.click()
        page.get_by_text("河道指标表", exact=True).wait_for(timeout=60000)
        page.wait_for_timeout(1200)

        page.screenshot(path=str(SCREENSHOT_DIR / "02_河道变化页.png"), full_page=True)
        paths.append(SCREENSHOT_DIR / "02_河道变化页.png")

        for label, filename in [
            ("植被响应", "03_植被响应页.png"),
            ("驱动评估", "04_驱动评估页.png"),
            ("报告导出", "05_报告导出页.png"),
        ]:
            try:
                page.get_by_text(label, exact=True).click()
                page.wait_for_timeout(1200)
                page.screenshot(path=str(SCREENSHOT_DIR / filename), full_page=True)
                paths.append(SCREENSHOT_DIR / filename)
            except PlaywrightTimeoutError:
                pass

        browser.close()

    return paths


def main() -> None:
    process = start_server()
    try:
        wait_for_server()
        capture()
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


if __name__ == "__main__":
    main()
