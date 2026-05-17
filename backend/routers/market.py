"""选题雷达：市场抓取与趋势分析"""
import re
import asyncio
import html as html_lib
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from database import fetchone, fetchall, execute
from .helpers import convert_row, convert_rows, to_snake
import uuid, time, json
from urllib.parse import urljoin, quote_plus, urlparse, parse_qs, unquote
import base64
import xml.etree.ElementTree as ET

router = APIRouter(tags=["market"])

# 搜索 User-Agent
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.7',
}

KNOWN_RANK_PAGES = [
    {
        "url": "https://www.zongheng.com/rank.html",
        "platform": "纵横中文网",
        "domain": "zongheng.com",
        "rankName": "纵横榜单",
        "hrefPatterns": ["/detail/"],
    },
    {
        "url": "https://www.xxsy.net/rank",
        "platform": "潇湘书院",
        "domain": "xxsy.net",
        "rankName": "潇湘榜单",
        "hrefPatterns": ["/book/"],
    },
    {
        "url": "https://m.readnovel.com/rank?tab=rank-7&type=7",
        "platform": "小说阅读网",
        "domain": "readnovel.com",
        "rankName": "小说阅读网榜单",
        "hrefPatterns": ["/book/"],
    },
    {
        "url": "https://www.52shuku.net/Top/",
        "platform": "52书库",
        "domain": "52shuku.net",
        "rankName": "52书库榜单",
        "hrefPatterns": [".html"],
    },
]

WEB_SEARCH_SOURCES = [
    {"label": "综合 Web", "query": "{keywords} 小说 热门 题材 榜单"},
    {"label": "夸克小说", "query": "夸克小说 {keywords} 热门 小说"},
    {"label": "UC小说", "query": "UC小说 {keywords} 热门 小说"},
    {"label": "七猫小说", "query": "七猫小说 {keywords} 热门 小说"},
    {"label": "番茄小说", "query": "番茄小说 {keywords} 热门 小说"},
    {"label": "起点小说", "query": "起点小说 {keywords} 热门 小说"},
]

NAV_TEXTS = {
    "首页", "网站首页", "登录", "注册", "分类", "排行榜", "榜单", "书架", "我的书架",
    "账户", "福利", "完本", "作者", "作者大全", "作家助手", "帮助中心", "阅读记录",
    "书单推荐", "百科", "男生频道", "女生频道", "改编频道", "返回", "更多",
}

RANK_TEXT_PARTS = (
    "月票榜", "畅销榜", "新书榜", "点击榜", "推荐榜", "捧场榜", "完结榜",
    "更新榜", "收藏榜", "风云榜", "人气榜", "点赞", "Top100", "频道", "Microsoft Rewards",
)

GENRE_KEYWORDS = [
    "玄幻", "奇幻", "仙侠", "修真", "都市", "历史", "穿越", "重生", "言情", "悬疑",
    "灵异", "科幻", "末世", "游戏", "竞技", "轻小说", "武侠", "种田", "宫斗", "权谋",
]

SOURCE_MATCH_KEYWORDS = {
    "夸克小说": ["夸克小说", "quark"],
    "UC小说": ["UC小说", "uc小说", "xiaoshuo.uc", "uc.cn"],
    "七猫小说": ["七猫小说", "七猫", "qimao"],
    "番茄小说": ["番茄小说", "fanqienovel"],
    "起点小说": ["起点小说", "起点中文网", "qidian"],
}

FALLBACK_MARKET_ITEMS = [
    {
        "title": "废土拾荒者的星舰日志",
        "author": "本地趋势样本",
        "category": "科幻末世",
        "intro": "底层拾荒少年捡到失控星舰核心，在资源枯竭的废土上建立移动城邦，同时被旧帝国遗留 AI 与财阀猎队追捕。",
        "tags": ["废土", "AI遗产", "基地建设", "升级流"],
    },
    {
        "title": "被退婚后我接管了边关军府",
        "author": "本地趋势样本",
        "category": "历史权谋",
        "intro": "女主被京城退婚后远赴边关，接手濒临崩盘的军府，以商路、军功和人心重建家族权柄。",
        "tags": ["大女主", "权谋", "边关", "经营"],
    },
    {
        "title": "修真界最后一个产品经理",
        "author": "本地趋势样本",
        "category": "修真脑洞",
        "intro": "穿越者不会炼丹也不会御剑，却发现宗门任务、功法迭代和秘境探索都能用产品思维重构。",
        "tags": ["修真", "穿越", "系统化", "轻喜剧"],
    },
    {
        "title": "长安诡案录：夜巡司",
        "author": "本地趋势样本",
        "category": "悬疑历史",
        "intro": "夜巡司小吏在连环异象中追查权贵秘案，每个案件都牵出盛世背后的制度裂缝和旧案血债。",
        "tags": ["悬疑", "探案", "历史", "群像"],
    },
    {
        "title": "全民领主：我把怪物做成产业链",
        "author": "本地趋势样本",
        "category": "游戏竞技",
        "intro": "全民降临领主战场，主角没有神级兵种，却靠捕捉、驯化和加工怪物资源滚雪球。",
        "tags": ["领主流", "经营", "游戏", "爽文"],
    },
]

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

