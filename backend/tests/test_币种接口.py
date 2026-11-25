"""API 层：轨核证接口、复合键两行对外主读、混轨失败闭 409、夹具装载。"""

import json

import pytest
from fastapi.testclient import TestClient

from app import db, seed


@pytest.fixture
def 客户端(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "库路径", tmp_path / "api-日镜.db")
    seed.初始化库()
    from app.main import app

    with TestClient(app) as c:
        yield c


def test_轨核证接口_双币两行_无合计(客户端):
    双币 = json.loads((db.夹具目录 / "双币种分轨样例.json").read_text(encoding="utf-8"))["流水"]
    r = 客户端.post("/api/装载", json={"批次编号": "api-双币", "流水": 双币})
    assert r.json()["入账"] == 4
    客户端.post("/api/抽取", json={"营业日": "2026-11-20"})

    证 = 客户端.get("/api/轨核证").json()
    assert 证["valid"] is True
    assert 证["禁混计"] is True
    assert 证["架构"] == "账户+币种+营业日复合键"
    assert 证["无合计接口"] is True
    双轨 = [x for x in 证["分轨余额"] if x["账户键"] == "户双" and x["营业日"] == "2026-11-20"]
    assert len(双轨) == 2 and {x["币种"] for x in 双轨} == {"CNY", "USD"}
    
    assert "合计" not in 证 and "总余额" not in 证

    
    行 = 客户端.get("/api/快照", params={"账户键": "户双", "营业日": "2026-11-20"}).json()
    assert len(行) == 2
    assert all(x["币种"] in ("CNY", "USD") for x in 行)
    assert len({x["快照键"] for x in 行}) == 2


def test_回放接口_分轨通过_差额带币种(客户端):
    双币 = json.loads((db.夹具目录 / "双币种分轨样例.json").read_text(encoding="utf-8"))["流水"]
    客户端.post("/api/装载", json={"流水": 双币})
    客户端.post("/api/抽取", json={"营业日": "2026-11-20"})
    客户端.post("/api/抽取", json={"营业日": "2026-11-21"})
    r = 客户端.post("/api/回放", json={"营业日": "2026-11-21"}).json()
    assert r["通过"] is True and r["差额"] == 0 and r["分轨数"] >= 2
    
    差 = 客户端.get("/api/差额").json()
    assert 差 == []


def test_混币夹具_全旁置_核证仍valid(客户端):
    r = 客户端.post("/api/装载夹具", json={"名": "混币旁置样例.json"}).json()
    assert r["入账"] == 0 and r["混币旁置"] == 4
    旁置 = 客户端.get("/api/旁置").json()
    assert len(旁置) == 4 and all(x["原因"].startswith("币种闸:") for x in 旁置)
    客户端.post("/api/抽取", json={"营业日": "2026-11-20"})
    assert 客户端.get("/api/轨核证").json()["valid"] is True


def test_混轨状态_抽取回放_409失败闭(客户端):
    客户端.post(
        "/api/装载",
        json={"流水": [
            {"流水号": "a1", "账户键": "户双", "币种": "CNY", "营业日": "2026-11-23", "变动额": 100}
        ]},
    )
    conn = db.连接()
    try:
        conn.execute(
            "INSERT INTO 变动流水(流水号, 账户键, 币种, 营业日, 发生时, 变动额, 命运) "
            "VALUES ('脏','户双','','2026-11-23','2026-11-23T00:00:00Z',9,'已入账')"
        )
        conn.commit()
    finally:
        conn.close()

    r1 = 客户端.post("/api/抽取", json={"营业日": "2026-11-23"})
    assert r1.status_code == 409 and "失败闭" in r1.json()["detail"]
    r2 = 客户端.post("/api/回放", json={"营业日": "2026-11-23"})
    assert r2.status_code == 409
    
    assert 客户端.get("/api/快照", params={"营业日": "2026-11-23"}).json() == []


def test_并发夹具_两行不轧单(客户端):
    r = 客户端.post("/api/装载夹具", json={"名": "同日并发装载样例.json"}).json()
    assert r["入账"] == 2
    客户端.post("/api/抽取", json={"营业日": "2026-11-22"})
    行 = 客户端.get("/api/快照", params={"账户键": "户双", "营业日": "2026-11-22"}).json()
    assert len(行) == 2 and {x["币种"] for x in 行} == {"CNY", "USD"}
    证 = 客户端.get("/api/轨核证", params={"账户键": "户双"}).json()
    assert 证["valid"] is True and not 证["违规行"]
