# Topic Center Live Market Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing Topic Center a real author workflow that manually refreshes at least five official public novel rankings, shows the works, uses the configured real Provider for discussion, saves candidates, and hands a selected candidate version to an unconfirmed project Seed.

**Architecture:** Keep the existing `MarketSourceService`, immutable snapshot authority, Topic Center aggregates, Provider gateway, and atomic project handoff. Replace synthetic-marker parsing with bounded site-specific official-page adapters, version the built-in source package in place, expose snapshot provenance to the UI, and add one explicit offline v1.13→v1.14 migration for the existing database. Do not add scheduling, browser scraping, a second market store, a second project Seed authority, or Writer Core changes.

**Tech Stack:** Python 3.13, FastAPI, Pydantic v2, httpx, Beautiful Soup 4, aiomysql/MySQL 8.4, Vue 3, Pinia, Naive UI, Node test runner, Playwright.

---

## Scope and execution rules

- Execute on an isolated `codex/` worktree created at implementation time.
- Use TDD for every behavior change and commit after every task.
- Never call a real Provider during Tasks 1–9. Task 10 is the sole real Provider acceptance.
- Live source probes are allowed only in the explicit live-validation steps; unit tests use reduced fixtures with the official DOM shape.
- Do not create another product database. The only product schema operation is the guarded in-place upgrade in Task 10.
- Do not delete, migrate, or rewrite existing project data.
- If fewer than five sources pass the live qualification command, do not run the database upgrade and do not claim completion.

## File responsibility map

### Backend parsing and registry

- `backend/gateways/market_sources/base.py`: bounded HTTP document retrieval, charset handling, page rejection, text and URL normalization.
- `backend/gateways/market_sources/qq_reading_public_rank.py`, `qimao_public_rank.py`, `jjwxc_public_rank.py`, `zongheng_public_rank.py`, `heiyan_public_rank.py`, `readnovel_public_rank.py`, `xxsy_public_rank.py`, `fanqie_public_rank.py`, `seventeen_k_public_rank.py`, and `hongxiu_public_rank.py`: one official-site parsing contract per platform.
- `backend/gateways/market_sources/registry.py`: the only adapter-key-to-instance registry.
- `backend/domain/market.py`: normalized immutable work metadata contract.
- `backend/domain/market_sources.py`: source-package keys, capabilities, and immutable policy values.

### Source package and persistence

- `backend/assets/market-sources-v1.1.0/`: ten-source hash-bound package.
- `backend/services/market_sources.py`: source capability projection and explicit package synchronization.
- `backend/repositories/market.py`: guarded source-definition update and policy-head CAS.
- `backend/services/market_snapshots.py`: immutable refresh publication; no second store.

### API and frontend

- `backend/domain/routers/market_sources.py`: source and snapshot DTOs plus registry wiring.
- `frontend/src/application/market/marketContracts.js`: strict source/snapshot parsing.
- `frontend/src/stores/marketSourceStore.js`: detail loading and last-success preservation.
- `frontend/src/components/topics/MarketDiscoveryPanel.vue`: source list orchestration.
- `frontend/src/components/topics/MarketSnapshotWorks.vue`: actual ranked-work reading surface.
- `frontend/src/components/topics/TopicDiscussionPanel.vue`: Provider-not-ready recovery link; existing explicit-save behavior remains.

### Operations and acceptance

- `backend/scripts/verify_live_market_sources.py`: read-only live qualification; exits nonzero below five successes.
- `backend/scripts/upgrade_product_database_v114.py`: guarded backup plus offline, same-database additive schema/source upgrade.
- `frontend/e2e/run-topic-center-live.mjs`: real front-door acceptance without fake market or Provider data.

## Task 1: Add a strict official HTML document boundary

**Files:**
- Modify: `backend/requirements.txt`
- Modify: `backend/requirements-m2.lock.txt`
- Modify: `backend/gateways/market_sources/base.py`
- Test: `backend/tests/unit/test_market_source_adapters.py`

- [ ] **Step 1: Write failing tests for accepted charsets, stale audit dates, unsafe responses, and bounded detail requests**

Add tests that express the new transport contract:

```python
@pytest.mark.asyncio
async def test_document_accepts_utf8_and_gb18030_without_policy_age_expiry():
    policy = _policy(
        platform="qimao",
        status="verified_public",
        checked_at=1_700_000_000_000,
        origins=("https://www.qimao.com",),
        prefixes=("/paihang/", "/shuku/"),
    )
    response = _transport_response(
        url="https://www.qimao.com/paihang/boy/update/date/",
        body="小说排行榜".encode("gb18030"),
        content_type="text/html; charset=gb2312",
    )
    async def transport(_request):
        return response
    document = await fetch_public_document(
        transport,
        policy=policy,
        policy_hash=canonical_hash(policy),
        url="https://www.qimao.com/paihang/boy/update/date/",
        captured_at=1_800_000_000_000,
    )
    assert document.text == "小说排行榜"

@pytest.mark.asyncio
@pytest.mark.parametrize("body", [b"captcha", "请完成人机验证".encode("utf-8")])
async def test_document_rejects_interstitials(body):
    with pytest.raises(MarketSourceFailure) as raised:
        await _fetch_document(body=body)
    assert raised.value.code == "MARKET_INTERSTITIAL_REJECTED"

def test_text_normalizer_rejects_private_use_font_obfuscation():
    with pytest.raises(MarketSourceFailure) as raised:
        normalized_public_text("\ue515\ue4a2\ue4c2")
    assert raised.value.code == "MARKET_HTML_UNKNOWN"
```

- [ ] **Step 2: Run the focused tests and verify the new imports/functions fail**

Run:

```powershell
python -m pytest -q backend/tests/unit/test_market_source_adapters.py
```

Expected: FAIL because `fetch_public_document` and `normalized_public_text` do not exist and stale policies are rejected.

- [ ] **Step 3: Add Beautiful Soup to both dependency contracts**

Add:

```text
# backend/requirements.txt
beautifulsoup4>=4.13.0,<5

# backend/requirements-m2.lock.txt
beautifulsoup4==4.13.4
soupsieve==2.7
```

- [ ] **Step 4: Replace marker-only parsing with reusable bounded document helpers**

Keep `HttpxMarketTransport`, `TransportRequest`, `TransportResponse`, response-size limits, redirect refusal, allowed-origin checks, and interstitial rejection. Add this public shape and use `BeautifulSoup(..., "html.parser")` only after all transport checks pass:

```python
@dataclass(frozen=True)
class PublicHTMLDocument:
    url: str
    text: str
    soup: BeautifulSoup


def normalized_public_text(value: object, *, limit: int = 300) -> str:
    text = " ".join(str(value or "").split())
    if not text or len(text) > limit:
        raise MarketSourceFailure("MARKET_SNAPSHOT_INVALID")
    if any(0xE000 <= ord(character) <= 0xF8FF for character in text):
        raise MarketSourceFailure("MARKET_HTML_UNKNOWN")
    return text


async def fetch_public_document(
    transport: Transport,
    *,
    policy: SourcePolicy | None,
    policy_hash: str | None,
    url: str,
    captured_at: int,
) -> PublicHTMLDocument:
    verify_transport_policy(
        policy, policy_hash, source_url=url, captured_at=captured_at,
    )
    response = await _bounded_response(transport, url)
    text = _decode_html(response)
    _reject_interstitial(text)
    return PublicHTMLDocument(url=url, text=text, soup=BeautifulSoup(text, "html.parser"))


def canonical_work_url(href, *, base_url, work_origins):
    value = urljoin(base_url, str(href).strip())
    if _origin(value) not in work_origins:
        raise MarketSourceFailure("MARKET_URL_NOT_ALLOWED")
    return value


def bounded_public_metrics(values):
    if not isinstance(values, Mapping) or len(values) > 32:
        raise MarketSourceFailure("MARKET_SNAPSHOT_INVALID")
    return {
        str(key): normalized_public_text(item, limit=200)
        if isinstance(item, str) else item
        for key, item in values.items()
    }


def market_entry_from_fields(
    *, rank, title, author, category, work_url, metrics,
    base_url, work_origins,
):
    return MarketEntry(
        rank=int(str(rank).strip()),
        title=normalized_public_text(title, limit=300),
        author=normalized_public_text(author, limit=200),
        category=normalized_public_text(category, limit=160),
        workURL=canonical_work_url(
            work_url, base_url=base_url, work_origins=work_origins,
        ),
        publicMetrics=bounded_public_metrics(metrics),
    )


class OfficialRankAdapter:
    async def document(self, url, *, policy, policy_hash, captured_at):
        return await fetch_public_document(
            self.transport, policy=policy, policy_hash=policy_hash,
            url=url, captured_at=captured_at,
        )

    def snapshot(self, entries, *, captured_at):
        if not 10 <= len(entries) <= MAX_MARKET_ENTRIES:
            raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
        return MarketSnapshot(
            platform=self.platform, rankingName=self.ranking_name,
            category=self.category, capturedAt=captured_at,
            sourceURL=self.source_url, entries=entries,
        )
```

