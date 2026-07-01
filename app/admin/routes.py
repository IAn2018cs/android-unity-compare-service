from __future__ import annotations

from html import escape

from fastapi import APIRouter, Body, Depends
from fastapi.responses import HTMLResponse, JSONResponse

from app.auth.deps import get_auth_service, require_admin_session
from app.auth.service import ApiKey, AuthService

admin_router = APIRouter()


def _rows(keys: list[ApiKey]) -> str:
    if not keys:
        return "<tr><td colspan='5'>暂无 API Key</td></tr>"
    rows = []
    for key in keys:
        status = "已吊销" if key.revoked else "启用中"
        action = "" if key.revoked else f" <button onclick=\"revokeKey('{escape(key.id)}')\">吊销</button>"
        rows.append(
            f"<tr><td>{escape(key.name)}</td><td><code>{escape(key.key_prefix)}...</code></td>"
            f"<td>{escape(key.created_at)}</td><td>{escape(key.last_used_at or '-')}</td><td>{status}{action}</td></tr>"
        )
    return "\n".join(rows)


@admin_router.get("/admin", response_class=HTMLResponse)
async def admin_page(_admin=Depends(require_admin_session), service: AuthService = Depends(get_auth_service)):
    return HTMLResponse(
        ADMIN_HTML.replace("__ROWS__", _rows(service.list_api_keys()))
    )


@admin_router.post("/admin/api-keys")
async def create_api_key(
    payload: dict = Body(default_factory=dict),
    _admin=Depends(require_admin_session),
    service: AuthService = Depends(get_auth_service),
):
    name = str(payload.get("name") or "").strip() if isinstance(payload, dict) else ""
    if not name:
        return JSONResponse({"error": "INVALID", "message": "缺少 name"}, status_code=400)
    record, raw = service.create_api_key(name)
    return JSONResponse(
        {"id": record.id, "name": record.name, "key": raw, "keyPrefix": record.key_prefix, "createdAt": record.created_at},
        status_code=201,
    )


@admin_router.post("/admin/api-keys/{key_id}/revoke")
async def revoke_api_key(
    key_id: str,
    _admin=Depends(require_admin_session),
    service: AuthService = Depends(get_auth_service),
):
    if not service.revoke_api_key(key_id):
        return JSONResponse({"error": "NOT_FOUND", "message": "Key 不存在或已吊销"}, status_code=404)
    return {"ok": True}


ADMIN_HTML = """
<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Android Unity Compare Service 管理后台</title>
<style>
body{font-family:system-ui,"PingFang SC",sans-serif;margin:2rem;background:#101114;color:#eee}
input,button{padding:.5rem .7rem;border-radius:6px;border:1px solid #333;background:#181a20;color:#eee}
button{cursor:pointer;background:#3454d1;border:0}table{width:100%;border-collapse:collapse;margin-top:1rem}
td,th{border-bottom:1px solid #2b2d33;padding:.6rem;text-align:left}code{color:#86efac}
.new{background:#13251a;border:1px solid #285c3d;padding:1rem;margin-top:1rem;word-break:break-all}
a{color:#aaa}
</style>
</head>
<body>
<h1>API Key 管理</h1>
<p><input id="name" placeholder="Key 名称"> <button onclick="createKey()">创建 Key</button> <a href="/auth/logout">退出</a></p>
<div id="new" class="new" hidden></div>
<table><thead><tr><th>名称</th><th>前缀</th><th>创建时间</th><th>最后使用</th><th>状态</th></tr></thead><tbody>__ROWS__</tbody></table>
<script>
async function createKey(){
  const name=document.getElementById('name').value.trim();
  if(!name){alert('请输入名称');return}
  const r=await fetch('/admin/api-keys',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name})});
  if(!r.ok){alert('创建失败');return}
  const d=await r.json(); const box=document.getElementById('new');
  box.hidden=false; box.innerHTML='明文仅显示一次：<code>'+d.key+'</code>';
}
async function revokeKey(id){
  if(!confirm('确认吊销？')) return;
  const r=await fetch('/admin/api-keys/'+id+'/revoke',{method:'POST'});
  if(r.ok) location.reload(); else alert('吊销失败');
}
</script>
</body>
</html>
"""
