"""币种隔离测试：双币分轨、混币旁置、并发装载、失败闭、核证。

全局架构 A：账户+币种+营业日复合键。
核心断言：任何情况下都不存在未标币种的单行总余额，回放按币种分轨通过。
"""

import json

import pytest

from app.modules.币种隔离 import 混轨失败闭, 轨键, 轨核证
from app.services import 回放, 抽取, 装载
from tests.conftest import 清业务

双币流水 = [
    {"流水号": "双-C1", "账户键": "户双", "币种": "CNY", "营业日": "2026-11-20", "变动额": 100000},
    {"流水号": "双-U1", "账户键": "户双", "币种": "USD", "营业日": "2026-11-20", "变动额": 5000},
    {"流水号": "双-C2", "账户键": "户双", "币种": "CNY", "营业日": "2026-11-21", "变动额": -20000},
    {"流水号": "双-U2", "账户键": "户双", "币种": "USD", "营业日": "2026-11-21", "变动额": 1200},
]


def 快照行(conn, 账户键, 币种, 日):
    return conn.execute(
        "SELECT * FROM 周期快照 WHERE 账户键=? AND 币种=? AND 营业日=? AND 状态='有效'",
        (账户键, 币种, 日),
    ).fetchone()


def 无未标单行(conn):
    """全局断言：不存在未标币种的有效镜（无单行总余额）。"""
    return conn.execute(
        "SELECT COUNT(*) AS c FROM 周期快照 "
        "WHERE 状态='有效' AND (币种 IS NULL OR TRIM(币种)='')"
    ).fetchone()["c"] == 0




def test_双币分轨_两行复合键_分轨守恒(库):
    报告 = 装载.装载流水(双币流水, "测-双币")
    assert 报告["入账"] == 4
    assert 报告["旁置"] == 0

    r1 = 抽取.日终抽取("2026-11-20", "抽-1")
    r2 = 抽取.日终抽取("2026-11-21", "抽-2")
    assert r1["写入"] >= 2 and r2["写入"] >= 2

    conn = 库.连接()
    try:
        cny0 = 快照行(conn, "户双", "CNY", "2026-11-20")
        usd0 = 快照行(conn, "户双", "USD", "2026-11-20")
        cny1 = 快照行(conn, "户双", "CNY", "2026-11-21")
        usd1 = 快照行(conn, "户双", "USD", "2026-11-21")
        
        assert cny0 and usd0 and cny0["快照键"] != usd0["快照键"]
        assert cny0["余额"] == 100000 and usd0["余额"] == 5000
        
        assert cny1["余额"] == 100000 - 20000
        assert usd1["余额"] == 5000 + 1200
        
        assert cny0["快照键"] == 轨键("户双", "CNY", "2026-11-20")
        assert 无未标单行(conn)
        
        n = conn.execute(
            "SELECT COUNT(*) AS c FROM 周期快照 WHERE 账户键=? AND 营业日=? AND 状态='有效'",
            ("户双", "2026-11-20"),
        ).fetchone()["c"]
        assert n == 2
    finally:
        conn.close()

    回 = 回放.回放核对("2026-11-21", "回-1")
    assert 回["通过"] is True
    assert 回["差额"] == 0
    assert 回["无快照"] == 0
    
    assert 回["分轨数"] >= 2




def test_混币旁置_不入账_不写混合镜(库):
    混 = [
        {"流水号": "混-1", "账户键": "户双", "营业日": "2026-11-20", "变动额": 700},
        {"流水号": "混-2", "账户键": "户双", "币种": "人民币", "营业日": "2026-11-20", "变动额": 800},
        {"流水号": "混-3", "账户键": "户双", "币种": "USD", "营业日": "2026-11-20", "变动额": 900, "汇率": "7.2"},
        {"流水号": "混-4", "账户键": "户双", "币种": "CNY", "营业日": "2026-11-20", "变动额": 1000, "折算额": 139},
    ]
    报告 = 装载.装载流水(混, "测-混币")
    assert 报告["入账"] == 0
    assert 报告["旁置"] == 4
    assert 报告["混币旁置"] == 4

    conn = 库.连接()
    try:
        原因 = [r["原因"] for r in conn.execute("SELECT 原因 FROM 旁置簿")]
        assert all(x.startswith("币种闸:") for x in 原因)
        assert conn.execute("SELECT COUNT(*) AS c FROM 变动流水").fetchone()["c"] == 0
    finally:
        conn.close()

    
    抽取.日终抽取("2026-11-20", "抽-混")
    conn = 库.连接()
    try:
        assert 无未标单行(conn)
        行 = conn.execute(
            "SELECT 币种, 余额 FROM 周期快照 WHERE 账户键='户双' AND 营业日='2026-11-20' AND 状态='有效'"
        ).fetchall()
        assert {r["币种"] for r in 行} == {"CNY"}
        assert all(r["余额"] == 0 for r in 行)
    finally:
        conn.close()