`verify_transport_policy` must keep the five-minute future-skew rejection but remove only the 30-day upper-age rejection. `_decode_html` accepts UTF-8/UTF8 and GB2312/GBK/GB18030, rejects conflicting charset declarations, and never uses replacement decoding.

- [ ] **Step 5: Run tests and commit**

Run:

```powershell
python -m pytest -q backend/tests/unit/test_market_source_adapters.py
python -m pip check
```

Expected: PASS; `pip check` reports no broken requirements.

Commit:

```powershell
git add -- backend/requirements.txt backend/requirements-m2.lock.txt backend/gateways/market_sources/base.py backend/tests/unit/test_market_source_adapters.py
git commit -m "feat: add strict public market document boundary"
```

## Task 2: Implement the three single-page official adapters

**Files:**
- Modify: `backend/gateways/market_sources/qq_reading_public_rank.py`
- Create: `backend/gateways/market_sources/qimao_public_rank.py`
- Create: `backend/gateways/market_sources/jjwxc_public_rank.py`
- Create: `backend/tests/fixtures/market/qq_rank_official_shape.html`
- Create: `backend/tests/fixtures/market/qimao_rank_official_shape.html`
- Create: `backend/tests/fixtures/market/jjwxc_rank_official_shape.html`
- Test: `backend/tests/unit/test_market_source_adapters.py`

- [ ] **Step 1: Add reduced official-DOM fixtures**

Each fixture contains 10 entries, uses the platform's real selectors, and replaces current titles/authors with neutral short values. Do not store full downloaded pages. The required shapes are:

```html
<!-- QQ -->
<div class="book-large rank-book"><a class="wrap" href="//book.qq.com/book-detail/1">
  <div class="content"><h4 class="title">作品一</h4><p class="intro">公开简介</p>
  <p class="other"><object><a>作者一</a><a>玄幻</a></object><span>连载</span><span>58.5万字</span></p></div>
</a></div>

<!-- 七猫 -->
<li class="rank-list-item"><span class="rank-number">1</span>
  <a class="s-book-title" href="https://www.qimao.com/shuku/1/">作品一</a>
  <span class="s-book-info"><a>作者一</a><a>玄幻奇幻</a><em>连载中</em><em>200万字</em></span>
  <span class="s-book-intro">公开简介</span>
</li>

<!-- 晋江 -->
<tr><td>1</td><td>作者一</td><td><a class="tooltip" href="onebook.php?novelid=1">作品一</a></td>
  <td>原创-言情-架空历史-爱情</td><td>完结</td><td>348925</td><td>3016198144</td></tr>
```

- [ ] **Step 2: Write failing adapter tests**

Assert exact ranks 1–10, canonical absolute work URLs, nonblank author/category, and public metrics:

```python
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("adapter_type", "fixture_name", "platform"),
    [
        (QQReadingPublicRankAdapter, "qq_rank_official_shape.html", "qq_reading"),
        (QimaoPublicRankAdapter, "qimao_rank_official_shape.html", "qimao"),
        (JJWXCPublicRankAdapter, "jjwxc_rank_official_shape.html", "jjwxc"),
    ],
)
async def test_single_page_adapters_normalize_ten_official_entries(
    adapter_type, fixture_name, platform,
):
    snapshot = await adapter_type(_fixture_transport(fixture_name)).fetch(
        policy=_adapter_policy(adapter_type),
        policy_hash=_adapter_policy_hash(adapter_type),
        captured_at=1_800_000_000_000,
    )
    assert snapshot.platform == platform
    assert [entry.rank for entry in snapshot.entries] == list(range(1, 11))
    assert all(entry.title and entry.author and entry.category for entry in snapshot.entries)
    assert all(entry.work_url.startswith("https://") for entry in snapshot.entries)
```

- [ ] **Step 3: Run the tests and verify Qimao/JJWXC adapters are missing**

Run:

```powershell
python -m pytest -q backend/tests/unit/test_market_source_adapters.py -k single_page
```

Expected: FAIL on missing adapter modules/classes.

- [ ] **Step 4: Implement exact selectors and normalized metrics**

Each adapter calls `fetch_public_document`, takes the first complete 10–100 rows, renumbers only when the page presents canonical consecutive ranking, and returns `MarketSnapshot`. Use these selector contracts:

```python
class QimaoPublicRankAdapter(OfficialRankAdapter):
    source_url = "https://www.qimao.com/paihang/boy/update/date/"
    platform = "qimao"
    ranking_name = "boy_update"
    category = "male"
    adapter_version = "qimao-public-rank-v2"

    def parse_entries(self, document):
        return tuple(
            market_entry_from_fields(
                rank=row.select_one(".rank-number").get_text(strip=True),
                title=row.select_one(".s-book-title").get_text(" ", strip=True),
                author=row.select(".s-book-info a")[0].get_text(" ", strip=True),
                category=row.select(".s-book-info a")[1].get_text(" ", strip=True),
                work_url=row.select_one(".s-book-title")["href"],
                metrics=_qimao_metrics(row),
                base_url=self.source_url,
                work_origins=self.work_origins,
            )
            for row in document.soup.select(".rank-list-item")[:100]
        )
```

QQ uses `.rank-book`, `.title`, `.other object a`, `.intro`, and `.other span`. JJWXC uses rows containing `a.tooltip`; it reads rank, author, title, category, status, word count, score, and update time from fixed table cells and refuses rows with an unexpected cell count.

- [ ] **Step 5: Run tests and commit**

Run:

```powershell
python -m pytest -q backend/tests/unit/test_market_source_adapters.py -k "single_page or qq or qimao or jjwxc"
```

Expected: PASS.

Commit:

```powershell
git add -- backend/gateways/market_sources backend/tests/fixtures/market backend/tests/unit/test_market_source_adapters.py
git commit -m "feat: parse three official novel rankings"
```

## Task 3: Implement two bounded detail-enriched adapters

**Files:**
- Modify: `backend/gateways/market_sources/base.py`
- Create: `backend/gateways/market_sources/zongheng_public_rank.py`
- Create: `backend/gateways/market_sources/heiyan_public_rank.py`
- Create: `backend/tests/fixtures/market/zongheng_rank_official_shape.html`
- Create: `backend/tests/fixtures/market/zongheng_detail_official_shape.html`
- Create: `backend/tests/fixtures/market/heiyan_rank_official_shape.html`
- Create: `backend/tests/fixtures/market/heiyan_detail_official_shape.html`
- Test: `backend/tests/unit/test_market_source_adapters.py`

- [ ] **Step 1: Add failing tests for a maximum of ten detail requests**

