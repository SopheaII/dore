import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

from dore.config import Config
from dore.memory.embed import HashEmbedder
from dore.memory import MemoryStore
from dore.apps.web import Handler, ModelHub, WebApp, discover_models


class FakeCore:
    def __init__(self, tag):
        self.tag = tag
        self.n_ctx = 4096
        self.prompts = []

    def count_tokens(self, text):
        return len(text.split())

    def chat(self, messages, max_tokens=512, temperature=0.3):
        self.prompts.append(messages)
        return self.tag


def make_app(tmp_path, names=("1b", "3b")):
    (tmp_path / "models").mkdir(exist_ok=True)
    paths = {}
    for name in names:
        path = tmp_path / "models" / f"Llama-3.2-{name.upper()}-Instruct-Q4_K_M.gguf"
        path.write_bytes(b"not a real model")
        paths[name] = path
    store = MemoryStore(tmp_path / "m.db", tmp_path / "m.faiss", HashEmbedder())
    hub = ModelHub(paths, factory=lambda p: FakeCore(p.stem))
    return WebApp(Config(data_dir=tmp_path), store, hub)


def test_lists_models_and_switches_on_request(tmp_path):
    app = make_app(tmp_path)
    models = app.models()
    assert [m["name"] for m in models["models"]] == ["1b", "3b"]
    assert models["default"] == "1b"

    assert app.chat("hello there", model="1b")["answer"].startswith("Llama-3.2-1B")
    assert app.hub.name == "1b"
    assert app.chat("hello again", model="3b")["answer"].startswith("Llama-3.2-3B")
    assert app.hub.name == "3b"

    try:
        app.chat("hi", model="9b")
    except KeyError as exc:
        assert "9b" in str(exc)
    else:
        raise AssertionError("unknown model should raise")


def test_commands_share_memory_and_clear_history(tmp_path):
    app = make_app(tmp_path)
    out = app.chat("/teach my wifi password is hunters2", model="1b")
    assert "saved verified memory" in out["answer"]
    assert app.store.stats()["verified"] == 1

    stats = app.chat("/stats", model="1b")
    assert stats["stats"]["verified"] == 1
    assert "verified: 1" in stats["answer"]

    app.chat("hello", model="1b")  # one chat turn in history
    assert app.agent.history
    app.chat("/new", model="1b")
    assert app.agent.history == []


def test_projects_are_per_conversation(tmp_path):
    app = make_app(tmp_path)
    app.chat("The build uses pnpm workspaces", model="1b", project="shop")
    assert app.agent.project == "shop"
    assert app.store.projects().get("shop") == 1
    app.chat("hi", model="1b", project="")
    assert app.agent.project == ""


def test_http_page_models_and_chat(tmp_path):
    app = make_app(tmp_path)
    Handler.app = app
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        with urllib.request.urlopen(base + "/") as res:
            page = res.read().decode()
        assert 'id="model"' in page and "What can I help with?" in page
        assert 'id="sidebar"' in page

        with urllib.request.urlopen(base + "/api/models") as res:
            assert [m["name"] for m in json.load(res)["models"]] == ["1b", "3b"]

        with urllib.request.urlopen(base + "/api/projects") as res:
            assert json.load(res)["projects"] == {}

        req = urllib.request.Request(
            base + "/api/chat",
            data=json.dumps({"message": "hello", "model": "3b"}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req) as res:
            data = json.load(res)
        assert data["answer"].startswith("Llama-3.2-3B")
        assert data["model"] == "3b"

        with urllib.request.urlopen(urllib.request.Request(base + "/api/reset", data=b"", method="POST")) as res:
            assert json.load(res)["answer"] == "new chat"
    finally:
        httpd.shutdown()
        httpd.server_close()
        app.store.close()


def test_discover_models_keeps_same_size_files(tmp_path):
    models = tmp_path / "models"
    models.mkdir()
    (models / "Llama-3.2-1B-Instruct-Q4_K_M.gguf").write_bytes(b"x")
    (models / "other-model.gguf").write_bytes(b"x")
    paths = discover_models(tmp_path)
    assert set(paths) == {"1b", "other-model"}
