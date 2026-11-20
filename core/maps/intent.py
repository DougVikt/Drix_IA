"""Roteador determinístico de comandos de mapa no chat.

O chat rápido da Drix não usa o loop de ferramentas. Em vez de trocar o
mecanismo de resposta, reconhecemos comandos curtos e inequívocos ("abrir mapa
Brasil", "quais mapas", "apagar mapa X") antes de chamar o modelo. A resposta é
um evento ``ui`` que abre o painel certo; nada é baixado ou apagado sem uma
confirmação explícita na interface.
"""

from __future__ import annotations

from . import extract, store

_OPEN_VERBS = {
    "abrir", "abra", "abre", "mostrar", "mostre", "mostra", "visualizar",
    "visualize", "exibir", "exiba", "ver", "veja",
}
_DOWNLOAD_VERBS = {
    "baixar", "baixe", "baixa", "extrair", "extraia", "instalar", "instale",
    "adicionar", "adicione", "obter", "obtenha",
}
_DELETE_VERBS = {
    "apagar", "apague", "apaga", "remover", "remova", "remove", "excluir",
    "exclua", "deletar", "delete", "deleta", "limpar", "limpe",
}
_IMPORT_VERBS = {"importar", "importe", "importa"}
_STATUS_VERBS = {"status", "progresso", "andamento"}
_INFO_VERBS = {"info", "informacoes", "detalhes", "ficha", "resumo"}
_LIST_VERBS = {"listar", "liste", "lista", "quais", "qual"}

_STOPWORDS = {
    "mapa", "mapas", "offline", "pmtiles", "maplibre", "o", "a", "os", "as",
    "um", "uma", "uns", "umas", "de", "do", "da", "dos", "das", "no", "na",
    "nos", "nas", "em", "para", "pra", "por", "favor", "meu", "minha", "meus",
    "minhas", "instalado", "instalados", "instalada", "instaladas", "que",
    "tem", "tenho", "quais", "qual", "mostra", "mostre", "mostrar", "ver",
    "veja", "visualizar", "abrir", "abra", "abre", "baixar", "baixe", "baixa",
    "extrair", "extraia", "instalar", "instale", "adicionar", "adicione",
    "apagar", "apague", "apaga", "remover", "remova", "remove", "excluir",
    "exclua", "deletar", "delete", "deleta", "limpar", "limpe", "status",
    "progresso", "andamento", "info", "informacoes", "detalhes", "ficha",
    "resumo", "listar", "liste", "lista", "quero", "gostaria", "pode", "poderia",
    "agora", "aqui", "este", "esta", "desse", "desse", "deste", "desta",
}


def _target(tokens: list[str]) -> str:
    words = [token for token in tokens if token not in _STOPWORDS and len(token) > 1]
    return " ".join(words).strip()


def match_preset(text: str) -> dict:
    norm = store.normalize(text)
    if not norm:
        return {}
    padded = f" {norm} "
    best = {}
    best_score = 0
    for item in extract.presets_list():
        candidates = [
            str(item.get("key") or "").replace("-", " "),
            str(item.get("name") or ""),
        ]
        candidates.extend(item.get("aliases") or [])
        for candidate in candidates:
            clean = store.normalize(candidate)
            if not clean:
                continue
            if f" {clean} " not in padded:
                continue
            # Frases mais longas são mais específicas ("brasil detalhado"
            # vence "brasil").
            score = len(clean) + 20
            if score > best_score:
                best, best_score = item, score
    return best


def detect(text: str) -> dict | None:
    raw = str(text or "").strip()
    if not raw or len(raw) > 180:
        return None
    norm = store.normalize(raw)
    tokens = norm.split()
    if not tokens:
        return None
    if not any(word in norm for word in ("mapa", "mapas", "pmtiles", "maplibre")):
        return None

    first = tokens[0]
    if first in _DELETE_VERBS:
        action = "delete"
    elif first in _DOWNLOAD_VERBS:
        action = "download"
    elif first in _IMPORT_VERBS:
        action = "import"
    elif first in _STATUS_VERBS:
        action = "status"
    elif first in _INFO_VERBS:
        action = "info"
    elif first in _OPEN_VERBS:
        action = "list" if "mapas" in tokens and "mapa" not in tokens else "open"
    elif first in _LIST_VERBS:
        action = "list"
    elif first in {"mapa", "mapas"}:
        if not any(word in tokens for word in ("instalado", "instalados", "offline", "tenho")):
            return None
        action = "list"
    else:
        return None

    target = _target(tokens)
    preset = match_preset(norm)
    found = store.find_map(target) if target else {}

    if action in {"list", "status"}:
        return {
            "type": "ui",
            "action": "open_panel",
            "view": "library",
            "reply": (
                "Abrindo o painel de mapas offline."
                if action == "list"
                else "Abrindo o andamento dos mapas."
            ),
        }

    if action == "import":
        return {
            "type": "ui",
            "action": "open_panel",
            "view": "import",
            "reply": "Abrindo a importação de mapas. Escolha o arquivo .pmtiles.",
        }

    if action == "delete":
        if found:
            return {
                "type": "ui",
                "action": "confirm_delete",
                "map_id": found["id"],
                "name": found["name"],
                "reply": (
                    f"Encontrei “{found['name']}”. Confirme a exclusão no painel "
                    "para apagar o arquivo."
                ),
            }
        return {
            "type": "ui",
            "action": "open_panel",
            "view": "library",
            "query": target,
            "reply": (
                f"Não encontrei um mapa instalado com “{target}”."
                if target else "Abrindo o painel para você escolher o mapa."
            ),
        }

    if action == "download":
        if preset:
            return {
                "type": "ui",
                "action": "open_panel",
                "view": "download",
                "preset": preset["key"],
                "reply": (
                    f"Preset “{preset['name']}” selecionado. Confirme o download "
                    "no painel de mapas."
                ),
            }
        return {
            "type": "ui",
            "action": "open_panel",
            "view": "download",
            "query": target,
            "reply": "Escolha um preset do Brasil ou informe um link .pmtiles para baixar.",
        }

    # open / info
    if found:
        return {
            "type": "ui",
            "action": "open_map",
            "map_id": found["id"],
            "name": found["name"],
            "reply": f"Abrindo o mapa “{found['name']}”.",
        }
    if preset:
        return {
            "type": "ui",
            "action": "open_panel",
            "view": "download",
            "preset": preset["key"],
            "reply": (
                f"O mapa “{preset['name']}” ainda não está instalado. "
                "Confirme o download no painel."
            ),
        }
    return {
        "type": "ui",
        "action": "open_panel",
        "view": "library",
        "query": target,
        "reply": (
            f"Não encontrei um mapa instalado com “{target}”."
            if target else "Abrindo o painel de mapas offline."
        ),
    }