```python
@pytest.mark.asyncio
@pytest.mark.parametrize("adapter_type", [ZonghengPublicRankAdapter, HeiyanPublicRankAdapter])
async def test_detail_enrichment_is_same_origin_and_capped_at_ten(adapter_type):
    transport = RoutedFixtureTransport(adapter_type)
    snapshot = await adapter_type(transport).fetch(
        policy=_adapter_policy(adapter_type),
        policy_hash=_adapter_policy_hash(adapter_type),
        captured_at=1_800_000_000_000,
    )
    assert len(snapshot.entries) == 10
    assert len(transport.detail_requests) == 10
    assert all(entry.author != "" for entry in snapshot.entries)
    assert all(url.startswith(adapter_type.work_origin) for url in transport.detail_requests)
```

Add rejection tests for an eleventh request, an off-origin detail URL, a detail page over 512 KiB, and a detail page without an author/category.

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```powershell
python -m pytest -q backend/tests/unit/test_market_source_adapters.py -k detail_enrichment
```

Expected: FAIL because both adapters are absent.

- [ ] **Step 3: Implement rank parsing plus bounded same-origin enrichment**

Use the first ten entries from one explicit ranking block. Fetch at most ten detail pages and apply the same policy, redirect, timeout, body, charset, and interstitial checks to every request.

```python
class DetailEnrichedRankAdapter(OfficialRankAdapter):
    detail_limit = 10

    async def fetch(self, *, policy, policy_hash, captured_at):
        rank_page = await self.document(
            self.source_url, policy=policy, policy_hash=policy_hash,
            captured_at=captured_at,
        )
        candidates = self.parse_rank_candidates(rank_page)[: self.detail_limit]
        if len(candidates) != self.detail_limit:
            raise MarketSourceFailure("MARKET_PAGE_INCOMPLETE")
        entries = []
        for rank, title, detail_url, rank_metrics in candidates:
            detail = await self.document(
                detail_url, policy=policy, policy_hash=policy_hash,
                captured_at=captured_at,
            )
            entries.append(self.parse_detail(rank, title, detail_url, rank_metrics, detail))
        return self.snapshot(tuple(entries), captured_at=captured_at)
```

Zongheng selects exactly one `.zh-modules-rank-box` through one explicit, visible `.rank-heading` whose normalized text is exactly `月票榜`; comments, scripts, styles, templates, hidden/`aria-hidden` nodes, and ambiguous headings cannot qualify it. It then uses `.zh-modules-rank-book`, `.book-rank--title a`, requires each candidate URL to match exact `/detail/<positive digits>` before any detail fetch, and reads detail `meta[name="og:novel:author"]`, `meta[name="og:novel:category"]`, `meta[name="og:novel:status"]`, `meta[name="og:description"]`, `.book-info--tags`, and `.book-info--nums`. Its truthful `rankingName` is `monthly_ticket`, but it remains manual-only and no `__NUXT__` payload is parsed or evaluated. Heiyan uses the single exact daily-recommendation page, one `.mod.mod-clean.update-list > .bd > table`, direct `tbody#tbody > tr` rows, and exact `/book/<positive digits>` work URLs. XXSY uses the exact `/rank/xxyuepiao` page and one exact `div.flex.flex-1.flex-wrap.relative.min-h-328px.ml-30px` container. Its three direct elements must be the `div.flex` heading wrapper with one direct `h3.font-source.text-t1` equal to `潇湘票榜`, one benign `i.block.line...` separator, and the unique `div.flex.flex-wrap.relative` grid with exactly 20 direct cards. A heading injected into a card cannot qualify the container. Each card requires an exact `/book/<positive digits>` work URL and strict `author · wordCount · category` row. Required OpenGraph values must match the rank title and detail URL where a detail-enriched adapter is used.

- [ ] **Step 4: Run tests and commit**

Run:

```powershell
python -m pytest -q backend/tests/unit/test_market_source_adapters.py -k "zongheng or heiyan or detail_enrichment"
```

Expected: PASS.

Commit:

```powershell
git add -- backend/gateways/market_sources backend/tests/fixtures/market backend/tests/unit/test_market_source_adapters.py
git commit -m "feat: enrich two official ranking sources safely"
```

## Task 4: Register the ten bounded public-rank candidate adapters

**Files:**
- Create: `backend/gateways/market_sources/fanqie_public_rank.py`
- Create: `backend/gateways/market_sources/seventeen_k_public_rank.py`
- Create: `backend/gateways/market_sources/hongxiu_public_rank.py`
- Create: `backend/gateways/market_sources/registry.py`
- Modify: `backend/domain/routers/market_sources.py`
- Create: `backend/tests/fixtures/market/fanqie_obfuscated_official_shape.html`
- Create: `backend/tests/fixtures/market/seventeen_k_rank_official_shape.html`
- Create: `backend/tests/fixtures/market/hongxiu_rank_official_shape.html`
- Test: `backend/tests/unit/test_market_source_adapters.py`
- Test: `backend/tests/api/test_market_source_routes.py`

- [ ] **Step 1: Write failing tests for registry completeness and fail-closed parsing**

```python
def test_candidate_registry_contains_exact_ten_adapter_keys():
    assert set(candidate_adapter_factories()) == {
        "fanqie_public_rank", "qimao_public_rank", "qq_reading_public_rank",
        "17k_public_rank", "zongheng_public_rank", "hongxiu_public_rank",
        "jjwxc_public_rank", "heiyan_public_rank",
        "readnovel_public_rank", "xxsy_public_rank",
    }

@pytest.mark.asyncio
async def test_fanqie_obfuscated_font_is_not_published_as_garbled_market_data():
    with pytest.raises(MarketSourceFailure) as raised:
        await _fanqie_fixture_adapter().fetch(**_verified_fetch_args())
    assert raised.value.code == "MARKET_HTML_UNKNOWN"

@pytest.mark.asyncio
@pytest.mark.parametrize("adapter_type", [SeventeenKPublicRankAdapter, HongxiuPublicRankAdapter])
async def test_title_only_ranking_is_rejected_without_real_author(adapter_type):
    with pytest.raises(MarketSourceFailure) as raised:
        await _candidate_fixture_adapter(adapter_type).fetch(**_verified_fetch_args())
    assert raised.value.code == "MARKET_PAGE_INCOMPLETE"
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
python -m pytest -q backend/tests/unit/test_market_source_adapters.py backend/tests/api/test_market_source_routes.py -k registry
```

Expected: FAIL because the registry does not exist.

- [ ] **Step 3: Implement the candidate parsers and central registry**

Fanqie recognizes `.rank-book-item` but rejects any PUA-obfuscated required field. 17K recognizes the first `.TYPE .BOX.Top1`; Hongxiu recognizes the first `.rank-list .book-rank-list`; both reject rather than invent authors when the official response lacks them. 17K remains a registered, non-packaged candidate and is not part of the ten-source v1.1 package.

```python
def candidate_adapter_factories():
    return MappingProxyType({
        "fanqie_public_rank": FanqiePublicRankAdapter,
        "qimao_public_rank": QimaoPublicRankAdapter,
        "qq_reading_public_rank": QQReadingPublicRankAdapter,
        "17k_public_rank": SeventeenKPublicRankAdapter,
        "zongheng_public_rank": ZonghengPublicRankAdapter,
        "hongxiu_public_rank": HongxiuPublicRankAdapter,
        "jjwxc_public_rank": JJWXCPublicRankAdapter,
        "heiyan_public_rank": HeiyanPublicRankAdapter,
        "readnovel_public_rank": ReadNovelPublicRankAdapter,
        "xxsy_public_rank": XXSYPublicRankAdapter,
    })


def build_market_adapters(transport):
    return {
        key: adapter_type(transport)
        for key, adapter_type in candidate_adapter_factories().items()
    }
```

Replace router-local imports/mapping with `build_market_adapters(transport)`. Keep Qidian outside the candidate registry and manual-only.

- [ ] **Step 4: Run tests and commit**

Run:

```powershell
python -m pytest -q backend/tests/unit/test_market_source_adapters.py backend/tests/api/test_market_source_routes.py
```

Expected: PASS.

Commit:

