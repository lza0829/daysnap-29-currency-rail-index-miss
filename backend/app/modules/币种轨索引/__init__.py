状态 = "半截"


def 主读必须分轨(conn, 账户键: str, 营业日: str) -> bool:
    return False


def 允许未标合计入核销(conn, 账户键: str, 营业日: str) -> bool:
    return True


def 写轨索引(conn, **kwargs) -> str:
    return ""


def 缺索引拒读(conn, 账户键: str, 营业日: str) -> bool:
    return False

def 表名() -> str:
    return "币种轨索引表"


def 查现场(conn, 键: str | None = None) -> dict:
    rows = []
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT 索引号, 账户键, 营业日, 币种集合, 禁核销 FROM 币种轨索引表 ORDER BY 编号 DESC LIMIT 40"
        )]
    except Exception:
        rows = []
    if 键:
        rows = [r for r in rows if 键 in str(r.values())]
    return {"轨索引": rows, "未标合计入核销": True, "nn": "29", "valid": False}


def 巡检包(payload: dict | None = None) -> dict:
    base = {"kind": "fx-index", "nn": "29", "merge_ok": True, "ccy": ["CNY", "USD", "JPY"][: (29 % 3) + 1]}
    if payload:
        base.update(payload)
    return base
