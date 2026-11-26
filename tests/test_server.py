import anyio
from mcp.client.client import Client

from dore.memory.embed import HashEmbedder
from dore.memory import MemoryStore
from dore.integrations.server import build_server


def text(result):
    return "".join(c.text for c in result.content)


def run(store, fn):
    async def main():
        server = build_server(store)
        return await fn(server)
    return anyio.run(main)


def make_store(tmp_path):
    return MemoryStore(tmp_path / "m.db", tmp_path / "m.faiss", HashEmbedder())


def test_tools_are_few_and_short(tmp_path):
    async def fn(server):
        async with Client(server) as c:
            return (await c.list_tools()).tools
    tools = run(make_store(tmp_path), fn)
    assert sorted(t.name for t in tools) == ["correct", "recall", "remember"]
    assert all(len(t.description) < 250 for t in tools)


def test_agent_facts_are_unverified_user_facts_verified(tmp_path):
    store = make_store(tmp_path)

    async def fn(server):
        async with Client(server) as c:
            a = text(await c.call_tool("remember", {"facts": ["the build uses pnpm workspaces"], "project": "shop"}))
            b = text(await c.call_tool("remember", {"facts": ["my editor is neovim"], "user_said": True}))
            return a, b
    a, b = run(store, fn)
    ida, idb = int(a.split("#")[1]), int(b.split("#")[1])
    assert a.startswith("saved #")
    assert store.get(ida).trust == "unverified" and store.get(ida).source == "agent"
    assert store.get(idb).trust == "verified" and store.get(idb).project == ""


def test_recall_project_scope_full_text_and_correct(tmp_path):
    store = make_store(tmp_path)
    store.duplicate_threshold = 1.01
    shop = store.add("api port is 8080", trust="verified", project="shop")
    store.add("api port is 9090", trust="verified", project="blog")
    long_id = store.add("deploy notes " + "step " * 200 + "end", trust="verified", project="shop")

    async def fn(server):
        async with Client(server) as c:
            r1 = text(await c.call_tool("recall", {"query": "api port", "project": "shop"}))
            full = text(await c.call_tool("recall", {"query": f"#{long_id}"}))
            fix = text(await c.call_tool("correct", {"correction": "api port is 8081", "wrong_ids": [shop],
                                                     "project": "shop", "user_said": True}))
            r2 = text(await c.call_tool("recall", {"query": "api port", "project": "shop"}))
            return r1, full, fix, r2
    r1, full, fix, r2 = run(store, fn)
    assert "8080" in r1 and "9090" not in r1
    assert full.endswith("end") and "…" not in full
    assert f"marked wrong: [{shop}]" in fix
    assert "8080" not in r2 and "8081" in r2


def test_two_clients_at_the_same_time_share_memory(tmp_path):
    store = make_store(tmp_path)

    async def fn(server):
        results = {}

        async def agent(name):
            async with Client(server) as c:
                for i in range(10):
                    await c.call_tool("remember", {"facts": [f"{name} learned item{i} zeta{i}{name}"]})
                await anyio.sleep(0.05)
                other = "beta" if name == "alpha" else "alpha"
                results[name] = text(await c.call_tool("recall", {"query": f"{other} learned item3 zeta3{other}",
                                                                   "k": 1}))
        async with anyio.create_task_group() as tg:
            tg.start_soon(agent, "alpha")
            tg.start_soon(agent, "beta")
        return results
    res = run(store, fn)
    assert "beta learned item3" in res["alpha"] and "alpha learned item3" in res["beta"]
    assert store.stats()["total"] == 20


def test_default_project_and_personal_facts(tmp_path):
    from dore.integrations.server import session_brief
    store = make_store(tmp_path)

    async def fn(_):
        server = build_server(store, default_project="shop")
        async with Client(server) as c:
            await c.call_tool("remember", {"facts": ["images live in the shop-assets bucket"]})
            await c.call_tool("remember", {"facts": ["my editor is neovim"], "user_said": True})
            return text(await c.call_tool("recall", {"query": "where do images live"}))
    r = run(store, fn)
    rows = dict(store.db.execute("SELECT content, project FROM memories").fetchall())
    assert rows == {"images live in the shop-assets bucket": "shop", "my editor is neovim": ""}
    assert "shop-assets" in r
    store.save(force=True)
    brief = session_brief(tmp_path / "m.db", "shop")
    assert "project 'shop': 1 notes, plus 1 general" in brief and "newest #" in brief
    assert "empty so far" in session_brief(tmp_path / "none.db", "shop")


def test_agent_correction_cannot_overrule_the_user(tmp_path):
    store = make_store(tmp_path)
    mine = store.add("my editor is neovim", source="user", trust="verified")
    theirs = store.add("the cache is redis", source="agent", trust="unverified")

    async def fn(server):
        async with Client(server) as c:
            return text(await c.call_tool("correct", {"correction": "the editor is vim and the cache is memcached",
                                                      "wrong_ids": [mine, theirs]}))
    out = run(store, fn)
    assert f"marked wrong: [{theirs}]" in out and f"kept [{mine}]" in out
    assert store.get(mine).trust == "verified" and store.get(theirs).trust == "wrong"