def test_隐式折算_任何折算字段都旁置(库):
    for 字段 in ("汇率", "折算汇率", "折算额", "折算币种", "折算后金额"):
        清业务(库)
        raw = [
            {"流水号": f"折-{字段}", "账户键": "户双", "币种": "USD", "营业日": "2026-11-20",
             "变动额": 100, 字段: "x"}
        ]
        报告 = 装载.装载流水(raw, f"批-{字段}")
        assert 报告["入账"] == 0 and 报告["混币旁置"] == 1




def test_同日并发装载_抽取仍两行(库):
    
    r_a = 装载.装载流水(
        [{"流水号": "并-C", "账户键": "户双", "币种": "CNY", "营业日": "2026-11-22", "变动额": 30000}],
        "并发-CNY",
    )
    r_b = 装载.装载流水(
        [{"流水号": "并-U", "账户键": "户双", "币种": "USD", "营业日": "2026-11-22", "变动额": 2000}],
        "并发-USD",
    )
    assert r_a["入账"] == 1 and r_b["入账"] == 1

    抽取.日终抽取("2026-11-22", "抽-并")
    conn = 库.连接()
    try:
        assert 无未标单行(conn)
        n = conn.execute(
            "SELECT COUNT(*) AS c FROM 周期快照 WHERE 账户键='户双' AND 营业日='2026-11-22' AND 状态='有效'"
        ).fetchone()["c"]
        assert n == 2
        assert 快照行(conn, "户双", "CNY", "2026-11-22")["余额"] == 30000
        assert 快照行(conn, "户双", "USD", "2026-11-22")["余额"] == 2000
    finally:
        conn.close()




def test_重抽_保持分轨_不压成总余额(库):
    装载.装载流水(双币流水, "测-重抽")
    抽取.日终抽取("2026-11-20", "抽-a")
    抽取.日终抽取("2026-11-20", "抽-b")  
    抽取.日终抽取("2026-11-21", "抽-c")
    抽取.日终抽取("2026-11-21", "抽-d")  
    conn = 库.连接()
    try:
        assert 无未标单行(conn)
        for 日, 币, 额 in (("2026-11-20", "CNY", 100000), ("2026-11-20", "USD", 5000),
                          ("2026-11-21", "CNY", 80000), ("2026-11-21", "USD", 6200)):
            assert 快照行(conn, "户双", 币, 日)["余额"] == 额
        
        n = conn.execute(
            "SELECT COUNT(*) AS c FROM 周期快照 WHERE 账户键='户双' AND 状态='有效'"
        ).fetchone()["c"]
        assert n == 4
    finally:
        conn.close()




