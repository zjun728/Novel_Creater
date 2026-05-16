"""选题雷达：市场抓取与趋势分析"""
import re
import asyncio
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from database import fetchone, fetchall, execute
from .helpers import convert_row, convert_rows, to_snake
import uuid, time, json

router = APIRouter(tags=["market"])

# 搜索 User-Agent
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'
}

# ---- Pydantic 模型 ----

class MarketItemCreate(BaseModel):
    title: str = ""
    platform: str = ""
    category: str = ""
    author: str = ""
    tags: Optional[list] = None
    rankName: str = ""
    rankPosition: int = 0
    intro: str = ""
    wordCount: int = 0
    status: str = "unknown"
    heatText: str = ""
    url: str = ""
    projectId: str = ""
    aiSummary: str = ""
    extractedHooks: Optional[list] = None
    extractedAppeals: Optional[list] = None
    plagiarismRiskNotes: str = ""

class MarketItemUpdate(BaseModel):
    title: Optional[str] = None
    platform: Optional[str] = None
    category: Optional[str] = None
    author: Optional[str] = None
    tags: Optional[list] = None
    rankName: Optional[str] = None
    rankPosition: Optional[int] = None
    intro: Optional[str] = None
    wordCount: Optional[int] = None
    status: Optional[str] = None
    heatText: Optional[str] = None
    url: Optional[str] = None
    aiSummary: Optional[str] = None
    extractedHooks: Optional[list] = None
    extractedAppeals: Optional[list] = None
    plagiarismRiskNotes: Optional[str] = None

class ScrapeRequest(BaseModel):
    keywords: str = "热门小说"
    projectId: str = ""

# ---- 页面内容提取 ----

def extract_page_info(html_text: str, url: str) -> dict:
    """从可读页面中提取小说元数据"""
    info = {"title": "", "author": "", "category": "", "intro": ""}

    # 书名：尝试 h1，其次 <title>
    title_m = re.search(r'<h1[^>]*>(.*?)</h1>', html_text, re.DOTALL)
    if title_m:
        info["title"] = re.sub(r'<[^>]+>', '', title_m.group(1)).strip()[:300]
    if not info["title"]:
        title_m = re.search(r'<title>(.*?)</title>', html_text)
        if title_m:
            raw = re.sub(r'<[^>]+>', '', title_m.group(1)).strip()
            raw = re.split(r'[|_\-—·]', raw)[0].strip()
            info["title"] = raw[:300]

    # 作者：匹配常见模式
    author_m = re.search(r'(?:作者|著者|作者：|著者：)\s*[：:]*\s*([^<\n]{2,30})', html_text)
    if author_m:
        info["author"] = author_m.group(1).strip()

    # 分类：匹配标签/分类模式
    cat_m = re.search(r'(?:分类|类型|题材|标签)[：:]\s*([^<\n]{2,20})', html_text)
    if cat_m:
        info["category"] = cat_m.group(1).strip()

    # 简介：优先 meta description，其次第一个长段落
    desc_m = re.search(r'<meta[^>]+name="description"[^>]+content="([^"]+)"', html_text)
    if desc_m:
        info["intro"] = desc_m.group(1).strip()[:500]
    else:
        for p_m in re.finditer(r'<p[^>]*>(.{50,})</p>', html_text, re.DOTALL):
            text = re.sub(r'<[^>]+>', '', p_m.group(1)).strip()
            if len(text) > 40:
                info["intro"] = text[:500]
                break

    # 平台：从 URL 提取
    domain_m = re.search(r'https?://(?:www\.)?([^/]+)', url)
    if domain_m:
        info["platform"] = domain_m.group(1)

    return info


async def search_and_fetch(keywords: str) -> list:
    """从已知可读平台获取热门小说数据"""
    import httpx

    items = []
    # 已知可读的排行榜页面（此前实测验证）
    KNOWN_RANK_PAGES = [
        {"url": "https://www.shuqi.com/rank", "platform": "shuqi.com", "name": "书旗小说"},
        {"url": "https://www.zongheng.com/rank.html", "platform": "zongheng.com", "name": "纵横中文网"},
        {"url": "https://www.xxsy.net/rank", "platform": "xxsy.net", "name": "潇湘书院"},
        {"url": "https://www.52shuku.net/Top/", "platform": "52shuku.net", "name": "52书库"},
        {"url": "https://m.readnovel.com/rank?tab=rank-7&type=7", "platform": "readnovel.com", "name": "小说阅读网"},
    ]

    async def fetch_rank_page(client, page_info):
        """抓取单个排行榜页面并解析小说条目"""
        try:
            resp = await client.get(page_info["url"], timeout=10.0)
            if resp.status_code != 200:
                return []
            html = resp.text
            page_items = []

            # 方式1：《书名》格式
            novels = re.findall(
                r'《([^》]{2,40})》\s*(?:[-_/——\-–·]\s*|\s*(?:作者|著)[：:]\s*)([^\s<]{2,20})',
                html
            )
            if novels:
                for idx, (title, author) in enumerate(novels[:20]):
                    page_items.append({
                        "title": title.strip(),
                        "author": author.strip(),
                        "platform": page_info["platform"],
                        "rankPosition": idx + 1,
                        "rankName": page_info["name"],
                    })
            else:
                # 方式2：链接格式
                entries = re.findall(
                    r'<a[^>]*href="[^"]*"[^>]*>([^<]{2,40})</a>.*?(?:作者[：:]?\s*([^<\n]{2,20}))?',
                    html, re.DOTALL
                )
                seen = set()
                for title, author in entries[:20]:
                    title = title.strip()
                    if title and len(title) >= 2 and title not in seen:
                        seen.add(title)
                        page_items.append({
                            "title": title,
                            "author": author.strip() if author else "",
                            "platform": page_info["platform"],
                            "rankPosition": 0,
                            "rankName": page_info["name"],
                        })

            # 补充简介、分类等信息
            info = extract_page_info(html, page_info["url"])
            for item in page_items[:15]:
                if info.get("intro"):
                    item["intro"] = info["intro"]
                if info.get("category"):
                    item["category"] = info["category"]

            return page_items
        except Exception:
            return []

    try:
        async with httpx.AsyncClient(headers=HEADERS, timeout=15.0, follow_redirects=True) as client:
            tasks = [fetch_rank_page(client, page) for page in KNOWN_RANK_PAGES]
            results = await asyncio.gather(*tasks)

            for page_items in results:
                if page_items:
                    for item in page_items:
                        items.append({
                            "id": str(uuid.uuid4()),
                            "title": item.get("title", ""),
                            "author": item.get("author", ""),
                            "platform": item.get("platform", ""),
                            "category": item.get("category", ""),
                            "intro": item.get("intro", ""),
                            "url": item.get("url", ""),
                            "capturedAt": int(time.time() * 1000),
                            "status": "unknown",
                            "tags": [],
                            "rankName": item.get("rankName", ""),
                            "rankPosition": item.get("rankPosition", 0),
                            "heatText": "",
                            "wordCount": 0,
                            "aiSummary": "",
                            "extractedHooks": None,
                            "extractedAppeals": None,
                            "plagiarismRiskNotes": "",
                        })

    except Exception:
        pass

    return items[:100]

