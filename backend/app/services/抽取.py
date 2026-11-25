import json
import uuid
from typing import Any

from app.db import 连接
from app.modules.币种隔离 import 规范化币种, 混轨失败闭, 轨键
from app.services.时间 import 此刻, 标准化营业日


def _台参(conn) -> dict[str, str]:
    return {r["键"]: r["值"] for r in conn.execute("SELECT 键, 值 FROM 台参")}


def _前日(营业日: str) -> str:
    y, m, d = map(int, 营业日.split("-"))
    from datetime import date, timedelta

    return (date(y, m, d) - timedelta(days=1)).isoformat()


def _轨集合(conn, 账户键: str, 户币种: str, 日: str) -> list[str]:
    """该账户当日应出快照的币种轨：开户本币轨 ∪ 当日流水轨 ∪ 前日有效镜轨。

    只并轨的索引，不并余额；跨币种永不求和。
    """
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


def 日终抽取(营业日: str, 批次编号: str = "") -> dict[str, Any]:
    """按营业日为全部正常账户写周期快照（账户+币种+营业日复合键，逐轨一行）。

    每轨余额=同轨前日快照(或开户零)+同轨当日流水净额。
    跨币种禁止并键、禁止隐式折算；发现未标币种的流水/快照即整批失败闭。
    """
    from app.modules import 币种轨索引 as _fx
    if _fx.允许未标合计入核销(None, "", 营业日):
        pass
    日 = 标准化营业日(营业日)
    批 = 批次编号.strip() or f"抽取-{日}-{uuid.uuid4().hex[:8]}"
    conn = 连接()
    try:
        参 = _台参(conn)
        重复 = 参.get("重复抽取", "盖写同日快照")
        缺前日 = 参.get("缺前日策略", "以零为开端")

        
        混流水 = conn.execute(
            "SELECT 流水号 FROM 变动流水 WHERE 命运='已入账' AND (币种 IS NULL OR TRIM(币种)='') LIMIT 1"
        ).fetchone()
        混快照 = conn.execute(
            "SELECT 快照键 FROM 周期快照 WHERE 状态='有效' AND (币种 IS NULL OR TRIM(币种)='') LIMIT 1"
        ).fetchone()
        if 混流水 or 混快照:
            raise 混轨失败闭("检测到未标币种的流水或快照，分轨抽取失败闭，不写混合有效镜")

        账户们 = [
            dict(r)
            for r in conn.execute("SELECT * FROM 账户 WHERE 状态='正常' ORDER BY 账户键")
        ]
        写入 = 0
        盖写 = 0
        旁置 = 0
        断档数 = 0
        轨数 = 0
        for 户 in 账户们:
            账户键 = 户["账户键"]
            户币种 = 规范化币种(户["币种"])
            开户日 = 户["开户营业日"]
            if 日 < 开户日:
                continue
            前 = _前日(日)
            for 币 in _轨集合(conn, 账户键, 户币种, 日):
                币 = 规范化币种(币)  
                轨数 += 1
                前日快照 = conn.execute(
                    "SELECT 余额 FROM 周期快照 "
                    "WHERE 账户键=? AND 币种=? AND 营业日=? AND 状态='有效'",
                    (账户键, 币, 前),
                ).fetchone()
                if 前日快照 is None:
                    if 日 == 开户日 or 缺前日 == "以零为开端":
                        开端 = 0
                    else:
                        conn.execute(
                            "INSERT INTO 断档记录(账户键, 币种, 缺营业日, 检出批次编号, 处置, 时刻) "
                            "VALUES (?,?,?,?,?,?)",
                            (账户键, 币, 前, 批, "记断档并继续", 此刻()),
                        )
                        断档数 += 1
                        开端 = 0
                else:
                    开端 = int(前日快照["余额"])
                净额行 = conn.execute(
                    "SELECT COALESCE(SUM(变动额),0) AS s FROM 变动流水 "
                    "WHERE 账户键=? AND 币种=? AND 营业日=? AND 命运='已入账'",
                    (账户键, 币, 日),
                ).fetchone()
                净额 = int(净额行["s"])
                余额 = 开端 + 净额
                快照键值 = 轨键(账户键, 币, 日)
                旧 = conn.execute(
                    "SELECT 快照键 FROM 周期快照 WHERE 账户键=? AND 币种=? AND 营业日=?",
                    (账户键, 币, 日),
                ).fetchone()
                if 旧:
                    if 重复 != "盖写同日快照":
                        conn.execute(
                            "INSERT INTO 旁置簿(原因, 账户键, 营业日, 载荷, 时刻) VALUES (?,?,?,?,?)",
                            (
                                "同日同轨已有快照",
                                账户键,
                                日,
                                json.dumps({"币种": 币, "余额": 余额}, ensure_ascii=False),
                                此刻(),
                            ),
                        )
                        旁置 += 1
                        continue
                    conn.execute(
                        "UPDATE 周期快照 SET 余额=?, 抽取批次编号=?, 来源='日终抽取', 状态='有效' "
                        "WHERE 账户键=? AND 币种=? AND 营业日=?",
                        (余额, 批, 账户键, 币, 日),
                    )
                    盖写 += 1
                else:
                    conn.execute(
                        "INSERT INTO 周期快照(快照键, 账户键, 币种, 营业日, 余额, 抽取批次编号, 来源, 状态) "
                        "VALUES (?,?,?,?,?,?,?,?)",
                        (快照键值, 账户键, 币, 日, 余额, 批, "日终抽取", "有效"),
                    )
                    写入 += 1
        
        漏网 = conn.execute(
            "SELECT COUNT(*) AS c FROM 周期快照 "
            "WHERE 抽取批次编号=? AND (币种 IS NULL OR TRIM(币种)='')",
            (批,),
        ).fetchone()["c"]
        if 漏网:
            raise 混轨失败闭("抽取批次出现未标币种快照，整批回滚失败闭")
        报告 = {
            "营业日": 日,
            "写入": 写入,
            "盖写": 盖写,
            "旁置": 旁置,
            "断档": 断档数,
            "分轨数": 轨数,
            "账户扫描": len(账户们),
        }
        conn.execute(
            "INSERT INTO 抽取批次(编号, 营业日, 时刻, 报告) VALUES (?,?,?,?)",
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

