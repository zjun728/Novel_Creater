"""Provider 配置与任务模型绑定"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from backend.database import fetchone, fetchall, execute
from .helpers import convert_row, convert_rows, to_snake
import uuid, time, json

router = APIRouter(tags=["providers"])

MODEL_BINDING_FIELDS = [
    "writing_model_id",
    "brainstorm_model_id",
    "outline_model_id",
    "audit_model_id",
    "summary_model_id",
    "extraction_model_id",
    "market_model_id",
    "polish_model_id",
]

MODEL_BINDING_CAMEL_FIELDS = [
    "writingModelId",
    "brainstormModelId",
    "outlineModelId",
    "auditModelId",
    "summaryModelId",
    "extractionModelId",
    "marketModelId",
    "polishModelId",
]

DEFAULT_TASK_PROVIDER_NAME = "联通云-DeepSeek-V4-Flash"
DEFAULT_TASK_MODEL_NAME = "DeepSeek-V4-Flash"

class ProviderCreate(BaseModel):
    name: str
    providerType: str = "openai-compatible"
    baseURL: str = ""
    apiKey: str = ""
    model: str = ""
    stream: bool = True
    maxContextTokens: int = 200000
    maxOutputTokens: int = 4096
    temperature: float = 0.8
    topP: float = 0.9
    supportsJSON: bool = True
    supportsStreaming: bool = True
    notes: str = ""
    thinking: Optional[dict] = None

class ProviderUpdate(BaseModel):
    name: Optional[str] = None
    providerType: Optional[str] = None
    baseURL: Optional[str] = None
    apiKey: Optional[str] = None
    model: Optional[str] = None
    stream: Optional[bool] = None
    maxContextTokens: Optional[int] = None
    maxOutputTokens: Optional[int] = None
    temperature: Optional[float] = None
    topP: Optional[float] = None
    supportsJSON: Optional[bool] = None
    supportsStreaming: Optional[bool] = None
    notes: Optional[str] = None
    thinking: Optional[dict] = None

class BindingsUpdate(BaseModel):
    writingModelId: Optional[str] = None
    brainstormModelId: Optional[str] = None
    outlineModelId: Optional[str] = None
    auditModelId: Optional[str] = None
    summaryModelId: Optional[str] = None
    extractionModelId: Optional[str] = None
    marketModelId: Optional[str] = None
    polishModelId: Optional[str] = None

# --- Providers ---
@router.get("/providers")
async def list_providers():
    rows = await fetchall("SELECT * FROM provider_profiles ORDER BY created_at")
    return convert_rows(rows)

@router.post("/providers")
async def create_provider(data: ProviderCreate):
    now = int(time.time() * 1000)
    pid = str(uuid.uuid4())
    thinking_json = json.dumps(data.thinking) if data.thinking else None
    sql = """INSERT INTO provider_profiles (id, name, provider_type, base_url, api_key, model,
             stream, max_context_tokens, max_output_tokens, temperature, top_p,
             supports_json, supports_streaming, notes, thinking, created_at, updated_at)
             VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"""
    await execute(sql, (pid, data.name, data.providerType, data.baseURL, data.apiKey, data.model,
                        int(data.stream), data.maxContextTokens, data.maxOutputTokens,
                        data.temperature, data.topP, int(data.supportsJSON),
                        int(data.supportsStreaming), data.notes, thinking_json, now, now))
    return convert_row(await fetchone("SELECT * FROM provider_profiles WHERE id=%s", (pid,)))

@router.put("/providers/{pid}")
async def update_provider(pid: str, data: ProviderUpdate):
    sets, args = [], []
    for k, v in data.dict(exclude_none=True).items():
        col = to_snake(k)
        if k == "thinking":
            sets.append("thinking=%s")
            args.append(json.dumps(v) if v else None)
        elif isinstance(v, bool):
            sets.append(f"{col}=%s")
            args.append(int(v))
        else:
            sets.append(f"{col}=%s")
            args.append(v)
    if not sets:
        return convert_row(await fetchone("SELECT * FROM provider_profiles WHERE id=%s", (pid,)))
    sets.append("updated_at=%s")
    args.append(int(time.time() * 1000))
    args.append(pid)
    await execute(f"UPDATE provider_profiles SET {', '.join(sets)} WHERE id=%s", args)
    return convert_row(await fetchone("SELECT * FROM provider_profiles WHERE id=%s", (pid,)))

@router.delete("/providers/{pid}")
async def delete_provider(pid: str):
    await execute("DELETE FROM provider_profiles WHERE id=%s", (pid,))
    return {"ok": True}

# --- Task Model Bindings ---
@router.get("/projects/{pid}/bindings")
async def get_bindings(pid: str):
    rows = await fetchall("SELECT * FROM task_model_bindings WHERE project_id=%s", (pid,))
    r = convert_rows(rows)
    return r[0] if r else None

@router.get("/projects/{pid}/bindings/status")
async def get_bindings_status(pid: str):
    project = await fetchone("SELECT * FROM projects WHERE id=%s", (pid,))
    if not project:
        raise HTTPException(404, "项目不存在")

    row = await fetchone("SELECT * FROM task_model_bindings WHERE project_id=%s", (pid,))
    binding = convert_row(row)
    has_binding = bool(row and _has_any_model_binding(row))
    return {
        "projectId": pid,
        "hasBinding": has_binding,
        "binding": binding,
        "inherited": bool(row and row.get("inherited_from_project_id")),
        "inheritedFromProjectId": row.get("inherited_from_project_id") if row else None,
        "inheritedFromProjectTitle": row.get("inherited_from_project_title") if row else "",
        "inheritedFromUpdatedAt": row.get("inherited_from_updated_at") if row else None,
        "message": _binding_status_message(row),
    }

@router.put("/projects/{pid}/bindings")
async def save_bindings(pid: str, data: BindingsUpdate):
    now = int(time.time() * 1000)
    rows = await fetchall("SELECT * FROM task_model_bindings WHERE project_id=%s", (pid,))
    d = data.dict()
    if rows:
        sets = [f"{to_snake(k)}=%s" for k in d]
        sets.extend([
            "inherited_from_project_id=%s",
            "inherited_from_project_title=%s",
            "inherited_from_updated_at=%s",
        ])
        if sets:
            sets.append("updated_at=%s")
            args = list(d.values()) + [None, "", None, now, rows[0]['id']]
            await execute(f"UPDATE task_model_bindings SET {', '.join(sets)} WHERE id=%s", args)
    else:
        bid = str(uuid.uuid4())
        vals = [bid, pid] + [d.get(k) for k in MODEL_BINDING_CAMEL_FIELDS]
        await execute(
            """
            INSERT INTO task_model_bindings
              (id, project_id, writing_model_id, brainstorm_model_id, outline_model_id, audit_model_id,
               summary_model_id, extraction_model_id, market_model_id, polish_model_id,
               inherited_from_project_id, inherited_from_project_title, inherited_from_updated_at,
               created_at, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            vals + [None, "", None, now, now],
        )
    return await get_bindings(pid)