# ---- API 端点 ----

@router.post("/market/scrape")
async def scrape_market(data: ScrapeRequest):
    """触发市场抓取：搜索 + 页面读取 + 入库"""
    if not data.keywords.strip():
        raise HTTPException(400, "关键词不能为空")
    if not data.projectId.strip():
        raise HTTPException(400, "项目ID不能为空")

    items = await search_and_fetch(data.keywords.strip())

    if not items:
        return {"count": 0, "items": [], "message": "未找到可读取的结果，请尝试其他关键词"}

    pid = data.projectId
    saved = []
    for item in items:
        try:
            await execute(
                """INSERT INTO market_items (id, project_id, platform, category, title, author,
                   tags, rank_name, rank_position, intro, word_count, status, heat_text, url,
                   captured_at, ai_summary, extracted_hooks, extracted_appeals, plagiarism_risk_notes)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    item["id"], pid, item["platform"], item["category"], item["title"],
                    item["author"], json.dumps(item["tags"]), item["rankName"], item["rankPosition"],
                    item["intro"], item["wordCount"], item["status"], item["heatText"], item["url"],
                    item["capturedAt"], item["aiSummary"],
                    json.dumps(item["extractedHooks"]) if item["extractedHooks"] else None,
                    json.dumps(item["extractedAppeals"]) if item["extractedAppeals"] else None,
                    item["plagiarismRiskNotes"],
                ),
            )
            saved.append(item)
        except Exception:
            pass

    return {"count": len(saved), "items": saved}


@router.get("/market/items")
async def list_items(projectId: str = ""):
    """列出 market items，可按 projectId 筛选"""
    if projectId:
        rows = await fetchall(
            "SELECT * FROM market_items WHERE project_id=%s ORDER BY captured_at DESC",
            (projectId,)
        )
    else:
        rows = await fetchall("SELECT * FROM market_items ORDER BY captured_at DESC")
    return convert_rows(rows)


@router.post("/market/items")
async def create_item(data: MarketItemCreate):
    """手动创建 market item"""
    now = int(time.time() * 1000)
    mid = str(uuid.uuid4())
    await execute(
        """INSERT INTO market_items (id, project_id, platform, category, title, author,
           tags, rank_name, rank_position, intro, word_count, status, heat_text, url,
           captured_at, ai_summary, extracted_hooks, extracted_appeals, plagiarism_risk_notes)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (
            mid, data.projectId, data.platform, data.category, data.title,
            data.author, json.dumps(data.tags) if data.tags else None,
            data.rankName, data.rankPosition, data.intro, data.wordCount,
            data.status, data.heatText, data.url, now, data.aiSummary,
            json.dumps(data.extractedHooks) if data.extractedHooks else None,
            json.dumps(data.extractedAppeals) if data.extractedAppeals else None,
            data.plagiarismRiskNotes,
        ),
    )
    return convert_row(await fetchone("SELECT * FROM market_items WHERE id=%s", (mid,)))


@router.put("/market/items/{mid}")
async def update_item(mid: str, data: MarketItemUpdate):
    """更新 market item（用于存储 AI 分析结果）"""
    sets, args = [], []
    for k, v in data.dict(exclude_none=True).items():
        col = to_snake(k)
        if isinstance(v, list):
            sets.append(f"{col}=%s")
            args.append(json.dumps(v))
        else:
            sets.append(f"{col}=%s")
            args.append(v)
    if not sets:
        return convert_row(await fetchone("SELECT * FROM market_items WHERE id=%s", (mid,)))
    args.append(mid)
    await execute(f"UPDATE market_items SET {', '.join(sets)} WHERE id=%s", args)
    return convert_row(await fetchone("SELECT * FROM market_items WHERE id=%s", (mid,)))


@router.delete("/market/items/{mid}")
async def delete_item(mid: str):
    """删除 market item"""
    await execute("DELETE FROM market_items WHERE id=%s", (mid,))
    return {"ok": True}
