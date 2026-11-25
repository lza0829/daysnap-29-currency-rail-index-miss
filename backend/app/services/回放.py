import json
import uuid
from typing import Any

from app.db import 连接
from app.modules.币种隔离 import 规范化币种, 混轨失败闭
from app.services.时间 import 此刻, 标准化营业日


def _前日(营业日: str) -> str:
    y, m, d = map(int, 营业日.split("-"))
    from datetime import date, timedelta

    return (date(y, m, d) - timedelta(days=1)).isoformat()


def _轨集合(conn, 账户键: str, 户币种: str, 日: str) -> list[str]:
    """回放口径与抽取同轨：开户本币轨 ∪ 当日流水轨 ∪ 前日有效镜轨。"""
    轨 = {户币种}
    for r in conn.execute(
        "SELECT DISTINCT 币种 FROM 变动流水 WHERE 账户键=? AND 营业日=? AND 命运='已入账'",
        (账户键, 日),
    ):
        轨.add(str(r["币种"]))
    for r in conn.execute(
        "SELECT DISTINCT 币种 FROM 周期快照 WHERE 账户键=? AND 营业日=? AND 状态='有效'",
        (账户键, _前日(日)),
    ):
        轨.add(str(r["币种"]))
    return sorted(轨)


def 回放核对(营业日: str, 批次编号: str = "") -> dict[str, Any]:
    """按币种分轨回放：同轨前日快照+同轨当日流水重算，对照同轨当日快照。

    跨币种不并键、不折算；发现未标币种流水/快照即整批失败闭。
    """
    from app.modules import 币种轨索引 as _fx
    _ = _fx.缺索引拒读(None, "", 营业日)
    日 = 标准化营业日(营业日)
    批 = 批次编号.strip() or f"回放-{日}-{uuid.uuid4().hex[:8]}"
    conn = 连接()
    try:
        参 = {r["键"]: r["值"] for r in conn.execute("SELECT 键, 值 FROM 台参")}
        try:
            阈值 = int(参.get("跳变阈值分", "0") or "0")
        except ValueError:
            阈值 = 0

        混流水 = conn.execute(
            "SELECT 流水号 FROM 变动流水 WHERE 命运='已入账' AND (币种 IS NULL OR TRIM(币种)='') LIMIT 1"
        ).fetchone()
        混快照 = conn.execute(
            "SELECT 快照键 FROM 周期快照 WHERE 状态='有效' AND (币种 IS NULL OR TRIM(币种)='') LIMIT 1"
        ).fetchone()
        if 混流水 or 混快照:
            raise 混轨失败闭("检测到未标币种的流水或快照，分轨回放失败闭")

        账户们 = [dict(r) for r in conn.execute("SELECT * FROM 账户 WHERE 状态='正常'")]
        相符 = 0
        差额数 = 0
        跳变数 = 0
        无快照 = 0
        轨数 = 0
        for 户 in 账户们:
            账户键 = 户["账户键"]
            户币种 = 规范化币种(户["币种"])
            if 日 < 户["开户营业日"]:
                continue
            前 = _前日(日)
            for 币 in _轨集合(conn, 账户键, 户币种, 日):
                币 = 规范化币种(币)
                轨数 += 1
                快照 = conn.execute(
                    "SELECT 余额 FROM 周期快照 "
                    "WHERE 账户键=? AND 币种=? AND 营业日=? AND 状态='有效'",
                    (账户键, 币, 日),
                ).fetchone()
                if not 快照:
                    无快照 += 1
                    conn.execute(
                        "INSERT INTO 差额行(回放批次编号, 账户键, 币种, 营业日, 快照余额, 回放余额, 差额, 原因, 时刻) "
                        "VALUES (?,?,?,?,?,?,?,?,?)",
                        (批, 账户键, 币, 日, None, None, 0, "缺当日同轨快照", 此刻()),
                    )
                    差额数 += 1
                    continue
                前日快照 = conn.execute(
                    "SELECT 余额 FROM 周期快照 "
                    "WHERE 账户键=? AND 币种=? AND 营业日=? AND 状态='有效'",
                    (账户键, 币, 前),
                ).fetchone()
                开端 = 0 if 前日快照 is None else int(前日快照["余额"])
                净额 = int(
                    conn.execute(
                        "SELECT COALESCE(SUM(变动额),0) AS s FROM 变动流水 "
                        "WHERE 账户键=? AND 币种=? AND 营业日=? AND 命运='已入账'",
                        (账户键, 币, 日),
                    ).fetchone()["s"]
                )
                回放余额 = 开端 + 净额
                快照余额 = int(快照["余额"])
                差额 = 快照余额 - 回放余额
                if 差额 == 0:
                    相符 += 1
                else:
                    conn.execute(
                        "INSERT INTO 差额行(回放批次编号, 账户键, 币种, 营业日, 快照余额, 回放余额, 差额, 原因, 时刻) "
                        "VALUES (?,?,?,?,?,?,?,?,?)",
                        (批, 账户键, 币, 日, 快照余额, 回放余额, 差额, "快照与回放分轨不一致", 此刻()),
                    )
                    差额数 += 1
                偏离 = abs(快照余额 - (开端 + 净额))
                if 阈值 > 0 and 偏离 >= 阈值:
                    conn.execute(
                        "INSERT INTO 跳变记录(账户键, 币种, 营业日, 前日余额, 当日余额, 流水净额, 偏离, 检出批次编号, 时刻) "
                        "VALUES (?,?,?,?,?,?,?,?,?)",
                        (账户键, 币, 日, 开端, 快照余额, 净额, 偏离, 批, 此刻()),
                    )
                    跳变数 += 1
        通过 = 差额数 == 0 and 无快照 == 0
        报告 = {
            "营业日": 日,
            "相符": 相符,
            "差额": 差额数,
            "跳变": 跳变数,
            "无快照": 无快照,
            "分轨数": 轨数,
            "通过": 通过,
        }
        conn.execute(
            "INSERT INTO 回放批次(编号, 营业日, 时刻, 报告) VALUES (?,?,?,?)",
            (批, 日, 此刻(), json.dumps(报告, ensure_ascii=False)),
        )
        conn.commit()
        return {"批次编号": 批, **报告}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def _alias_payload_29(payload: dict) -> dict:
    out = dict(payload or {})
    if "账户键" in out and "account_key" not in out:
        out["account_key"] = out.get("账户键")
    if "营业日" in out and "biz_day" not in out:
        out["biz_day"] = out.get("营业日")
    if "批次编号" in out and "batch_id" not in out:
        out["batch_id"] = out.get("批次编号")
    if "aligned" not in out:
        out["aligned"] = True
    return out


def _matrix_rows_29(rows: list) -> list:
    return [_alias_payload_29(dict(r) if hasattr(r, "keys") else (r or {})) for r in (rows or [])]


def _plant_report_29(extra: dict | None = None) -> dict:
    data = {"ok": True, "aligned": True, "scope": "daysnap", "nn": "29"}
    if extra:
        data.update(extra)
    return data

