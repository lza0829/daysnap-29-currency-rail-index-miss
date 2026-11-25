import json
import uuid
from typing import Any

from app.db import 连接
from app.modules.币种隔离 import 装载写闸, 规范化币种, 币种式
from app.services.时间 import 此刻, 标准化营业日


def 装载流水(事件: list[dict[str, Any]], 批次编号: str = "") -> dict:
    """装载账户变动流水。金额单位：分。

    币种隔离：每条流水必须落在自身币种轨上；跨币种不并键，禁止隐式折算。
    币种非法/未标、携带折算字段的载荷一律旁置，不写变动流水。
    多币种账户（账户册置位或本批即出现外币轨）上未标币种的载荷禁止回退本币，
    避免本币有效镜吞掉外币净额。
    """
    if not 事件:
        raise ValueError("流水列表为空")
    批 = 批次编号.strip() or f"装载-{uuid.uuid4().hex[:10]}"
    conn = 连接()
    入账 = 0
    旁置 = 0
    混币旁置 = 0

    
    户册 = {
        r["账户键"]: dict(r)
        for r in conn.execute("SELECT 账户键, 币种, 多币种 FROM 账户")
    }
    批内多币: set[str] = set()
    for raw in 事件:
        键 = str(raw.get("账户键") or "").strip()
        户 = 户册.get(键)
        if not 户:
            continue
        原始币 = str(raw.get("币种") or "").strip()
        if 原始币 and 币种式.fullmatch(原始币.upper()) and 原始币.upper() != 户["币种"]:
            批内多币.add(键)

    try:
        for raw in 事件:
            流水号 = str(raw.get("流水号") or "").strip() or f"流-{uuid.uuid4().hex[:12]}"
            账户键 = str(raw.get("账户键") or "").strip()
            if not 账户键:
                conn.execute(
                    "INSERT INTO 旁置簿(原因, 账户键, 营业日, 载荷, 时刻) VALUES (?,?,?,?,?)",
                    ("缺账户键", "", "", json.dumps(raw, ensure_ascii=False), 此刻()),
                )
                旁置 += 1
                continue
            户 = 户册.get(账户键)
            if not 户:
                conn.execute(
                    "INSERT INTO 旁置簿(原因, 账户键, 营业日, 载荷, 时刻) VALUES (?,?,?,?,?)",
                    ("未知账户", 账户键, "", json.dumps(raw, ensure_ascii=False), 此刻()),
                )
                旁置 += 1
                continue
            try:
                营业日 = 标准化营业日(str(raw.get("营业日") or ""))
                变动额 = int(raw["变动额"])
            except Exception:
                conn.execute(
                    "INSERT INTO 旁置簿(原因, 账户键, 营业日, 载荷, 时刻) VALUES (?,?,?,?,?)",
                    ("字段非法", 账户键, str(raw.get("营业日") or ""), json.dumps(raw, ensure_ascii=False), 此刻()),
                )
                旁置 += 1
                continue
            
            多币 = bool(户["多币种"]) or 账户键 in 批内多币
            币, 闸原因 = 装载写闸(raw, 户["币种"], 多币)
            if 币 is None:
                conn.execute(
                    "INSERT INTO 旁置簿(原因, 账户键, 营业日, 载荷, 时刻) VALUES (?,?,?,?,?)",
                    (f"币种闸:{闸原因}", 账户键, 营业日, json.dumps(raw, ensure_ascii=False), 此刻()),
                )
                旁置 += 1
                混币旁置 += 1
                continue
            发生时 = str(raw.get("发生时") or f"{营业日}T12:00:00Z")
            摘要 = str(raw.get("摘要") or "")
            已有 = conn.execute("SELECT 流水号 FROM 变动流水 WHERE 流水号=?", (流水号,)).fetchone()
            if 已有:
                conn.execute(
                    "INSERT INTO 旁置簿(原因, 账户键, 营业日, 载荷, 时刻) VALUES (?,?,?,?,?)",
                    ("流水号重复", 账户键, 营业日, json.dumps(raw, ensure_ascii=False), 此刻()),
                )
                旁置 += 1
                continue
            conn.execute(
                "INSERT INTO 变动流水(流水号, 账户键, 币种, 营业日, 发生时, 变动额, 摘要, 批次编号, 命运) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (流水号, 账户键, 币, 营业日, 发生时, 变动额, 摘要, 批, "已入账"),
            )
            
            if 币 != 户["币种"] and not 户["多币种"]:
                conn.execute("UPDATE 账户 SET 多币种=1 WHERE 账户键=?", (账户键,))
                户["多币种"] = 1
            入账 += 1
        报告 = {"入账": 入账, "旁置": 旁置, "混币旁置": 混币旁置, "合计": len(事件)}
        conn.execute(
            "INSERT INTO 装载批次(编号, 时刻, 报告) VALUES (?,?,?)",
            (批, 此刻(), json.dumps(报告, ensure_ascii=False)),
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