```powershell
git add -- backend/gateways/market_sources backend/domain/routers/market_sources.py backend/tests/fixtures/market backend/tests/unit/test_market_source_adapters.py backend/tests/api/test_market_source_routes.py
git commit -m "feat: register bounded market source candidates"
```

## Task 5: Version and synchronize the built-in market source package

**Files:**
- Create: `backend/assets/market-sources-v1.1.0/sources.json`
- Create: `backend/assets/market-sources-v1.1.0/manifest.json`
- Modify: `backend/domain/market_sources.py`
- Modify: `backend/services/market_sources.py`
- Modify: `backend/repositories/market.py`
- Modify: `backend/scripts/seed_market_sources.py`
- Modify: `backend/services/product_database_readiness.py`
- Test: `backend/tests/unit/test_market_source_manifest.py`
- Test: `backend/tests/unit/test_seed_market_sources.py`
- Test: `backend/tests/unit/test_product_database_readiness.py`
- Test: `backend/tests/unit/test_prepare_product_database_command.py`
- Test: `backend/tests/unit/test_prepare_phase2_browser_db.py`
- Test: `backend/tests/integration/test_product_database_readiness_mysql.py`
- Test: `backend/tests/integration/test_market_snapshots.py`

- [ ] **Step 1: Write failing tests for ten sources and versioned in-place synchronization**

```python
def test_v11_package_has_ten_sources_five_verified_and_no_scheduler():
    package = load_market_source_package(V11_MANIFEST)
    assert package.package_version == "market-sources-v1.1.0"
    assert len(package.sources) == 10
    verified = {item.adapter_key for item in package.sources if item.policy.status == "verified_public"}
    assert verified == {
        "qq_reading_public_rank", "qimao_public_rank", "heiyan_public_rank",
        "readnovel_public_rank", "xxsy_public_rank",
    }
    assert all(item.policy.enabled is False for item in package.sources)
    assert all(item.can_schedule is False for item in package.sources)

def test_old_checked_at_remains_audit_data_not_a_refresh_kill_switch():
    service = _service(clock=lambda: 1_900_000_000_000)
    source = service._public_source(_verified_row(checked_at=1_700_000_000_000))
    assert source["automatic_refresh_allowed"] is True

@pytest.mark.asyncio
async def test_sync_upgrades_existing_sources_with_new_policy_revisions():
    repository = v10_seeded_repository()
    report = await MarketSourceSeedService(repository, **_seed_dependencies()).seed(V11_PACKAGE)
    assert report.inserted == 5
    assert report.updated == 3
    assert report.replayed == 2
    assert repository.heads[repository.id_for("qq-reading.male-popular")]["revision"] == 2
    assert repository.snapshot_count == 0
```

The registry contains ten candidate adapters, while the hash-bound package contains ten source definitions. The five verified package sources are the exact initial production gate. Fanqie, Zongheng, and JJWXC remain manual-only until their returned data meets the same bounded response and author/title/category requirement. Qidian and Shuqi remain manual-only compatibility sources. 17K remains a registered non-packaged candidate; 17K and Hongxiu are not part of the ten-source package.

- [ ] **Step 2: Run focused tests and verify they fail**

Run:

```powershell
python -m pytest -q backend/tests/unit/test_market_source_manifest.py backend/tests/unit/test_seed_market_sources.py
```

Expected: FAIL because v1.1.0 and update behavior do not exist.

- [ ] **Step 3: Extend the immutable adapter key and capability contract**

Replace the five-value adapter literal with all retained manual and public keys. Define one immutable refreshable set and use it from `can_refresh`:

```python
NETWORK_ADAPTER_KEYS = frozenset({
    "fanqie_public_rank", "qimao_public_rank", "qq_reading_public_rank",
    "17k_public_rank", "zongheng_public_rank", "hongxiu_public_rank",
    "jjwxc_public_rank", "heiyan_public_rank",
    "readnovel_public_rank", "xxsy_public_rank",
})

@property
def can_refresh(self) -> bool:
    return self.adapter_key in NETWORK_ADAPTER_KEYS and self.policy.status == "verified_public"
```

Set `PACKAGE_VERSION` to `market-sources-v1.1.0`; allow `MarketSourceManifest.package_version` to parse both `market-sources-v1.0.0` and `market-sources-v1.1.0` so immutable historical package tests remain readable. Point the active seeding command/readiness checks at the new manifest. In `MarketSourceService._public_source`, keep hash/status/future-skew checks and remove only the 30-day upper-age condition so `checkedAt` is audit data rather than a runtime kill switch.

- [ ] **Step 4: Add guarded source and policy-head update operations**

Add repository methods with CAS checks:

```python
async def update_source_definition(self, session, *, source_id, expected_updated_at, source, now_ms):
    changed = await session.execute(
        """UPDATE market_sources SET adapter_key=%s,display_name=%s,
                  public_config_json=%s,updated_at=%s
           WHERE id=%s AND updated_at=%s AND status='active'""",
        (source.adapter_key, source.display_name,
         canonical_json(dict(source.public_config)), now_ms,
         source_id, expected_updated_at),
    )
    if changed != 1:
        raise MarketSourceSeedConflict()

async def replace_policy_head(self, session, *, source_id, expected_revision, row):
    changed = await session.execute(
        """UPDATE market_source_policy_heads
           SET revision_id=%s,revision=%s,content_hash=%s,updated_at=%s
           WHERE source_id=%s AND revision=%s""",
        (row["revision_id"], row["revision"], row["content_hash"],
         row["updated_at"], source_id, expected_revision),
    )
    if changed != 1:
        raise MarketSourceSeedConflict()
```

`MarketSourceSeedService.seed` must perform one transaction: exact matches replay; missing stable keys insert; changed existing definitions create `head.revision + 1`, update the source definition, insert the immutable policy revision, and CAS-move the head. Add `updated: int = 0` as the final `MarketSourceSeedReport` field and populate it for changed sources without breaking old constructor call sites. It never deletes sources, policies, snapshots, or refresh history.

- [ ] **Step 5: Create the ten-source v1.1 package**

Retain these stable keys: `qidian.newsign`, `qq-reading.male-popular`, `fanqie.reading`, `qimao.public-catalog`, `shuqi.public-catalog`. Add: `xxsy.xiaoxiang-ticket`, `zongheng.monthly`, `readnovel.original-monthly-ticket`, `jjwxc.quarterly-score`, `heiyan.daily-recommendation`. The five verified display names are exactly `QQ 阅读男生人气榜`, `七猫男生更新榜`, `黑岩每日推荐榜`, `小说阅读网原创月票榜`, and `潇湘票榜`.

Use `verified_public` only for QQ Reading, Qimao, Heiyan, ReadNovel, and XXSY. Zongheng and JJWXC remain `manual_only`. All policies keep `enabled: false` and `requestIntervalSeconds: 3600`; verified policies include their exact rank path and work path in their path prefixes. Compute the child hash, update `manifest.json` with `apply_patch`, then validate:

```powershell
$hash = (Get-FileHash 'backend\assets\market-sources-v1.1.0\sources.json' -Algorithm SHA256).Hash.ToLowerInvariant()
$hash
python -m backend.scripts.seed_market_sources --validate-only
```

Expected: a 64-character lowercase hash followed by `package_version=market-sources-v1.1.0` and `source_count=10`.

- [ ] **Step 6: Run tests and commit**

Run:

```powershell
python -m pytest -q backend/tests/unit/test_market_source_manifest.py backend/tests/unit/test_seed_market_sources.py backend/tests/unit/test_product_database_readiness.py backend/tests/unit/test_prepare_product_database_command.py backend/tests/unit/test_prepare_phase2_browser_db.py backend/tests/integration/test_market_snapshots.py
```

Expected: PASS with ten sources and immutable historical policy revisions.

Commit:

