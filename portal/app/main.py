from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, Response
import markdown
import httpx
import os

app = FastAPI(docs_url=None, redoc_url=None)

# URL directe du service API Cloud Run (interne GCP, pas de round-trip LB)
API_URL = os.getenv("API_URL", "https://threat-hunting-api-3gqrf5kr2q-ew.a.run.app")

@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_api(path: str, request: Request):
    """Proxy transparent vers l'API — permet d'accéder via l'URL directe du portail."""
    qs = request.url.query
    target = f"{API_URL}/{path}" + (f"?{qs}" if qs else "")
    headers = {k: v for k, v in request.headers.items() if k.lower() != "host"}
    body = await request.body()
    async with httpx.AsyncClient(verify=False, timeout=30) as client:
        resp = await client.request(request.method, target, headers=headers, content=body)
    resp_headers = {k: v for k, v in resp.headers.items()
                    if k.lower() not in ("transfer-encoding", "content-encoding")}
    return Response(content=resp.content, status_code=resp.status_code, headers=resp_headers)

# Mount static files (css, js, images)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Mount Threat Interface SPA (HTML/JS/CSS)
app.mount("/interface", StaticFiles(directory="/app/interface", html=True), name="interface")

templates = Jinja2Templates(directory="templates")

DOCS_PATH = "/docs_mount"

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """Landing page with tool links"""
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/docs", response_class=HTMLResponse)
async def list_docs(request: Request):
    """List available documentation files"""
    file_list = []
    if os.path.exists(DOCS_PATH):
        for f in sorted(os.listdir(DOCS_PATH)):
            f_lower = f.lower()
            if f_lower.endswith(".md"):
                file_list.append({"name": f, "type": "DOC", "desc": "Markdown Documentation", "action": "READ"})
            elif f_lower.endswith((".png", ".jpg", ".jpeg")):
                file_list.append({"name": f, "type": "IMG", "desc": "Image File", "action": "VIEW"})
            elif f_lower.endswith(".drawio"):
                file_list.append({"name": f, "type": "XML", "desc": "Draw.io Diagram", "action": "DL"})

    return templates.TemplateResponse("docs_list.html", {"request": request, "files": file_list})

# Mount docs directory for raw file access
app.mount("/files", StaticFiles(directory=DOCS_PATH), name="files")

@app.get("/docs/{filename}", response_class=HTMLResponse)
async def view_doc(request: Request, filename: str):
    """Render a specific file (Markdown or Image)"""
    if not os.path.exists(os.path.join(DOCS_PATH, filename)):
        raise HTTPException(status_code=404, detail="Document not found")
    
    # 1. Markdown: Render to HTML
    if filename.lower().endswith(".md"):
        with open(os.path.join(DOCS_PATH, filename), "r", encoding="utf-8") as f:
            content = f.read()
        html_content = markdown.markdown(content, extensions=['fenced_code', 'tables'])
    
    # 2. Images: Show in viewer
    elif filename.lower().endswith((".png", ".jpg", ".jpeg")):
        html_content = f'<div style="text-align: center;"><img src="/files/{filename}" style="max-width: 100%; border: 1px solid #333; border-radius: 4px;"></div>'

    # 3. Draw.io: Embed Viewer
    elif filename.lower().endswith(".drawio"):
         html_content = (
            f'<div style="text-align: center; margin-bottom: 20px;">'
            f'<div class="mxgraph" style="max-width:100%;border:1px solid transparent;" '
            f'data-mxgraph=\'{{"highlight":"#0000ff","nav":true,"resize":true,"toolbar":"zoom layers tags lightbox","edit":"_blank","url":"/files/{filename}"}}\'></div>'
            f'<script type="text/javascript" src="https://viewer.diagrams.net/js/viewer-static.min.js"></script>'
            f'<div style="margin-top:10px;"><a href="/files/{filename}" download class="run-btn" style="text-decoration:none; padding: 5px 10px; font-size: 12px;">DOWNLOAD SOURCE</a></div>'
            f'</div>'
        )

    # 4. Others: Show download link
    else:
        html_content = (
            f'<div style="text-align: center; padding: 50px;">'
            f'<h3>Preview not available for this file type.</h3>'
            f'<a href="/files/{filename}" download class="run-btn" style="text-decoration:none; padding: 10px 20px;">DOWNLOAD FILE</a>'
            f'</div>'
        )
    
    return templates.TemplateResponse("doc_viewer.html", {
        "request": request, 
        "content": html_content, 
        "title": filename
    })