def decode_response_text(resp) -> str:
    """尽量正确解码中文页面，避免 GBK 站点出现乱码。"""
    content = resp.content
    candidates = []
    if resp.encoding:
        candidates.append(resp.encoding)
    candidates.extend(["utf-8", "gb18030", "gbk"])

    best_text = ""
    best_score = -10**9
    for enc in dict.fromkeys(candidates):
        try:
            text = content.decode(enc, errors="replace")
        except Exception:
            continue
        chinese_count = len(re.findall(r"[\u4e00-\u9fff]", text))
        bad_count = text.count("�")
        mojibake_count = sum(text.count(ch) for ch in ("å", "æ", "ä", "ç", "è", "é"))
        score = chinese_count - bad_count * 10 - mojibake_count * 2
        if score > best_score:
            best_score = score
            best_text = text
    return best_text or resp.text


def clean_lines(fragment: str) -> list[str]:
    text = re.sub(r"<script[\s\S]*?</script>", "\n", fragment, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "\n", text)
    text = html_lib.unescape(text)
    text = text.replace("\xa0", " ")
    lines = []
    for line in text.splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            lines.append(line)
    return lines


def compact_text(fragment: str) -> str:
    return re.sub(r"\s+", " ", " ".join(clean_lines(fragment))).strip()


def has_private_use_chars(text: str) -> bool:
    return bool(re.search(r"[\ue000-\uf8ff]", text or ""))


def is_probable_novel_title(text: str) -> bool:
    text = (text or "").strip()
    if not (2 <= len(text) <= 40):
        return False
    if has_private_use_chars(text):
        return False
    if not re.search(r"[\u4e00-\u9fff]", text):
        return False
    if text in NAV_TEXTS:
        return False
    if any(part in text for part in RANK_TEXT_PARTS):
        return False
    if re.fullmatch(r"[\d\s./万]+", text):
        return False
    return True


def infer_category(*texts: str) -> str:
    joined = " ".join(t for t in texts if t)
    for genre in GENRE_KEYWORDS:
        if genre in joined:
            return genre
    return ""


def normalize_url(base_url: str, href: str) -> str:
    href = html_lib.unescape((href or "").strip())
    if href.startswith("//"):
        return "https:" + href
    return urljoin(base_url, href)


def extract_domain(url: str) -> str:
    try:
        domain = urlparse(url).netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]
        return domain
    except Exception:
        return ""