```powershell
git add -- backend/assets/market-sources-v1.1.0 backend/domain/market_sources.py backend/services/market_sources.py backend/repositories/market.py backend/scripts/seed_market_sources.py backend/services/product_database_readiness.py backend/tests/unit/test_market_source_manifest.py backend/tests/unit/test_seed_market_sources.py backend/tests/unit/test_product_database_readiness.py backend/tests/unit/test_prepare_product_database_command.py backend/tests/unit/test_prepare_phase2_browser_db.py backend/tests/integration/test_product_database_readiness_mysql.py backend/tests/integration/test_market_snapshots.py
git commit -m "feat: synchronize verified market source package"
```

## Task 6: Expose immutable snapshot origin and strict frontend contracts

**Files:**
- Modify: `backend/repositories/market.py`
- Modify: `backend/domain/routers/market_sources.py`
- Create: `frontend/src/application/market/marketContracts.js`
- Modify: `frontend/src/api/db/client.js`
- Modify: `frontend/src/stores/marketSourceStore.js`
- Test: `backend/tests/api/test_market_source_routes.py`
- Test: `frontend/tests/unit/marketSourceStore.test.mjs`
- Create: `frontend/tests/unit/marketContracts.test.mjs`

- [ ] **Step 1: Write failing API and client-contract tests**

```python
def test_snapshot_detail_exposes_capture_mode_adapter_and_entries(client):
    value = client.get("/api/market-sources/source-1/snapshots/snapshot-1").json()
    assert value["captureMode"] == "network"
    assert value["adapterVersion"] == "qimao-public-rank-v2"
    assert len(value["entries"]) == value["entryCount"] == 10
```

```javascript
test('snapshot contract freezes real work details and provenance', () => {
  const value = parseMarketSnapshot(snapshotFixture, { detail: true })
  assert.equal(value.captureMode, 'network')
  assert.equal(value.entries[0].rank, 1)
  assert.equal(value.entries[0].workURL, 'https://www.qimao.com/shuku/1/')
  assert(Object.isFrozen(value.entries))
})
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
python -m pytest -q backend/tests/api/test_market_source_routes.py -k capture_mode
node --test frontend/tests/unit/marketContracts.test.mjs frontend/tests/unit/marketSourceStore.test.mjs
```

Expected: FAIL on missing provenance fields/parser.

- [ ] **Step 3: Join immutable manifest provenance into snapshot reads**

Update summary/detail queries to join `market_snapshot_manifests` and return `adapter_version`. Map `manual-snapshot-v1` to `captureMode: "manual"`; every registered official adapter maps to `captureMode: "network"`.

The API detail shape is exact:

```json
{
  "id": "snapshot-id",
  "sourceId": "source-id",
  "capturedAt": 1800000000000,
  "platform": "qimao",
  "rankingName": "boy_update",
  "category": "male",
  "sourceURL": "https://www.qimao.com/paihang/boy/update/date/",
  "contentHash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "entryCount": 10,
  "captureMode": "network",
  "adapterVersion": "qimao-public-rank-v2",
  "entries": []
}
```

- [ ] **Step 4: Add strict frontend parsing and store usage**

`marketContracts.js` validates exact keys, canonical rank order, 1–100 entries, HTTPS work URLs, bounded metric objects, and `captureMode`. Wrap all `api.marketSources` results with these parsers. `loadSnapshotDetail` must cache only parsed immutable values.

- [ ] **Step 5: Run tests and commit**

Run:

```powershell
python -m pytest -q backend/tests/api/test_market_source_routes.py
node --test frontend/tests/unit/marketContracts.test.mjs frontend/tests/unit/marketSourceStore.test.mjs
```

Expected: PASS.

Commit:

```powershell
git add -- backend/repositories/market.py backend/domain/routers/market_sources.py backend/tests/api/test_market_source_routes.py frontend/src/application/market/marketContracts.js frontend/src/api/db/client.js frontend/src/stores/marketSourceStore.js frontend/tests/unit/marketContracts.test.mjs frontend/tests/unit/marketSourceStore.test.mjs
git commit -m "feat: expose trusted market snapshot details"
```

## Task 7: Turn the market page into a ranked-work reading surface

**Files:**
- Create: `frontend/src/components/topics/MarketSnapshotWorks.vue`
- Modify: `frontend/src/components/topics/MarketDiscoveryPanel.vue`
- Modify: `frontend/src/views/TopicCenterView.vue`
- Test: `frontend/tests/unit/topicCenterView.test.mjs`
- Create: `frontend/tests/unit/marketSnapshotWorks.test.mjs`

- [ ] **Step 1: Write failing product-surface tests**

```javascript
test('market page exposes actual works rather than snapshot counts only', async () => {
  const source = await readFile(component('MarketSnapshotWorks.vue'), 'utf8')
  for (const text of ['排名', '书名', '作者', '题材', '公开指标', '查看原页面']) {
    assert.match(source, new RegExp(text))
  }
  assert.match(source, /entry\.workURL/)
  assert.match(source, /rel="noopener noreferrer"/)
})

test('source cards distinguish network refresh from manual import', async () => {
  const source = await readFile(component('MarketDiscoveryPanel.vue'), 'utf8')
  assert.match(source, /网络刷新/)
  assert.match(source, /人工导入/)
  assert.match(source, /查看榜单作品/)
  assert.doesNotMatch(source, /自动刷新|定时刷新/)
})
```

- [ ] **Step 2: Run tests and verify the component is absent**

Run:

```powershell
node --test frontend/tests/unit/topicCenterView.test.mjs frontend/tests/unit/marketSnapshotWorks.test.mjs
```

Expected: FAIL because `MarketSnapshotWorks.vue` does not exist.

- [ ] **Step 3: Implement detail loading and accessible work display**

`MarketDiscoveryPanel` keeps compact source cards. “查看榜单作品” loads the latest snapshot detail and selects it. Render one `MarketSnapshotWorks` below/alongside the source list with:

```vue
<ol class="ranked-works" aria-label="榜单作品">
  <li v-for="entry in snapshot.entries" :key="entry.rank" class="ranked-work">
    <span class="rank">{{ String(entry.rank).padStart(2, '0') }}</span>
    <div><h3>{{ entry.title }}</h3><p>{{ entry.author }} · {{ entry.category }}</p></div>
    <dl><div v-for="(value, key) in visibleMetrics(entry.publicMetrics)" :key="key">
      <dt>{{ metricLabel(key) }}</dt><dd>{{ value }}</dd>
    </div></dl>
    <a :href="entry.workURL" target="_blank" rel="noopener noreferrer">查看原页面</a>
  </li>
</ol>
```

Each source card exposes `data-market-source-key` and a computed `data-market-source-status` of `available`, `available-with-later-failure`, `failed`, or `not-captured`. Give refresh buttons the accessible name `刷新${source.displayName}`. Show source name, capture time, `网络刷新/人工导入`, entry count, and “附加到讨论”. Keep a single vertical scroll owner on narrow screens and never lock body scroll.

- [ ] **Step 4: Run unit tests and production build**

Run:

```powershell
node --test frontend/tests/unit/topicCenterView.test.mjs frontend/tests/unit/marketSnapshotWorks.test.mjs frontend/tests/unit/marketSourceStore.test.mjs
npm --prefix frontend run build
```

Expected: PASS and Vite build succeeds.

- [ ] **Step 5: Commit**

```powershell
git add -- frontend/src/components/topics/MarketSnapshotWorks.vue frontend/src/components/topics/MarketDiscoveryPanel.vue frontend/src/views/TopicCenterView.vue frontend/tests/unit/topicCenterView.test.mjs frontend/tests/unit/marketSnapshotWorks.test.mjs
git commit -m "feat: show real ranked works in topic center"
```

## Task 8: Complete Provider recovery and discussion-to-project UX

**Files:**
- Modify: `frontend/src/components/topics/TopicDiscussionPanel.vue`
- Modify: `frontend/src/stores/topicCenterStore.js`
- Modify: `frontend/src/router/projectRoutes.js`
- Test: `frontend/tests/unit/topicCenterView.test.mjs`
- Test: `frontend/tests/unit/topicCenterStore.test.mjs`
- Test: `backend/tests/unit/test_topic_discussion_prompt.py`
- Test: `backend/tests/unit/test_topic_discussion_service.py`
- Test: `backend/tests/unit/test_topic_project_handoff.py`

