import asyncio
import base64
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
import shutil
from pathlib import Path

import websockets


ROOT = Path("D:/Projects/Novel_Creater")
OUT_DIR = ROOT / "tmp" / "browser_acceptance"
CHROME = Path(os.environ.get(
    "NOVEL_ACCEPTANCE_BROWSER",
    "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
))
DEBUG_PORT = 9223
APP_URL = "http://127.0.0.1:8000/"
API_BASE = "http://127.0.0.1:8000/api"


def api(method, path, body=None):
    data = None
    headers = {"Content-Type": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(f"{API_BASE}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as res:
            text = res.read().decode("utf-8")
            return json.loads(text) if text else None
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed {error.code}: {detail}") from error


def http_json(url):
    with urllib.request.urlopen(url, timeout=5) as res:
        return json.loads(res.read().decode("utf-8"))


def assert_true(condition, message):
    if not condition:
        raise AssertionError(f"ASSERT_FAILED: {message}")


async def wait_for(fn, timeout=10, interval=0.15):
    started = time.time()
    last = None
    while time.time() - started < timeout:
        try:
            value = await fn() if asyncio.iscoroutinefunction(fn) else fn()
            if value:
                return value
            last = value
        except Exception as error:
            last = error
        await asyncio.sleep(interval)
    raise TimeoutError(f"wait_for timeout: {last}")


class CDP:
    def __init__(self, ws):
        self.ws = ws
        self.next_id = 0

    async def call(self, method, params=None):
        self.next_id += 1
        message_id = self.next_id
        await self.ws.send(json.dumps({"id": message_id, "method": method, "params": params or {}}))
        async def recv_response():
            while True:
                raw = await self.ws.recv()
                message = json.loads(raw)
                if message.get("id") != message_id:
                    continue
                if "error" in message:
                    raise RuntimeError(json.dumps(message["error"], ensure_ascii=False))
                return message.get("result")
        try:
            return await asyncio.wait_for(recv_response(), timeout=15)
        except asyncio.TimeoutError as error:
            raise TimeoutError(f"CDP call timeout: {method}") from error

    async def evaluate(self, expression):
        result = await self.call("Runtime.evaluate", {
            "expression": expression,
            "awaitPromise": True,
            "returnByValue": True,
        })
        if result.get("exceptionDetails"):
            raise RuntimeError(result["exceptionDetails"].get("text", "Runtime.evaluate failed"))
        return result.get("result", {}).get("value")

    async def screenshot(self, name):
        result = await self.call("Page.captureScreenshot", {
            "format": "png",
            "captureBeyondViewport": True,
        })
        file_path = OUT_DIR / f"{name}.png"
        file_path.write_bytes(base64.b64decode(result["data"]))
        return str(file_path)


async def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    project_id = ""
    profile_dir = OUT_DIR / f"chrome-profile-{int(time.time() * 1000)}"
    chrome_log = OUT_DIR / "chrome_stderr.log"
    stderr_file = chrome_log.open("wb")
    chrome = subprocess.Popen([
        str(CHROME),
        f"--remote-debugging-port={DEBUG_PORT}",
        f"--user-data-dir={profile_dir}",
        "--headless",
        "--disable-gpu",
        "--disable-gpu-sandbox",
        "--disable-software-rasterizer",
        "--disable-accelerated-2d-canvas",
        "--disable-accelerated-video-decode",
        "--disable-features=VizDisplayCompositor",
        "--disable-dev-shm-usage",
        "--no-first-run",
        "--disable-extensions",
        "--no-sandbox",
        "--single-process",
        "--no-zygote",
        "--window-size=1440,1100",
        APP_URL,
    ], stdout=subprocess.DEVNULL, stderr=stderr_file)

    try:
        print("WAIT_CHROME", flush=True)
        await wait_for(lambda: http_json(f"http://127.0.0.1:{DEBUG_PORT}/json/version"), timeout=10)
        pages = http_json(f"http://127.0.0.1:{DEBUG_PORT}/json/list")
        page = next((item for item in pages if item.get("type") == "page"), pages[0])
        print(f"CONNECT_CDP {page.get('url')}", flush=True)

        async with websockets.connect(page["webSocketDebuggerUrl"], max_size=16 * 1024 * 1024) as ws:
            cdp = CDP(ws)
            print("ENABLE_PAGE", flush=True)
            await cdp.call("Page.enable")
            await cdp.call("Runtime.enable")

            async def click_by_text(text):
                return await cdp.evaluate(f"""(() => {{
                  const all = Array.from(document.querySelectorAll('button, .n-button, [role="button"], .n-tabs-tab'));
                  const el = all.find(node => (node.innerText || node.textContent || '').trim().includes({json.dumps(text)}));
                  if (!el) return false;
                  el.scrollIntoView({{ block: 'center', inline: 'center' }});
                  el.click();
                  return true;
                }})()""")

            async def set_by_placeholder(placeholder, value):
                return await cdp.evaluate(f"""(() => {{
                  const el = Array.from(document.querySelectorAll('input, textarea'))
                    .find(node => (node.getAttribute('placeholder') || '').includes({json.dumps(placeholder)}));
                  if (!el) return false;
                  const desc = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el), 'value');
                  desc.set.call(el, {json.dumps(value)});
                  el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                  el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                  return true;
                }})()""")

            print("NAV_HOME", flush=True)
            await cdp.call("Page.navigate", {"url": APP_URL})
            await wait_for(lambda: cdp.evaluate('document.body && document.body.innerText.includes("项目库")'))
            shots = [await cdp.screenshot("01_home")]
            print("HOME_OK", flush=True)

            title = f"Browser Smoke {int(time.time() * 1000)}"
            assert_true(await click_by_text("新建项目"), "new project button should be clickable")
            await wait_for(lambda: cdp.evaluate('document.body.innerText.includes("新建项目") && document.body.innerText.includes("项目名称")'))
            assert_true(await set_by_placeholder("输入项目名称", title), "title input should be filled")
            assert_true(await set_by_placeholder("如：玄幻、都市、科幻", "都市奇幻"), "genre input should be filled")
            assert_true(await set_by_placeholder("项目简介", "Headless browser acceptance project."), "description input should be filled")
            assert_true(await click_by_text("创建"), "create button should be clickable")
            await wait_for(lambda: cdp.evaluate('location.pathname.includes("/project/")'), timeout=10)
            project_id = await cdp.evaluate('location.pathname.split("/").filter(Boolean).pop()')
            assert_true(project_id, "project id should be present in route")
            shots.append(await cdp.screenshot("02_project_created"))
            print(f"PROJECT_CREATED {project_id}", flush=True)

            seed = api("POST", f"/projects/{project_id}/seeds", {
                "title": "Headless Seed",
                "genre": "urban fantasy",
                "logline": "A student joins an immortal group chat.",
                "protagonist": "Shen Ye",
                "desire": "Confirm the truth.",
                "coreConflict": "Seal dilemma.",
                "worldPressure": "Late-spiritual era.",
                "openingHook": "The phone lights up.",
                "emotionalPromise": "Funny start and warm ending.",
                "differentiation": "Group chat as story backbone.",
                "styleTarget": "Fast webnovel style.",
                "riskNotes": "Avoid filler.",
                "endingAnchor": "Walk into chaos.",
                "source": "headless",
            })
            api("PUT", f"/projects/{project_id}/seeds/{seed['id']}", {"status": "selected"})
            api("PUT", f"/projects/{project_id}/bible", {
                "premise": "A student joins an immortal group chat.",
                "targetReader": "Urban fantasy readers.",
                "styleBible": "Every chat line has a purpose.",
                "themeBible": "Different choices before one dilemma.",
                "worldRules": "The seal dilemma is central.",
                "confirmedSettings": ["Fengyuan bloodline"],
                "forbiddenDirections": ["No pure cheat tool"],
            })
            api("POST", f"/projects/{project_id}/settings/entities", {
                "entityType": "character",
                "name": "Shen Ye",
                "category": "protagonist",
                "summary": "Main character.",
                "importance": 10,
                "tags": ["protagonist"],
            })
            api("POST", f"/projects/{project_id}/volumes", {
                "volumeNum": 1,
                "title": "Entry",
                "startChapter": 1,
                "endChapter": 10,
                "targetWords": 30000,
                "coreGoal": "Enter the group chat",
                "mainConflict": "Reality versus myth",
                "keyCharacters": ["Shen Ye"],
                "summary": "Opening arc.",
                "status": "planned",
            })
            chapter = api("POST", f"/projects/{project_id}/chapters", {"chapterNum": 1, "title": "Chapter 1"})
            api("PUT", f"/projects/{project_id}/chapter-beat-plan/1", {"content": "1. Entry.\n2. Chat.\n3. Anomaly."})
            version = api("POST", f"/projects/{project_id}/chapters/{chapter['id']}/versions", {
                "title": "Candidate",
                "content": "Shen Ye sees the group chat light up on his phone.",
                "versionType": "ai_candidate",
                "promptBrief": "headless",
            })
            api("PUT", f"/projects/{project_id}/chapters/{chapter['id']}", {
                "finalVersionId": version["id"],
                "status": "final",
                "summary": "Shen Ye enters the group chat.",
                "wordCount": 12,
            })
            audit = api("POST", f"/projects/{project_id}/global-audits", {
                "reportType": "global",
                "title": "Headless Audit",
                "report": {
                    "healthScore": 78,
                    "safeToWriteNext": False,
                    "overallVerdict": "Needs one continuity check.",
                    "criticalIssues": [{
                        "type": "continuity",
                        "description": "Title spelling should stay consistent.",
                        "impact": "Continuity risk.",
                        "suggestion": "Use one title spelling.",
                        "severity": "major",
                        "chapterRefs": [1],
                        "relatedItems": ["Shen Ye"],
                    }],
                    "nextActions": ["Fix title spelling"],
                },
            })
            task = api("POST", f"/projects/{project_id}/correction-tasks", {
                "sourceType": "global_audit",
                "sourceId": audit["id"],
                "targetModule": "canon",
                "title": "Unify title spelling",
                "description": "Title spelling should stay consistent.",
                "severity": "major",
                "issueType": "continuity",
                "chapterRefs": [1],
                "relatedItems": ["Shen Ye"],
                "suggestedAction": "Use one spelling.",
                "status": "pending",
                "metadata": {"headless": True},
            })

            await cdp.call("Page.navigate", {"url": f"{APP_URL}project/{project_id}"})
            await wait_for(lambda: cdp.evaluate('document.body.innerText.includes("待处理") || document.body.innerText.includes("Headless Seed")'))
            await asyncio.sleep(0.5)
            workflow_text = await cdp.evaluate("Array.from(document.querySelectorAll('button')).map(b => b.innerText).join('\\n')")
            assert_true("2 种子" in workflow_text and "已就绪" in workflow_text, "seed workflow should be ready")
            assert_true("3 圣经" in workflow_text and "已就绪" in workflow_text, "bible workflow should be ready")
            assert_true("4 设定库" in workflow_text and "已就绪" in workflow_text, "settings workflow should be ready")
            assert_true("5 章节" in workflow_text and "已开始" in workflow_text, "chapter workflow should be started")
            assert_true("6 纠偏" in workflow_text and "待处理" in workflow_text, "correction workflow should be pending")
            shots.append(await cdp.screenshot("03_workflow_ready"))

            for label, wait_text, shot_name in [
                ("2 创作种子", "当前选中的种子", "04_seed_tab"),
                ("3 创作圣经", "项目信息", "05_bible_tab"),
                ("4 设定库", "Shen Ye", "06_settings_tab"),
                ("5 章节管理", "Chapter 1", "07_chapters_tab"),
                ("6 纠偏任务", "纠偏任务板", "08_corrections_pending"),
            ]:
                assert_true(await click_by_text(label), f"{label} click should work")
                await wait_for(lambda text=wait_text: cdp.evaluate(f"document.body.innerText.includes({json.dumps(text)})"))
                shots.append(await cdp.screenshot(shot_name))

            api("PUT", f"/projects/{project_id}/correction-tasks/{task['id']}", {"status": "ignored"})
            await cdp.call("Page.navigate", {"url": f"{APP_URL}project/{project_id}?tab=corrections"})
            await wait_for(lambda: cdp.evaluate('document.body.innerText.includes("纠偏任务板") && document.body.innerText.includes("忽略本次")'))
            after_ignore_text = await cdp.evaluate("document.body.innerText")
            assert_true("当前还有 1 条未完成纠偏任务" not in after_ignore_text, "ignored correction should not show active warning")
            shots.append(await cdp.screenshot("09_corrections_ignored"))

            assert_true(await click_by_text("编辑项目信息"), "project edit button should work")
            await wait_for(lambda: cdp.evaluate('document.body.innerText.includes("目标字数和目标章节数会影响后续章节规划")'))
            disabled_count = await cdp.evaluate("Array.from(document.querySelectorAll('input')).filter(input => input.disabled).length")
            assert_true(disabled_count >= 2, "target words and target chapters should be disabled after content exists")
            shots.append(await cdp.screenshot("10_project_edit_locked"))
            print("BROWSER_ACCEPTANCE_OK", flush=True)

            print(json.dumps({"ok": True, "projectId": project_id, "screenshots": shots}, ensure_ascii=False, indent=2))
    finally:
        if project_id:
            try:
                api("DELETE", f"/projects/{project_id}")
            except Exception as error:
                print(f"cleanup failed for {project_id}: {error}")
        chrome.kill()
        stderr_file.close()
        shutil.rmtree(profile_dir, ignore_errors=True)
        try:
            chrome.wait(timeout=5)
        except subprocess.TimeoutExpired:
            chrome.terminate()


if __name__ == "__main__":
    asyncio.run(main())