def test_未标流水_抽取失败闭_不留半截有效镜(库):
    装载.装载流水(
        [{"流水号": "好-1", "账户键": "户双", "币种": "CNY", "营业日": "2026-11-23", "变动额": 100}],
        "好批",
    )
    
    conn = 库.连接()
    try:
        conn.execute(
            "INSERT INTO 变动流水(流水号, 账户键, 币种, 营业日, 发生时, 变动额, 命运) "
            "VALUES ('脏-1','户双','','2026-11-23','2026-11-23T00:00:00Z',999,'已入账')"
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(混轨失败闭):
        抽取.日终抽取("2026-11-23", "脏抽")
    conn = 库.连接()
    try:
        
        assert conn.execute(
            "SELECT COUNT(*) AS c FROM 周期快照 WHERE 抽取批次编号='脏抽'"
        ).fetchone()["c"] == 0
        assert 无未标单行(conn)
    finally:
        conn.close()

    with pytest.raises(混轨失败闭):
        回放.回放核对("2026-11-23", "脏回")


def test_未标快照_核证valid为假(库):
    装载.装载流水(
        [{"流水号": "好-2", "账户键": "户双", "币种": "CNY", "营业日": "2026-11-24", "变动额": 100}],
        "好批2",
    )
    抽取.日终抽取("2026-11-24", "干净抽")
    conn = 库.连接()
    try:
        证 = 轨核证(conn, "户双", "2026-11-24")
        assert 证["valid"] is True and 证["禁混计"] is True
        
        conn.execute(
            "INSERT INTO 周期快照(快照键, 账户键, 币种, 营业日, 余额, 抽取批次编号, 来源, 状态) "
            "VALUES ('脏镜','户双','','2026-11-24',99999,'旁路','旁路','有效')"
        )
        conn.commit()
        证2 = 轨核证(conn, "户双", "2026-11-24")
        assert 证2["valid"] is False
        assert 证2["禁混计"] is False
        assert 证2["违规行"]
    finally:
        conn.close()




def test_无流水轨_前日余额延续_两轨都在(库):
    装载.装载流水(
        [
            {"流水号": "轨-C", "账户键": "户双", "币种": "CNY", "营业日": "2026-11-20", "变动额": 1000},
            {"流水号": "轨-U", "账户键": "户双", "币种": "USD", "营业日": "2026-11-20", "变动额": 50},
        ],
        "开轨批",
    )
    抽取.日终抽取("2026-11-20", "t1")
    
    装载.装载流水(
        [{"流水号": "轨-C2", "账户键": "户双", "币种": "CNY", "营业日": "2026-11-21", "变动额": 200}],
        "次日批",
    )
    抽取.日终抽取("2026-11-21", "t2")
    conn = 库.连接()
    try:
        assert 无未标单行(conn)
        
        assert 快照行(conn, "户双", "USD", "2026-11-21")["余额"] == 50
        assert 快照行(conn, "户双", "CNY", "2026-11-21")["余额"] == 1200
        n = conn.execute(
            "SELECT COUNT(*) AS c FROM 周期快照 WHERE 账户键='户双' AND 营业日='2026-11-21' AND 状态='有效'"
        ).fetchone()["c"]
        assert n == 2
    finally:
        conn.close()
    assert 回放.回放核对("2026-11-21", "rt")["通过"] is True



def test_轨核证_分轨余额_禁混计_valid(库):
    装载.装载流水(双币流水, "测-核证")
    抽取.日终抽取("2026-11-20", "抽-证")
    conn = 库.连接()
    try:
        证 = 轨核证(conn)
        assert 证["架构"] == "账户+币种+营业日复合键"
        assert 证["禁止隐式折算"] is True
        assert 证["无合计接口"] is True
        assert 证["valid"] is True and 证["禁混计"] is True
        双轨 = [r for r in 证["分轨余额"] if r["账户键"] == "户双" and r["营业日"] == "2026-11-20"]
        assert {r["币种"] for r in 双轨} == {"CNY", "USD"}
        assert {r["余额"] for r in 双轨} == {100000, 5000}
        
        assert all(r["币种"] for r in 证["分轨余额"])
    finally:
        conn.close()




def test_单币主链_不回归(库):
    流水 = [
        {"流水号": "甲-1", "账户键": "户甲", "币种": "CNY", "营业日": "2026-11-20", "变动额": 10000},
        {"流水号": "甲-2", "账户键": "户甲", "币种": "CNY", "营业日": "2026-11-20", "变动额": -2500},
        {"流水号": "甲-3", "账户键": "户甲", "币种": "CNY", "营业日": "2026-11-21", "变动额": 3000},
    ]
    装载.装载流水(流水, "测-单币")
    抽取.日终抽取("2026-11-20", "s1")
    抽取.日终抽取("2026-11-21", "s2")
    回 = 回放.回放核对("2026-11-21", "r1")
    assert 回["通过"] is True
    conn = 库.连接()
    try:
        assert 快照行(conn, "户甲", "CNY", "2026-11-21")["余额"] == 10500
        assert 无未标单行(conn)
    finally:
        conn.close()


def test_流水缺省币种_跟随账户册本币轨(库):
    报告 = 装载.装载流水(
        [{"流水号": "默-1", "账户键": "户甲", "营业日": "2026-11-20", "变动额": 1}],
        "默批",
    )
    assert 报告["入账"] == 1
    conn = 库.连接()
    try:
        assert conn.execute("SELECT 币种 FROM 变动流水 WHERE 流水号='默-1'").fetchone()["币种"] == "CNY"
    finally:
        conn.close()


def test_未标载荷排在外币前_同批也不得吞入本币(库):
    
    报告 = 装载.装载流水(
        [
            {"流水号": "序-未标", "账户键": "户甲", "营业日": "2026-11-25", "变动额": 666},
            {"流水号": "序-USD", "账户键": "户甲", "币种": "USD", "营业日": "2026-11-25", "变动额": 9},
        ],
        "顺序批",
    )
    assert 报告["入账"] == 1
    assert 报告["混币旁置"] == 1
    conn = 库.连接()
    try:
        原因 = [r["原因"] for r in conn.execute("SELECT 原因 FROM 旁置簿")]
        assert any("多币账户未标币种" in x for x in 原因)
        assert conn.execute(
            "SELECT COUNT(*) AS c FROM 变动流水 WHERE 流水号='序-未标'"
        ).fetchone()["c"] == 0
        assert conn.execute("SELECT 多币种 FROM 账户 WHERE 账户键='户甲'").fetchone()["多币种"] == 1
    finally:
        conn.close()