- [ ] **Step 1: Write failing tests for Provider-not-ready recovery and preserved input**

```javascript
test('provider-not-ready keeps author text and offers model settings', async () => {
  const store = createTopicCenterStore({
    sendMessage: async () => { throw new ApiError({ code: 'TOPIC_PROVIDER_NOT_READY' }) },
  }, 'topic-provider-recovery')()
  await assert.rejects(store.sendMessage('d1', { content: '保留这段想法' }))
  assert.equal(store.lastSendFailure.code, 'TOPIC_PROVIDER_NOT_READY')
})
```

Source-level UI assertions must require `providerSettingsPath()`, “配置默认模型”, and the absence of automatic retry/save/project creation language.

- [ ] **Step 2: Run focused tests and verify failure**

Run:

```powershell
node --test frontend/tests/unit/topicCenterStore.test.mjs frontend/tests/unit/topicCenterView.test.mjs
```

Expected: FAIL because the store does not expose a stable last-send failure and the UI has no settings link.

- [ ] **Step 3: Implement the minimum recovery state**

Expose only `lastSendFailure` and `clearSendFailure` from the store. In the panel, keep `draft` unchanged on any failure; for `TOPIC_PROVIDER_NOT_READY`, render:

```vue
<router-link :to="providerSettingsPath()">配置默认模型</router-link>
```

Do not add a model selector to Topic Center. Keep the existing maximum four evidence references, 20 entries per evidence snapshot, strict structured result, explicit save actions, immutable versions, and atomic handoff.

- [ ] **Step 4: Run the entire deterministic Topic Center backend/frontend set**

Run:

```powershell
python -m pytest -q backend/tests/unit/test_topic_discussion_prompt.py backend/tests/unit/test_topic_discussion_provider.py backend/tests/unit/test_topic_discussion_service.py backend/tests/unit/test_topic_library_service.py backend/tests/unit/test_topic_project_handoff.py backend/tests/api/test_topic_routes.py
node --test frontend/tests/unit/topicContracts.test.mjs frontend/tests/unit/topicCenterStore.test.mjs frontend/tests/unit/topicCenterView.test.mjs
```

Expected: PASS without a real Provider call.

- [ ] **Step 5: Commit**

```powershell
git add -- frontend/src/components/topics/TopicDiscussionPanel.vue frontend/src/stores/topicCenterStore.js frontend/src/router/projectRoutes.js frontend/tests/unit/topicCenterView.test.mjs frontend/tests/unit/topicCenterStore.test.mjs backend/tests/unit/test_topic_discussion_prompt.py backend/tests/unit/test_topic_discussion_service.py backend/tests/unit/test_topic_project_handoff.py
git commit -m "fix: close topic discussion recovery flow"
```

## Task 9: Add the explicit backup-and-upgrade command for the existing database

**Files:**
- Create: `backend/scripts/upgrade_product_database_v114.py`
- Create: `backend/tests/unit/test_upgrade_product_database_v114.py`
- Modify: `backend/schema_manifest.py`
- Modify: `backend/tests/unit/test_schema_manifest.py`
- Modify: `backend/tests/unit/test_schema_version.py`

- [ ] **Step 1: Write failing preflight, success, partial-DDL, and secret-output tests**

```python
@pytest.mark.asyncio
async def test_upgrade_requires_exact_old_metadata_and_91_tables():
    session = FakeUpgradeSession(
        version="writer-core-v1.13.0",
        manifest_hash=v113_manifest_hash(),
        tables=v113_table_names(),
    )
    result = await upgrade_v113_to_v114(
        session, database="novel_creator_v113",
        confirm_database="novel_creator_v113", now_ms=1_800_000_000_000,
    )
    assert result.table_count == 99
    assert session.executed_ddl == topic_statements()
    assert session.metadata_update == (
        "writer-core-v1.14.0", manifest_hash(), 1_800_000_000_000,
    )

@pytest.mark.asyncio
async def test_upgrade_rejects_any_partial_topic_schema_before_writing():
    session = FakeUpgradeSession(tables=(*v113_table_names(), "topic_discussions"))
    with pytest.raises(SchemaUpgradeError, match="preflight"):
        await upgrade_v113_to_v114(session, **CONFIRMED_DATABASE)
    assert session.executed == []

@pytest.mark.asyncio
async def test_product_upgrade_creates_backup_before_ddl_and_syncs_sources_after_metadata():
    events = []
    result = await run_product_upgrade(
        dependencies=fake_dependencies(events),
        database="novel_creator_v113",
        confirm_database="novel_creator_v113",
        backup_directory=Path(r"D:\NovelCreatorBackups\topic-center-v114-20260904"),
        mysqldump=Path(r"D:\Software\MySQL Server 8.4\bin\mysqldump.exe"),
        mysql=Path(r"D:\Software\MySQL Server 8.4\bin\mysql.exe"),
    )
    assert events == [
        "inventory", "market-source-inventory", "backup", "ddl", "metadata",
        "seed-market", "verify",
    ]
    assert result.backup_sha256 == "a" * 64

@pytest.mark.asyncio
async def test_incompatible_market_source_inventory_refuses_before_backup_or_ddl():
    dependencies = fake_dependencies(market_source_keys=("qq-reading.male-popular",))
    with pytest.raises(SchemaUpgradeError) as raised:
        await run_product_upgrade(dependencies=dependencies, **UPGRADE_ARGUMENTS)
    assert str(raised.value) == "PRODUCT_DATABASE_MARKET_SOURCE_INVENTORY_INCOMPATIBLE"
    assert dependencies.events == ["inventory", "market-source-inventory"]
```

Also assert: mismatched database confirmation, non-v1.13 metadata, wrong old hash, wrong old table inventory, an empty/missing/extra source inventory, the original pre-correction v1.1 ten-source inventory, and already-v1.14 replay all refuse before backup and DDL; CLI output contains no host/user/password.

- [ ] **Step 2: Run tests and verify missing module failure**

Run:

```powershell
python -m pytest -q backend/tests/unit/test_upgrade_product_database_v114.py
```

Expected: FAIL because the command does not exist.

- [ ] **Step 3: Implement exact old/new manifest derivation**

Do not copy a stale 91-table list. First expose a bounded manifest helper and make existing `read_statements()` call it:

```python
def read_fragment_statements(fragment_name: str) -> tuple[str, ...]:
    if fragment_name not in FRAGMENTS:
        raise ValueError("fragment is outside the schema manifest")
    normalized = _normalize_newlines(
        (SCHEMA_DIR / fragment_name).read_text(encoding="utf-8")
    )
    return tuple(
        part.strip() for part in _STATEMENT_SPLIT.split(normalized) if part.strip()
    )
```

Then derive the old manifest by excluding only `19_topics.sql` from current fragments:

```python
TOPIC_FRAGMENT = "19_topics.sql"

def v113_statements() -> tuple[str, ...]:
    return tuple(
        statement
        for name in FRAGMENTS if name != TOPIC_FRAGMENT
        for statement in read_fragment_statements(name)
    )

def topic_statements() -> tuple[str, ...]:
    return read_fragment_statements(TOPIC_FRAGMENT)
```

Flatten the statement tuples, calculate the normalized v1.13 hash with the same delimiter algorithm as `schema_manifest.manifest_hash`, and require exactly 91 old tables and exactly eight new Topic Center tables.

- [ ] **Step 4: Implement the fail-closed offline command**

The single product command owns the required ordering: advisory lock, exact schema inventory, read-only market-source compatibility inventory, unique logical backup, eight additive DDL statements, metadata CAS, v1.1 source synchronization, and read-only post-verification. CLI:

