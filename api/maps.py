"""Rotas HTTP dos mapas offline."""

from __future__ import annotations

import asyncio
import mimetypes
import re
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.maps import downloads, extract, store  # noqa: E402
from core.maps import tools as _maps_tools  # noqa: F401,E402  (registra ferramentas)

router = APIRouter()
ASSETS = ROOT / "ui" / "front" / "map-assets"


def _map_or_404(map_id: str) -> dict:
    item = store.get_map(map_id)
    if not item:
        raise HTTPException(status_code=404, detail="mapa não encontrado")
    return item


def _base(request: Request) -> str:
    base = str(request.base_url)
    return base if base.endswith("/") else base + "/"


def _style(map_id: str, item: dict, base: str, theme: str) -> dict:
    dark = theme == "dark"
    background = "#10141c" if dark else "#f7f5f0"
    earth = "#171c26" if dark else "#f2efe9"
    water = "#16283d" if dark else "#a9cbe8"
    landcover = "#1b2a22" if dark else "#dce8cf"
    landuse = "#20242e" if dark else "#ece7da"
    road_casing = "#0e1117" if dark else "#d8d2c6"
    road = "#2b3240" if dark else "#ffffff"
    boundary = "#3a4353" if dark else "#b5ada0"
    label = "#d7dce5" if dark else "#333333"
    halo = background

    return {
        "version": 8,
        "name": f"Drix · {item.get('name', 'Mapa')}",
        "glyphs": base + "api/maps/assets/fonts/{fontstack}/{range}.pbf",
        "sources": {
            "drix": {
                "type": "vector",
                "url": f"pmtiles://{base}api/maps/{map_id}/tiles",
                "attribution": "© OpenStreetMap contributors · Protomaps · Drix",
            }
        },
        "layers": [
            {"id": "background", "type": "background",
             "paint": {"background-color": background}},
            {"id": "earth", "type": "fill", "source": "drix", "source-layer": "earth",
             "paint": {"fill-color": earth}},
            {"id": "water", "type": "fill", "source": "drix", "source-layer": "water",
             "paint": {"fill-color": water}},
            {"id": "landcover", "type": "fill", "source": "drix", "source-layer": "landcover",
             "paint": {"fill-color": landcover, "fill-opacity": 0.6}},
            {"id": "landuse", "type": "fill", "source": "drix", "source-layer": "landuse",
             "paint": {"fill-color": landuse, "fill-opacity": 0.7}},
            {"id": "roads-casing", "type": "line", "source": "drix", "source-layer": "roads",
             "paint": {
                 "line-color": road_casing,
                 "line-width": ["interpolate", ["linear"], ["zoom"], 5, 1.2, 10, 3.2, 14, 8, 16, 16],
                 "line-opacity": 0.75,
             }},
            {"id": "roads", "type": "line", "source": "drix", "source-layer": "roads",
             "paint": {
                 "line-color": road,
                 "line-width": ["interpolate", ["linear"], ["zoom"], 5, 0.5, 10, 2.0, 14, 6, 16, 13],
             }},
            {"id": "boundaries", "type": "line", "source": "drix", "source-layer": "boundaries",
             "paint": {"line-color": boundary, "line-width": 0.8, "line-opacity": 0.8}},
            {"id": "places", "type": "symbol", "source": "drix", "source-layer": "places",
             "layout": {
                 "text-field": ["coalesce", ["get", "name:pt"], ["get", "name"]],
                 "text-font": ["Noto Sans Regular"],
                 "text-size": ["interpolate", ["linear"], ["zoom"], 2, 10, 6, 12, 10, 14],
                 "text-max-width": 8,
                 "text-allow-overlap": False,
             },
             "paint": {
                 "text-color": label,
                 "text-halo-color": halo,
                 "text-halo-width": 1.2,
             }},
        ],
    }


