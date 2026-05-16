"""Provider 配置与任务模型绑定"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from database import fetchone, fetchall, execute
from .helpers import convert_row, convert_rows, to_snake
import uuid, time, json

router = APIRouter(tags=["providers"])

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

@router.put("/projects/{pid}/bindings")
async def save_bindings(pid: str, data: BindingsUpdate):
    now = int(time.time() * 1000)
    rows = await fetchall("SELECT * FROM task_model_bindings WHERE project_id=%s", (pid,))
    d = data.dict(exclude_none=True)
    if rows:
        sets = [f"{to_snake(k)}=%s" for k in d]
        sets.append("updated_at=%s")
        args = list(d.values()) + [now, rows[0]['id']]
        await execute(f"UPDATE task_model_bindings SET {', '.join(sets)} WHERE id=%s", args)
    else:
        bid = str(uuid.uuid4())
        vals = [bid, pid] + [d.get(k) for k in ['writingModelId','brainstormModelId','outlineModelId','auditModelId','summaryModelId','extractionModelId','marketModelId','polishModelId']]
        await execute(f"INSERT INTO task_model_bindings (id, project_id, writing_model_id, brainstorm_model_id, outline_model_id, audit_model_id, summary_model_id, extraction_model_id, market_model_id, polish_model_id, created_at, updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", vals + [now, now])
    return await get_bindings(pid)