```text
python -m backend.scripts.upgrade_product_database_v114 \
  --database novel_creator_v113 \
  --confirm-database novel_creator_v113 \
  --backup-directory D:\NovelCreatorBackups\topic-center-v114-20260904 \
  --mysqldump "D:\Software\MySQL Server 8.4\bin\mysqldump.exe" \
  --mysql "D:\Software\MySQL Server 8.4\bin\mysql.exe"
```

While the advisory lock is held and before backup or DDL, the command loads the hash-bound `market-sources-v1.0.0` package and requires the database to contain exactly its five stable keys: `qidian.newsign`, `qq-reading.male-popular`, `fanqie.reading`, `qimao.public-catalog`, and `shuqi.public-catalog`. Empty, missing, extra, duplicate, or any prior v1.1 inventory fails with `PRODUCT_DATABASE_MARKET_SOURCE_INVENTORY_INCOMPATIBLE` and performs no write. The command also validates the exact database name, current metadata/hash/table inventory, absence of all eight topic tables, MySQL 8.4 client pair, private backup directory, and live connection before creating one unique backup. Only after a nonempty backup has been hashed does it execute `19_topics.sql`, re-read all 99 tables, and update singleton metadata with a guarded predicate on the old version/hash:

```python
changed = await session.execute(
    """UPDATE schema_metadata
       SET schema_version=%s,manifest_hash=%s,initialized_at=%s
       WHERE singleton_id=1 AND schema_version=%s AND manifest_hash=%s""",
    (EXPECTED_SCHEMA_VERSION, manifest_hash(), now_ms,
     "writer-core-v1.13.0", v113_manifest_hash()),
)
if changed != 1:
    raise SchemaUpgradeError("schema upgrade metadata conflict")
```

After metadata changes, the same command synchronizes `market-sources-v1.1.0` and verifies the 99-table/current-hash/ten-source result read-only. MySQL DDL auto-commits, so the command must never claim transaction rollback. On any DDL failure it prints one fixed “restore required” error and exits 1; Task 12 stops and restores the emitted backup manually. There is no runtime migration-on-start path.

- [ ] **Step 5: Run tests and commit**

Run:

```powershell
python -m pytest -q backend/tests/unit/test_upgrade_product_database_v114.py backend/tests/unit/test_schema_manifest.py backend/tests/unit/test_schema_version.py
```

Expected: PASS.

Commit:

```powershell
git add -- backend/scripts/upgrade_product_database_v114.py backend/schema_manifest.py backend/tests/unit/test_upgrade_product_database_v114.py backend/tests/unit/test_schema_manifest.py backend/tests/unit/test_schema_version.py
git commit -m "feat: add guarded in-place topic database upgrade"
```

## Task 10: Add live source qualification and real front-door acceptance

**Files:**
- Create: `backend/scripts/verify_live_market_sources.py`
- Create: `backend/tests/unit/test_verify_live_market_sources.py`
- Create: `frontend/e2e/run-topic-center-live.mjs`
- Modify: `scripts/test-suites.mjs`
- Test: `backend/tests/unit/test_verify_live_market_sources.py`
- Test: `frontend/e2e/p0-c-topic-center.spec.ts`

- [ ] **Step 1: Write failing tests for the five-source gate**

```python
@pytest.mark.asyncio
async def test_live_verifier_fails_when_fewer_than_five_sources_succeed():
    result = await verify_sources(
        VERIFIED_KEYS,
        fetch=lambda key: valid_snapshot(key) if key in VERIFIED_KEYS[:4]
        else (_ for _ in ()).throw(MarketSourceFailure("MARKET_HTTP_FAILED")),
    )
    assert result.exit_code == 1
    assert result.succeeded == 4
    assert result.failed == 1

@pytest.mark.asyncio
async def test_live_verifier_requires_ten_complete_entries_per_success():
    result = await verify_sources(VERIFIED_KEYS, fetch=fetch_nine_entries)
    assert result.exit_code == 1
    assert result.public_errors == {"MARKET_PAGE_INCOMPLETE"}
```

- [ ] **Step 2: Run tests and verify missing module failure**

Run:

```powershell
python -m pytest -q backend/tests/unit/test_verify_live_market_sources.py
```

Expected: FAIL because the verifier is absent.

- [ ] **Step 3: Implement the read-only verifier**

The command loads the hash-bound v1.1 package, selects `verified_public` definitions, instantiates only those registered adapters, performs one refresh attempt per source without opening a database, and outputs only:

```text
source=qq-reading.male-popular status=succeeded entries=20 captured_at=1800000000000
source=qimao.public-catalog status=failed code=MARKET_PAGE_INCOMPLETE
summary succeeded=5 failed=0 required=5
```

It exits 0 only when at least five distinct platforms return at least ten canonical entries with nonblank title/author/category and approved HTTPS work URLs.

- [ ] **Step 4: Implement a live Playwright runner with no fakes**

`run-topic-center-live.mjs` accepts `--base-url`, refuses non-loopback URLs, and performs the real UI path:

```javascript
await page.goto(`${baseURL}/topics/market`)
await expect(page.getByText('市场热门与公开证据')).toBeVisible()
const verifiedSources = [
  ['qq-reading.male-popular', 'QQ 阅读男生人气榜'],
  ['qimao.public-catalog', '七猫男生更新榜'],
  ['heiyan.daily-recommendation', '黑岩每日推荐榜'],
  ['readnovel.original-monthly-ticket', '小说阅读网原创月票榜'],
  ['xxsy.xiaoxiang-ticket', '潇湘票榜'],
]
for (const [key, name] of verifiedSources) {
  const card = page.locator(`[data-market-source-key="${key}"]`)
  await page.getByRole('button', { name: `刷新${name}` }).click()
  await expect(card).toHaveAttribute('data-market-source-status', 'available', { timeout: 120_000 })
}
await expect(page.locator('[data-market-source-status="available"]')).toHaveCount(5)
await page.getByRole('button', { name: '查看榜单作品' }).first().click()
await expect(page.getByRole('list', { name: '榜单作品' }).getByRole('listitem')).toHaveCount(10)
await page.getByLabel('新讨论标题').fill(`真实选题验收-${runId}`)
await page.getByRole('button', { name: '开始讨论' }).click()
await page.getByLabel('继续讨论').fill('基于当前市场信息，给出适合二百万字长篇的原创方向。')
await page.getByRole('button', { name: '发送给 AI' }).click()
await expect(page.getByText('AI 建议').last()).toBeVisible({ timeout: 210_000 })
await page.getByRole('button', { name: '保存为候选种子' }).first().click()
await page.getByRole('link', { name: '候选种子库' }).click()
await page.getByRole('button', { name: '创建项目' }).first().click()
await page.getByLabel('项目名称').fill(`真实选题项目-${runId}`)
await page.getByRole('button', { name: '创建项目并检查种子' }).click()
await expect(page.getByText('待确认')).toBeVisible()
```

The runner performs two discussions: one without evidence and one with a real selected snapshot. It saves one direction and one candidate, continues the candidate discussion to create version 2, creates one project from version 2, and stops on the project Seed page before confirmation. It must not configure the Provider, use route interception, insert data directly, or call backend APIs from the test.

- [ ] **Step 5: Run deterministic regression and commit**

Run:

```powershell
python -m pytest -q backend/tests/unit/test_verify_live_market_sources.py backend/tests/unit/test_market_source_adapters.py backend/tests/unit/test_market_source_manifest.py backend/tests/unit/test_seed_market_sources.py backend/tests/api/test_market_source_routes.py backend/tests/api/test_topic_routes.py
node --test frontend/tests/unit/marketContracts.test.mjs frontend/tests/unit/marketSourceStore.test.mjs frontend/tests/unit/marketSnapshotWorks.test.mjs frontend/tests/unit/topicCenterStore.test.mjs frontend/tests/unit/topicCenterView.test.mjs
npm --prefix frontend run build
```

Expected: all tests pass and production build succeeds. Do not run the live Playwright runner yet.

Commit:

