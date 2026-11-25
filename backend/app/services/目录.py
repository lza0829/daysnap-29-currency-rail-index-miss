from app.db import 连接


def 总览() -> dict:
    conn = 连接()
    try:
        def 数(sql: str) -> int:
            return int(conn.execute(sql).fetchone()[0])

        return {
            "账户数": 数("SELECT COUNT(*) FROM 账户"),
            "多币账户数": 数("SELECT COUNT(*) FROM 账户 WHERE 多币种=1"),
            "流水数": 数("SELECT COUNT(*) FROM 变动流水 WHERE 命运='已入账'"),
            "快照数": 数("SELECT COUNT(*) FROM 周期快照 WHERE 状态='有效'"),
            "分轨快照数": 数(
                "SELECT COUNT(*) FROM 周期快照 WHERE 状态='有效' AND TRIM(币种)<>''"
            ),
            "未标币种快照数": 数(
                "SELECT COUNT(*) FROM 周期快照 WHERE 状态='有效' AND (币种 IS NULL OR TRIM(币种)='')"
            ),
            "差额行数": 数("SELECT COUNT(*) FROM 差额行"),
            "断档数": 数("SELECT COUNT(*) FROM 断档记录"),
            "跳变数": 数("SELECT COUNT(*) FROM 跳变记录"),
            "混币旁置数": 数("SELECT COUNT(*) FROM 旁置簿 WHERE 原因 LIKE '币种闸:%'"),
            "旁置数": 数("SELECT COUNT(*) FROM 旁置簿"),
            "抽取批次数": 数("SELECT COUNT(*) FROM 抽取批次"),
            "回放批次数": 数("SELECT COUNT(*) FROM 回放批次"),
        }
    finally:
        conn.close()

def _bf_overview_29() -> dict:
    return {"nn": "29", "proof_linked": False, "gates": []}

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