def clean_html_text(fragment: str) -> str:
    text = re.sub(r"<script[\s\S]*?</script>", " ", fragment or "", flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_lib.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def resolve_bing_url(url: str) -> str:
    """Bing 有时会返回 /ck/a 包装链接，尽量还原真实 URL。"""
    url = html_lib.unescape(url or "").strip()
    if not url:
        return ""
    parsed = urlparse(url)
    if "bing.com" not in parsed.netloc or "/ck/" not in parsed.path:
        return url

    raw = parse_qs(parsed.query).get("u", [""])[0]
    if not raw:
        return url
    try:
        decoded = unquote(raw)
        if decoded.startswith("a1"):
            payload = decoded[2:]
            padding = "=" * (-len(payload) % 4)
            return base64.urlsafe_b64decode(payload + padding).decode("utf-8", errors="ignore")
        return decoded
    except Exception:
        return url


def is_useful_search_result(title: str, url: str, snippet: str, source_label: str = "") -> bool:
    text = f"{title} {snippet}".strip()
    domain = extract_domain(url)
    if not title or len(title) < 2:
        return False
    if "bing.com" in domain or "microsoft" in domain:
        return False
    if any(part in text for part in ("Microsoft Rewards", "下载", "官网", "浏览器官方下载")):
        return False
    if source_label and source_label != "综合 Web":
        source_keys = SOURCE_MATCH_KEYWORDS.get(source_label, [source_label])
        haystack = f"{text} {domain}".lower()
        if not any(key.lower() in haystack for key in source_keys):
            return False
        if "小说" not in text and not any(domain_key in domain for domain_key in ("qidian", "fanqienovel", "qimao", "readnovel")):
            return False
    if not any(word in text for word in ("小说", "网文", "榜", "排行", "热门", "题材", "书", "阅读")):
        return False
    return True


def parse_book_anchor(body: str, page_info: dict) -> dict:
    lines = clean_lines(body)
    text = compact_text(body)
    title = ""
    intro = ""
    author = ""
    category = ""
    heat_text = ""

    for idx, line in enumerate(lines):
        if is_probable_novel_title(line):
            title = line
            following = lines[idx + 1: idx + 6]
            intro = next((x for x in following if len(x) >= 30 and not has_private_use_chars(x)), "")
            category = next((x for x in following if infer_category(x) == x or infer_category(x)), "")
            author = next((x for x in following if 2 <= len(x) <= 16 and x != category and not re.search(r"\d", x)), "")
            heat_text = next((x for x in following if re.search(r"\d", x) and ("万" in x or "热度" in x or "字" in x)), "")
            break

    if not title and is_probable_novel_title(text):
        title = text

    return {
        "title": title,
        "author": author,
        "category": infer_category(category, text),
        "intro": intro,
        "heatText": heat_text,
    }


def parse_anchor_items(html_text: str, page_info: dict) -> list[dict]:
    page_items = []
    seen_titles = set()
    href_patterns = page_info.get("hrefPatterns", [])

    for match in re.finditer(r"<a[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", html_text, re.I | re.S):
        href = html_lib.unescape(match.group(1).strip())
        if href.startswith("javascript:"):
            continue
        if href_patterns and not any(pattern in href for pattern in href_patterns):
            continue

        parsed = parse_book_anchor(match.group(2), page_info)
        title = parsed.get("title", "").strip()
        if not is_probable_novel_title(title):
            continue
        if title in seen_titles:
            continue
        seen_titles.add(title)

        item_url = normalize_url(page_info["url"], href)
        page_items.append({
            "title": title,
            "author": parsed.get("author", ""),
            "platform": page_info["platform"],
            "category": parsed.get("category", ""),
            "intro": parsed.get("intro", ""),
            "url": item_url,
            "rankPosition": len(page_items) + 1,
            "rankName": page_info["rankName"],
            "heatText": parsed.get("heatText", ""),
            "tags": [],
        })
        if len(page_items) >= 25:
            break

    return page_items


def parse_bracket_items(html_text: str, page_info: dict) -> list[dict]:
    page_items = []
    seen_titles = set()
    for title in re.findall(r"《([^》]{2,40})》", html_text):
        title = html_lib.unescape(title).strip()
        if not is_probable_novel_title(title) or title in seen_titles:
            continue
        seen_titles.add(title)
        page_items.append({
            "title": title,
            "author": "",
            "platform": page_info["platform"],
            "category": infer_category(title),
            "intro": "",
            "url": page_info["url"],
            "rankPosition": len(page_items) + 1,
            "rankName": page_info["rankName"],
            "heatText": "",
            "tags": [],
        })
        if len(page_items) >= 20:
            break
    return page_items


def parse_bing_results(html_text: str, source_label: str, query: str) -> list[dict]:
    results = []
    seen_urls = set()

    def add_result(url: str, title: str, snippet: str):
        url = resolve_bing_url(url)
        title = clean_html_text(title)
        snippet = clean_html_text(snippet)

        if not is_useful_search_result(title, url, snippet, source_label):
            return
        if url in seen_urls:
            return
        seen_urls.add(url)

        domain = extract_domain(url)
        category = infer_category(query, title, snippet)
        results.append({
            "title": title[:300],
            "author": "",
            "platform": source_label if source_label != "综合 Web" else (domain or "Web Search"),
            "category": category,
            "intro": snippet[:500],
            "url": url,
            "rankPosition": len(results) + 1,
            "rankName": f"Web Search：{source_label}",
            "heatText": domain,
            "tags": [tag for tag in ["Web Search", source_label, category] if tag],
        })

    for match in re.finditer(
        r"<li[^>]+class=[\"'][^\"']*\bb_algo\b[^\"']*[\"'][\s\S]*?<h2[^>]*>\s*<a[^>]*href=[\"']([^\"']+)[\"'][^>]*>([\s\S]*?)</a>([\s\S]*?)(?=<li[^>]+class=[\"'][^\"']*\bb_algo\b|</ol>|$)",
        html_text,
        re.I,
    ):
        body = match.group(3)
        snippet_match = re.search(r"<p[^>]*>([\s\S]*?)</p>", body, re.I)
        add_result(match.group(1), match.group(2), snippet_match.group(1) if snippet_match else "")
        if len(results) >= 10:
            break

    # Bing 在某些地区返回精简结构，没有 b_algo 容器，只保留 h2 链接。
    if len(results) < 3:
        for match in re.finditer(
            r"<h2[^>]*>\s*<a[^>]*href=[\"']([^\"']+)[\"'][^>]*>([\s\S]*?)</a>\s*</h2>([\s\S]{0,800})",
            html_text,
            re.I,
        ):
            body = match.group(3)
            snippet_match = re.search(r"<p[^>]*>([\s\S]*?)</p>", body, re.I)
            add_result(match.group(1), match.group(2), snippet_match.group(1) if snippet_match else "")
            if len(results) >= 10:
                break

    return results


def parse_bing_rss(xml_text: str, source_label: str, query: str) -> list[dict]:
    results = []
    seen_urls = set()
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return results

    channel = root.find("channel")
    if channel is None:
        return results

    for item in channel.findall("item"):
        title = clean_html_text(item.findtext("title") or "")
        url = html_lib.unescape(item.findtext("link") or "")
        snippet = clean_html_text(item.findtext("description") or "")
        if not is_useful_search_result(title, url, snippet, source_label):
            continue
        if url in seen_urls:
            continue
        seen_urls.add(url)

        domain = extract_domain(url)
        category = infer_category(query, title, snippet)
        results.append({
            "title": title[:300],
            "author": "",
            "platform": source_label if source_label != "综合 Web" else (domain or "Web Search"),
            "category": category,
            "intro": snippet[:500],
            "url": url,
            "rankPosition": len(results) + 1,
            "rankName": f"Web Search：{source_label}",
            "heatText": domain,
            "tags": [tag for tag in ["Web Search", source_label, category] if tag],
        })
        if len(results) >= 10:
            break

    return results


def make_market_item(raw: dict, keywords: str, fallback: bool = False) -> dict:
    category = raw.get("category") or infer_category(keywords, raw.get("title", ""), raw.get("intro", ""))
    tags = raw.get("tags") or ([category] if category else [])
    return {
        "id": str(uuid.uuid4()),
        "title": raw.get("title", ""),
        "author": raw.get("author", ""),
        "platform": raw.get("platform", ""),
        "category": category,
        "intro": raw.get("intro", ""),
        "url": raw.get("url", ""),
        "capturedAt": int(time.time() * 1000),
        "status": "reference" if fallback else "unknown",
        "tags": tags,
        "rankName": raw.get("rankName", "本地趋势样本" if fallback else ""),
        "rankPosition": raw.get("rankPosition", 0),
        "heatText": raw.get("heatText", ""),
        "wordCount": 0,
        "aiSummary": "",
        "extractedHooks": None,
        "extractedAppeals": None,
        "plagiarismRiskNotes": "实时抓取失败时加载的本地参考样本，不代表当前平台实时排名。" if fallback else "",
    }


def fallback_market_items(keywords: str) -> list[dict]:
    preferred = [item for item in FALLBACK_MARKET_ITEMS if infer_category(keywords, item["category"], item["intro"])]
    source = preferred or FALLBACK_MARKET_ITEMS
    return [
        make_market_item({
            **item,
            "platform": "本地趋势样本",
            "rankName": "抓取失败兜底样本",
            "rankPosition": idx + 1,
            "url": "",
        }, keywords, fallback=True)
        for idx, item in enumerate(source)
    ]


async def search_web_sources(keywords: str) -> tuple[list[dict], list[dict]]:
    """通用 Web Search，多源查找平台页面、榜单文章和题材线索。"""
    import httpx

    diagnostics = []

    async def fetch_search(client, plan):
        query = plan["query"].format(keywords=keywords)
        search_url = f"https://cn.bing.com/search?q={quote_plus(query)}&format=rss&mkt=zh-CN"
        source_status = {
            "platform": f"Web Search：{plan['label']}",
            "url": search_url,
            "ok": False,
            "statusCode": None,
            "count": 0,
            "error": "",
        }
        try:
            resp = await client.get(search_url, timeout=12.0)
            source_status["statusCode"] = resp.status_code
            if resp.status_code != 200:
                source_status["error"] = f"HTTP {resp.status_code}"
                return [], source_status

            html_text = decode_response_text(resp)
            results = parse_bing_rss(html_text, plan["label"], query)
            if not results:
                html_url = f"https://cn.bing.com/search?q={quote_plus(query)}&mkt=zh-CN"
                html_resp = await client.get(html_url, timeout=12.0)
                if html_resp.status_code == 200:
                    results = parse_bing_results(decode_response_text(html_resp), plan["label"], query)
            source_status["ok"] = True
            source_status["count"] = len(results)
            if not results:
                source_status["error"] = "搜索可访问，但未解析到有效结果"
            return results, source_status
        except Exception as e:
            source_status["error"] = str(e)
            return [], source_status

    items = []
    async with httpx.AsyncClient(headers=HEADERS, timeout=15.0, follow_redirects=True) as client:
        tasks = [fetch_search(client, plan) for plan in WEB_SEARCH_SOURCES]
        results = await asyncio.gather(*tasks)

    seen = set()
    for search_items, source_status in results:
        diagnostics.append(source_status)
        for item in search_items:
            key = item.get("url") or f"{item.get('platform')}::{item.get('title')}"
            if item.get("title") and key not in seen:
                seen.add(key)
                items.append(make_market_item(item, keywords))

    return items[:60], diagnostics


async def search_and_fetch(keywords: str) -> tuple[list[dict], list[dict]]:
    """从榜单页 + 多源 Web Search 获取热门小说数据。返回 items 与来源诊断。"""
    import httpx

    diagnostics = []

    async def fetch_rank_page(client, page_info):
        source_status = {
            "platform": page_info["platform"],
            "url": page_info["url"],
            "ok": False,
            "statusCode": None,
            "count": 0,
            "error": "",
        }
        try:
            resp = await client.get(page_info["url"], timeout=12.0)
            source_status["statusCode"] = resp.status_code
            if resp.status_code != 200:
                source_status["error"] = f"HTTP {resp.status_code}"
                return [], source_status

            html_text = decode_response_text(resp)
            page_items = parse_anchor_items(html_text, page_info)
            if not page_items:
                page_items = parse_bracket_items(html_text, page_info)

            source_status["ok"] = True
            source_status["count"] = len(page_items)
            if not page_items:
                source_status["error"] = "页面可访问，但未解析到书籍条目"
            return page_items, source_status
        except Exception as e:
            source_status["error"] = str(e)
            return [], source_status

    items = []
    async with httpx.AsyncClient(headers=HEADERS, timeout=15.0, follow_redirects=True) as client:
        tasks = [fetch_rank_page(client, page) for page in KNOWN_RANK_PAGES]
        results = await asyncio.gather(*tasks)

    seen = set()
    for page_items, source_status in results:
        diagnostics.append(source_status)
        for item in page_items:
            key = (item.get("platform"), item.get("title"))
            if item.get("title") and key not in seen:
                seen.add(key)
                items.append(make_market_item(item, keywords))

    web_items, web_diagnostics = await search_web_sources(keywords)
    diagnostics.extend(web_diagnostics)
    for item in web_items:
        key = item.get("url") or f"{item.get('platform')}::{item.get('title')}"
        if item.get("title") and key not in seen:
            seen.add(key)
            items.append(item)

    return items[:140], diagnostics

# ---- API 端点 ----

@router.post("/market/scrape")
async def scrape_market(data: ScrapeRequest):
    """触发市场抓取：搜索 + 页面读取 + 入库"""
    if not data.keywords.strip():
        raise HTTPException(400, "关键词不能为空")
    if not data.projectId.strip():
        raise HTTPException(400, "项目ID不能为空")

    items, diagnostics = await search_and_fetch(data.keywords.strip())
    fallback = False

    if not items:
        items = fallback_market_items(data.keywords.strip())
        fallback = True

    pid = data.projectId
    saved = []
    save_errors = 0
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
            save_errors += 1

    if fallback:
        message = "实时抓取失败，已加载本地趋势参考样本；这些样本不代表当前平台实时排名。"
    elif saved:
        message = f"成功抓取 {len(saved)} 条热门小说数据"
    else:
        message = "抓取到页面数据，但写入数据库失败，请检查数据库连接或表结构。"

    return {
        "count": len(saved),
        "items": saved,
        "message": message,
        "fallback": fallback,
        "sources": diagnostics,
        "saveErrors": save_errors,
    }


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