```powershell
git add -- backend/scripts/verify_live_market_sources.py backend/tests/unit/test_verify_live_market_sources.py frontend/e2e/run-topic-center-live.mjs frontend/e2e/p0-c-topic-center.spec.ts scripts/test-suites.mjs
git commit -m "test: add live topic center release gate"
```

## Task 11: Qualify live sources before any database write

**Files:**
- No repository file changes expected.

- [ ] **Step 1: Confirm a clean implementation branch and exact commit**

Run:

```powershell
git status --short --branch
git rev-parse HEAD
```

Expected: only known pre-existing untracked review/tmp artifacts remain; no implementation file is modified.

- [ ] **Step 2: Run the live read-only source qualification once**

Run:

```powershell
python -m backend.scripts.verify_live_market_sources
```

Expected: exit 0, exactly five `status=succeeded` lines for `qq-reading.male-popular` (QQ 阅读男生人气榜), `qimao.public-catalog` (七猫男生更新榜), `heiyan.daily-recommendation` (黑岩每日推荐榜), `readnovel.original-monthly-ticket` (小说阅读网原创月票榜), and `xxsy.xiaoxiang-ticket` (潇湘票榜). Every success has `entries>=10`, and the final line is `summary succeeded=5 failed=0 required=5`. `zongheng.monthly` and `jjwxc.quarterly-score` remain `manual_only` and must not appear in the live verified set.

If the command exits nonzero, stop. Fix the failing adapter through a new failing fixture test and rerun the deterministic test set before making one new live qualification attempt. Do not proceed to database work with fewer than five successes.

## Task 12: Back up and upgrade the existing product database in place

**Files:**
- No repository file changes expected; this is one controlled product operation.

- [ ] **Step 1: Stop this workspace's backend and frontend processes**

Identify only processes whose command line and working directory belong to `D:\Projects\Novel_Creater`, stop them, and verify ports 8000 and 5173 are not listening. Do not stop unrelated processes.

- [ ] **Step 2: Load the five MySQL values into memory and verify the approved local configuration file hash**

Use `D:\Projects\Novel_Creater\.env.local.json`. Require SHA-256:

```text
0e3ddb3683e9c878bc1b2d7244c643dc013716a194df9555e837b8000a35f032
```

Bridge only `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, `MYSQL_PASSWORD`, and `MYSQL_DB` to the backup/upgrade child processes and clear them in `finally`. Never print their values.

- [ ] **Step 3: Run the exact single backup-and-upgrade command once**

Use the existing Phase 7B private backup boundary and exact command:

```powershell
python -m backend.scripts.upgrade_product_database_v114 --database novel_creator_v113 --confirm-database novel_creator_v113 --backup-directory 'D:\NovelCreatorBackups\topic-center-v114-20260904' --mysqldump 'D:\Software\MySQL Server 8.4\bin\mysqldump.exe' --mysql 'D:\Software\MySQL Server 8.4\bin\mysql.exe'
```

Expected:

```text
database=novel_creator_v113
backup_filename_match=^phase7b-backup-[0-9a-f]{32}\.sql$
backup_sha256_length=64
from_schema=writer-core-v1.13.0
to_schema=writer-core-v1.14.0
added_tables=8
table_count=99
package_version=market-sources-v1.1.0
source_count=10
```

The filename and SHA are generated values reported by the command, never caller-supplied placeholders. Do not automatically retry. On any failure, stop services, preserve the emitted backup identity/output, and restore that exact backup before any further attempt.

- [ ] **Step 4: Verify schema and source inventory read-only**

Run a read-only diagnostic that confirms:

- schema metadata is `writer-core-v1.14.0` with current manifest hash;
- all 99 manifest tables exist;
- all eight topic tables exist;
- ten active market sources exist;
- exactly five source heads are `verified_public` and refresh-capable;
- no project, chapter, Canon, Planning, Provider, asset, or existing snapshot row was deleted or rewritten by the upgrade.

## Task 13: Run the real front-door flow and finish the branch

**Files:**
- Modify only if a verified defect is found; every defect starts with a failing deterministic test.

- [ ] **Step 1: Start backend and Vite against the upgraded existing database**

Use the in-memory five-value MySQL bridge for the backend. Start only loopback services at `127.0.0.1:8000` and `127.0.0.1:5173`. Confirm `/api/health` and the Topic Center page load successfully.

- [ ] **Step 2: Verify formal UI source capabilities before the one live run**

Without clicking refresh yet, confirm the five qualified sources expose enabled, correctly named manual-refresh buttons and the manual-only sources show “仅支持导入” with no enabled refresh button. The Playwright runner in Step 3 owns the sole refresh click for each verified source, avoiding cooldown conflicts.

- [ ] **Step 3: Run the real Provider Playwright acceptance once**

Run:

```powershell
node frontend/e2e/run-topic-center-live.mjs --base-url http://127.0.0.1:5173
```

Expected: the runner completes both AI discussions, saves a direction and candidate version 2, creates one project, and lands on a project Seed that is still “待确认”. The run uses the application's already configured default Provider.

- [ ] **Step 4: Manually inspect the created author-facing records**

Confirm from the UI:

- market works are readable and link to their official pages;
- evidence chips identify the selected source and snapshot;
- AI output is a normal discussion reply plus explicit direction/candidate suggestions;
- saved direction/candidate show complete Chinese fields and version history;
- project creation does not automatically confirm the Seed;
- no internal ID, hash, raw JSON, Provider secret, or fake-data label appears in the main author surface.

- [ ] **Step 5: Run final deterministic verification**

Run:

```powershell
python -m pytest -q backend/tests/unit/test_market_source_adapters.py backend/tests/unit/test_market_source_manifest.py backend/tests/unit/test_seed_market_sources.py backend/tests/unit/test_verify_live_market_sources.py backend/tests/unit/test_topic_discussion_prompt.py backend/tests/unit/test_topic_discussion_provider.py backend/tests/unit/test_topic_discussion_service.py backend/tests/unit/test_topic_library_service.py backend/tests/unit/test_topic_project_handoff.py backend/tests/unit/test_upgrade_product_database_v114.py backend/tests/api/test_market_source_routes.py backend/tests/api/test_topic_routes.py
node --test frontend/tests/unit/marketContracts.test.mjs frontend/tests/unit/marketSourceStore.test.mjs frontend/tests/unit/marketSnapshotWorks.test.mjs frontend/tests/unit/topicContracts.test.mjs frontend/tests/unit/topicCenterStore.test.mjs frontend/tests/unit/topicCenterView.test.mjs
npm --prefix frontend run build
git status --short --branch
```

Expected: all tests pass, build succeeds, and no unexpected tracked changes remain.

- [ ] **Step 6: Request code review and resolve findings**

Use the `requesting-code-review` skill. Fix only verified in-scope findings, each with a regression test. Repeat the focused verification after every fix.

- [ ] **Step 7: Finish and publish**

Use the `finishing-a-development-branch` skill. With user-selected integration, merge to `main`, rerun the final verification on `main`, and push `main` to `origin`. Do not delete the database backup or the existing product database.

## Plan self-review

- Spec coverage: source boundaries, ten registered candidate adapters, ten packaged source definitions, five-source gate, source isolation, immutable snapshots, real work display, blank/evidence discussions, explicit saves, candidate versioning, pending project Seed, single-database upgrade, and real Provider acceptance each map to a task.
- Scope: project metadata editing, Writer Core, automatic refresh, full-text crawling, old-data migration, and a second database remain excluded.
- Type consistency: adapter keys, `captureMode`, `adapterVersion`, five verified source keys, v1.1 package, and v1.14 schema names are consistent across backend, API, frontend, and acceptance tasks.
- Safety: all unit/browser development tests avoid real Provider calls; live source qualification precedes database writes; MySQL DDL is never described as transactional; the upgrade refuses partial schema and has one backup recovery boundary.
- Placeholder scan: runtime values such as the actual backup SHA are produced by an immediately preceding exact step and are not design placeholders.