async def find_latest_saved_task_model_binding(exclude_project_id: Optional[str] = None):
    where = [
        "(" + " OR ".join([f"b.{field} IS NOT NULL" for field in MODEL_BINDING_FIELDS]) + ")"
    ]
    args = []
    if exclude_project_id:
        where.append("b.project_id<>%s")
        args.append(exclude_project_id)
    row = await fetchone(
        f"""
        SELECT b.*, p.title AS source_project_title
        FROM task_model_bindings b
        LEFT JOIN projects p ON p.id=b.project_id
        WHERE {' AND '.join(where)}
        ORDER BY b.updated_at DESC
        LIMIT 1
        """,
        tuple(args),
    )
    return row


async def inherit_latest_task_model_bindings(pid: str):
    latest = await find_latest_saved_task_model_binding(exclude_project_id=pid)
    default_provider = await find_default_task_model_provider()
    if not latest and not default_provider:
        return None

    now = int(time.time() * 1000)
    bid = str(uuid.uuid4())
    values = [default_provider.get("id") for _ in MODEL_BINDING_FIELDS] if default_provider else [latest.get(field) for field in MODEL_BINDING_FIELDS]
    await execute(
        """
        INSERT INTO task_model_bindings
          (id, project_id, writing_model_id, brainstorm_model_id, outline_model_id, audit_model_id,
           summary_model_id, extraction_model_id, market_model_id, polish_model_id,
           inherited_from_project_id, inherited_from_project_title, inherited_from_updated_at,
           created_at, updated_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        [bid, pid] + values + [
            latest.get("project_id") if latest else None,
            latest.get("source_project_title") if latest else "",
            latest.get("updated_at") if latest else None,
            now,
            now,
        ],
    )
    return await get_bindings(pid)


async def find_default_task_model_provider():
    provider = await fetchone(
        """
        SELECT *
        FROM provider_profiles
        WHERE model=%s AND name=%s
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        (DEFAULT_TASK_MODEL_NAME, DEFAULT_TASK_PROVIDER_NAME),
    )
    if provider:
        return provider
    return await fetchone(
        """
        SELECT *
        FROM provider_profiles
        WHERE model=%s
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        (DEFAULT_TASK_MODEL_NAME,),
    )


def _has_any_model_binding(row: dict) -> bool:
    return any(row.get(field) for field in MODEL_BINDING_FIELDS)


def _binding_status_message(row: Optional[dict]) -> str:
    if not row or not _has_any_model_binding(row):
        return "当前项目未配置任务模型映射：请先配置模型。"
    if row.get("inherited_from_project_id"):
        title = row.get("inherited_from_project_title") or "上一个项目"
        updated_at = row.get("inherited_from_updated_at") or ""
        return f"已继承上一个项目模型配置：{title} / {updated_at}"
    return "当前项目已配置任务模型映射。"
