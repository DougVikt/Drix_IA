"""Ferramentas de mapa expostas ao agente.

As ferramentas de leitura são seguras; download, extração e exclusão passam
pelo sistema de permissões (``ask`` por padrão) e pelo cache local de decisões.
"""

from __future__ import annotations

import json

from .. import tools
from . import downloads, extract, store


def _json(data) -> str:
    return json.dumps(data, ensure_ascii=False)


def _find(args: dict) -> dict:
    map_id = str(args.get("map_id") or "").strip()
    if map_id:
        return store.get_map(map_id)
    query = str(args.get("name") or args.get("query") or "").strip()
    if query:
        return store.find_map(query)
    return {}


def _tool_list(args: dict, ctx) -> str:
    return _json({"maps": store.list_maps(100), "info": store.info()})


def _tool_info(args: dict, ctx) -> str:
    item = _find(args)
    if not item:
        return "ERROR: mapa não encontrado"
    return _json(item)


def _tool_status(args: dict, ctx) -> str:
    return _json({
        "jobs": downloads.list_jobs(20),
        "uploads": downloads.list_uploads(),
        "info": store.info(),
    })


def _tool_search(args: dict, ctx) -> str:
    query = store.normalize(str(args.get("query") or args.get("name") or ""))
    if not query:
        return "ERROR: informe 'query'."
    hits = []
    for item in store.list_maps(500):
        haystack = store.normalize(
            " ".join(str(item.get(key) or "") for key in ("id", "name", "source_url"))
        )
        if query in haystack:
            hits.append(item)
    if not hits:
        found = store.find_map(query)
        if found:
            hits.append(found)
    return _json({"query": query, "count": len(hits), "maps": hits})


def _tool_open(args: dict, ctx) -> str:
    item = _find(args)
    if not item:
        return "ERROR: mapa não encontrado"
    return _json({
        "map_id": item["id"],
        "name": item["name"],
        "style_url": f"/api/maps/{item['id']}/style.json",
        "tiles_url": f"/api/maps/{item['id']}/tiles",
        "zoom": item.get("zoom_label"),
        "size": item.get("size_label"),
        "center": item.get("center"),
        "center_zoom": item.get("center_zoom"),
    })


def _tool_download(args: dict, ctx) -> str:
    url = str(args.get("url") or "").strip()
    if not url:
        return "ERROR: informe a URL de um arquivo .pmtiles."
    job = downloads.start_download(
        url,
        str(args.get("name") or ""),
        str(args.get("sha256") or ""),
    )
    return _json(job)


def _tool_extract(args: dict, ctx) -> str:
    preset = str(args.get("preset") or "").strip()
    bbox = args.get("bbox")
    if not preset and not bbox:
        return "ERROR: informe um preset ou uma bbox."
    job = downloads.start_extract(
        preset,
        maxzoom=args.get("maxzoom"),
        bbox=bbox,
        name=str(args.get("name") or ""),
        source_url=str(args.get("source_url") or ""),
    )
    return _json(job)


def _tool_delete(args: dict, ctx) -> str:
    item = _find(args)
    if not item:
        return "ERROR: mapa não encontrado"
    store.delete_map(item["id"])
    return _json({"deleted": item["id"], "name": item.get("name")})


tools.register(tools.Tool(
    "maps_list",
    "Lista os mapas offline instalados, presets disponíveis e espaço em disco.",
    {"type": "object", "properties": {}},
    _tool_list,
))

tools.register(tools.Tool(
    "maps_info",
    "Mostra detalhes de um mapa offline instalado (zoom, cobertura, tamanho).",
    {
        "type": "object",
        "properties": {
            "map_id": {"type": "string", "description": "ID do mapa."},
            "name": {"type": "string", "description": "Nome ou parte do nome."},
        },
    },
    _tool_info,
))

tools.register(tools.Tool(
    "maps_status",
    "Mostra o andamento de downloads, extrações e importações de mapas.",
    {"type": "object", "properties": {}},
    _tool_status,
))

tools.register(tools.Tool(
    "maps_search",
    "Procura mapas offline instalados pelo nome ou pela origem.",
    {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Nome ou termo de busca."},
        },
        "required": ["query"],
    },
    _tool_search,
))

tools.register(tools.Tool(
    "maps_open",
    "Abre um mapa offline no visualizador e devolve a URL do estilo MapLibre.",
    {
        "type": "object",
        "properties": {
            "map_id": {"type": "string", "description": "ID do mapa."},
            "name": {"type": "string", "description": "Nome ou parte do nome."},
        },
    },
    _tool_open,
))

tools.register(tools.Tool(
    "maps_download",
    "Baixa um arquivo PMTiles de um link https e adiciona ao catálogo local.",
    {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Link direto do arquivo .pmtiles."},
            "name": {"type": "string", "description": "Nome amigável do mapa."},
            "sha256": {"type": "string", "description": "Hash esperado (opcional)."},
        },
        "required": ["url"],
    },
    _tool_download,
    danger="network",
))

tools.register(tools.Tool(
    "maps_extract",
    "Cria um recorte PMTiles a partir de um preset do Brasil ou de uma bbox.",
    {
        "type": "object",
        "properties": {
            "preset": {"type": "string", "description": "Chave do preset (ex.: brasil)."},
            "bbox": {
                "type": "array",
                "items": {"type": "number"},
                "description": "min_lon, min_lat, max_lon, max_lat.",
            },
            "maxzoom": {"type": "integer", "minimum": 0, "maximum": 16},
            "name": {"type": "string", "description": "Nome do mapa gerado."},
            "source_url": {"type": "string", "description": "Build de origem (opcional)."},
        },
    },
    _tool_extract,
    danger="network",
))

tools.register(tools.Tool(
    "maps_delete",
    "Remove um mapa offline do catálogo e apaga o arquivo local.",
    {
        "type": "object",
        "properties": {
            "map_id": {"type": "string", "description": "ID do mapa."},
            "name": {"type": "string", "description": "Nome ou parte do nome."},
        },
    },
    _tool_delete,
    danger="write",
))
