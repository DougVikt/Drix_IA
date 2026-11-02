import httpx


class DrixClient:
    def __init__(self, base_url: str = "http://localhost:8000", api_key: str = ""):
        self.base_url = base_url.rstrip("/")
        self._headers = {"Content-Type": "application/json"}
        if api_key:
            self._headers["X-Drix-Key"] = api_key
        self._http = httpx.Client(base_url=self.base_url, headers=self._headers, timeout=120)

    # ─── Chat ─────────────────────────────────────────

    def chat(self, message: str, workspace: str = "default") -> dict:
        r = self._http.post("/api/chat", json={"message": message, "workspace": workspace})
        return r.json()

    # ─── Engine ───────────────────────────────────────

    def engine_status(self) -> dict:
        return self._http.get("/api/engine").json()

    def engine_start(self) -> dict:
        return self._http.post("/api/engine/start").json()

    def engine_stop(self) -> dict:
        return self._http.post("/api/engine/stop").json()

    def engine_restart(self) -> dict:
        return self._http.post("/api/engine/restart").json()

    # ─── Workspaces ───────────────────────────────────

    def list_workspaces(self) -> list:
        return self._http.get("/api/workspaces").json().get("workspaces", [])

    def create_workspace(self, name: str) -> dict:
        return self._http.post("/api/workspaces", json={"name": name}).json()

    def delete_workspace(self, name: str) -> dict:
        return self._http.delete(f"/api/workspaces/{name}").json()

    def get_messages(self, workspace: str, limit: int = 50) -> list:
        return self._http.get(f"/api/workspaces/{workspace}/messages", params={"limit": limit}).json().get("messages", [])

    def select_workspace(self, name: str) -> dict:
        return self._http.post(f"/api/workspaces/{name}/select").json()

    # ─── Models ───────────────────────────────────────

    def list_models(self) -> dict:
        return self._http.get("/api/models").json()

    def pull_model(self, name: str) -> dict:
        return self._http.post("/api/models/pull", json={"name": name}).json()

    def select_model(self, name: str) -> dict:
        return self._http.post("/api/models/select", json={"name": name}).json()

    def delete_model(self, name: str) -> dict:
        return self._http.delete(f"/api/models/{name}").json()

    # ─── Memory ───────────────────────────────────────

    def memory_search(self, query: str, limit: int = 5) -> dict:
        return self._http.post("/api/memory/search", json={"query": query, "limit": limit}).json()

    def memory_all(self) -> dict:
        return self._http.get("/api/memory/all").json()

    def memory_reset(self) -> dict:
        return self._http.post("/api/memory/reset").json()

    # ─── Web Search ───────────────────────────────────

    def buscar(self, query: str) -> dict:
        return self._http.post("/api/buscar", json={"query": query}).json()

    def site(self, url: str) -> dict:
        return self._http.post("/api/site", json={"url": url}).json()

    # ─── System ───────────────────────────────────────

    def status(self) -> dict:
        return self._http.get("/api/status").json()

    def logs(self, lines: int = 50) -> list:
        return self._http.get("/api/logs", params={"lines": lines}).json().get("logs", [])

    def sync(self) -> dict:
        return self._http.post("/api/sync").json()