def _iter_file(path: Path, start: int, length: int, chunk_size: int = 1024 * 1024):
    with open(path, "rb") as handle:
        handle.seek(start)
        remaining = length
        while remaining > 0:
            chunk = handle.read(min(chunk_size, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def _tile_headers(path: Path) -> dict:
    stat = path.stat()
    return {
        "Accept-Ranges": "bytes",
        "Content-Type": "application/octet-stream",
        "ETag": f'"{int(stat.st_mtime)}-{stat.st_size}"',
        "Cache-Control": "public, max-age=3600",
    }


@router.get("/maps")
async def maps_list():
    return {
        "maps": store.list_maps(),
        "info": store.info(),
        "presets": extract.presets_list(),
        "jobs": downloads.list_jobs(20),
        "uploads": downloads.list_uploads(),
        "enabled": bool((store.settings() or {}).get("enabled", True)),
    }


@router.get("/maps/jobs")
async def jobs_list():
    return {"jobs": downloads.list_jobs(50)}


@router.get("/maps/jobs/{job_id}")
async def job_status(job_id: str):
    job = downloads.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job não encontrado")
    return job


@router.post("/maps/jobs/{job_id}/cancel")
async def job_cancel(job_id: str):
    try:
        return downloads.cancel(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/maps/jobs/{job_id}/resume")
async def job_resume(job_id: str):
    try:
        return downloads.resume(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/maps/downloads")
async def start_download(req: Request):
    body = await req.json()
    try:
        return downloads.start_download(
            str(body.get("url") or ""),
            str(body.get("name") or ""),
            str(body.get("sha256") or ""),
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/maps/uploads")
async def uploads_list():
    return {"uploads": downloads.list_uploads()}


@router.post("/maps/uploads")
async def upload_start(req: Request):
    body = await req.json()
    try:
        return downloads.start_upload(str(body.get("filename") or ""), body.get("size"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/maps/uploads/{upload_id}")
async def upload_status(upload_id: str):
    try:
        return downloads.resume_upload(upload_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.put("/maps/uploads/{upload_id}")
async def upload_chunk(upload_id: str, request: Request, offset: int = 0):
    data = await request.body()
    if len(data) > 8 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="bloco muito grande")
    try:
        return downloads.append_upload(upload_id, offset, data)
    except downloads.OffsetError as exc:
        return JSONResponse(
            status_code=409,
            content={"detail": str(exc), "offset": exc.current},
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/maps/uploads/{upload_id}/finish")
async def upload_finish(upload_id: str, req: Request):
    try:
        body = await req.json()
    except Exception:
        body = {}
    try:
        return downloads.finish_upload(
            upload_id, str(body.get("name") or ""), str(body.get("sha256") or ""),
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/maps/uploads/{upload_id}")
async def upload_cancel(upload_id: str, purge: bool = False):
    try:
        return downloads.cancel_upload(upload_id, purge=purge)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/maps/extract/estimate")
async def extract_estimate(req: Request):
    body = await req.json()
    try:
        return await asyncio.to_thread(
            extract.estimate,
            preset=str(body.get("preset") or ""),
            bbox=body.get("bbox"),
            maxzoom=body.get("maxzoom"),
            source_url=str(body.get("source_url") or ""),
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/maps/extract")
async def extract_start(req: Request):
    body = await req.json()
    try:
        return downloads.start_extract(
            str(body.get("preset") or ""),
            maxzoom=body.get("maxzoom"),
            bbox=body.get("bbox"),
            name=str(body.get("name") or ""),
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/maps/assets/{path:path}")
async def map_asset(path: str):
    target = (ASSETS / path).resolve()
    if ASSETS.resolve() not in target.parents or not target.is_file():
        raise HTTPException(status_code=404, detail="asset não encontrado")
    media = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
    if target.suffix.lower() == ".pbf":
        media = "application/x-protobuf"
    return FileResponse(
        target, media_type=media,
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/maps/{map_id}/style.json")
async def map_style(map_id: str, request: Request, theme: str = "light"):
    item = _map_or_404(map_id)
    return _style(map_id, item, _base(request), "dark" if theme == "dark" else "light")


@router.get("/maps/{map_id}/tiles")
async def map_tiles(map_id: str, request: Request):
    item = _map_or_404(map_id)
    path = (store.files_dir() / item["filename"]).resolve()
    if path.parent != store.files_dir().resolve() or not path.is_file():
        raise HTTPException(status_code=404, detail="arquivo do mapa não encontrado")
    size = path.stat().st_size
    headers = _tile_headers(path)
    if request.headers.get("if-none-match") == headers["ETag"]:
        return Response(status_code=304, headers=headers)

    header = request.headers.get("range")
    if not header:
        return StreamingResponse(
            _iter_file(path, 0, size),
            headers={**headers, "Content-Length": str(size)},
        )
    match = re.match(r"bytes=(\d*)-(\d*)$", header.strip())
    if not match:
        return Response(status_code=416, headers={**headers, "Content-Range": f"bytes */{size}"})
    start_text, end_text = match.groups()
    if not start_text and not end_text:
        return Response(status_code=416, headers={**headers, "Content-Range": f"bytes */{size}"})
    if not start_text:
        length = int(end_text)
        start = max(0, size - length)
        end = size - 1
    else:
        start = int(start_text)
        end = min(int(end_text), size - 1) if end_text else size - 1
    if start >= size or start > end:
        return Response(status_code=416, headers={**headers, "Content-Range": f"bytes */{size}"})
    length = end - start + 1
    return StreamingResponse(
        _iter_file(path, start, length),
        status_code=206,
        headers={
            **headers,
            "Content-Range": f"bytes {start}-{end}/{size}",
            "Content-Length": str(length),
        },
    )


@router.head("/maps/{map_id}/tiles")
async def map_tiles_head(map_id: str):
    item = _map_or_404(map_id)
    path = (store.files_dir() / item["filename"]).resolve()
    if path.parent != store.files_dir().resolve() or not path.is_file():
        raise HTTPException(status_code=404, detail="arquivo do mapa não encontrado")
    headers = _tile_headers(path)
    headers["Content-Length"] = str(path.stat().st_size)
    return Response(status_code=200, headers=headers)


@router.get("/maps/{map_id}")
async def map_info(map_id: str):
    return _map_or_404(map_id)


@router.delete("/maps/{map_id}")
async def map_delete(map_id: str):
    try:
        if not store.delete_map(map_id):
            raise HTTPException(status_code=404, detail="mapa não encontrado")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True}
