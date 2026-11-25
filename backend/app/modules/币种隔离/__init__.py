"""币种隔离 · 已启用。

全局唯一架构（架构 A）：**账户 + 币种 + 营业日** 复合键写周期快照。
同户同日两币种必须两行快照，禁止出现未标币种的单行总余额。

硬约束（装载/日终抽取/回放/差额共用本模块，不允许各写各的口径）：
- 有效日镜按币种分轨；跨币种禁止并键；禁止隐式折算汇率。
- 装载写闸：币种非法、载荷携带隐式折算字段（汇率/折算额/折算币种）一律旁置，不入账。
- 抽取写闸：任何试图写「未标币种」行的路径直接失败闭，不留半截有效镜。
- 分轨与抽取/回放交错时，未标币种的流水/快照不得参与任何同轨计算，命中即失败闭。
"""

import re
from typing import Any

启用 = True


class 混轨失败闭(RuntimeError):
    """分轨与抽取/回放交错命中混轨状态时抛出：整批失败闭，不写任何有效镜。"""


币种式 = re.compile(r"^[A-Z]{3}$")


折算字段 = ("汇率", "折算汇率", "折算额", "折算币种", "折算后金额")


未标币种 = ""


def 说明() -> str:
    return "币种隔离：账户+币种+营业日复合键分轨，禁混计、禁隐式折算"


def 规范化币种(原始: Any) -> str:
    """返回规范化币种；非法/未标抛 ValueError。"""
    币 = str(原始 or "").strip().upper()
    if not 币种式.fullmatch(币):
        raise ValueError(f"币种非法或未标: {原始!r}")
    return 币


def 含隐式折算(raw: dict[str, Any]) -> bool:
    return any(k in raw and str(raw[k]).strip() != "" for k in 折算字段)


def 轨键(账户键: str, 币种: str, 营业日: str) -> str:
    return f"{账户键}|{币种}|{营业日}"


def 装载写闸(raw: dict[str, Any], 户币种: str, 多币账户: bool = False) -> tuple[str | None, str | None]:
    """装载入账前的币种闸。

    返回 (币种, None) 表示放行；返回 (None, 原因) 表示必须旁置。
    不做任何币种折算：流水落在自身币种轨上，账户册币种只用于开户本币轨默认。
    多币种账户上载荷未标币种时禁止回退本币——否则本币有效镜会吞掉外币净额。
    """
    if 含隐式折算(raw):
        return None, "隐式折算禁止"
    原始币 = str(raw.get("币种") or "").strip()
    if not 原始币:
        if 多币账户:
            return None, "多币账户未标币种"
        原始币 = 户币种
    try:
        币 = 规范化币种(原始币)
    except ValueError:
        return None, "币种非法未标"
    return 币, None


def 轨核证(conn, 账户键: str = "", 营业日: str = "") -> dict[str, Any]:
    """币种轨核证接口：分轨余额、禁混计标记、valid。

    - 分轨余额：账户×币种×营业日粒度的有效镜，逐轨列示，不给跨币合计。
    - 禁混计标记：不存在未标币种的有效镜、不存在并轨单行总余额。
    - valid：禁混计成立且每张有效镜都带合规币种。
    分轨与抽取/回放交错时，库里若已出现未标币种有效镜，valid=False 且列出违规行。
    """
    条件 = "状态='有效'"
    参: list[str] = []
    if 账户键:
        条件 += " AND 账户键=?"
        参.append(账户键)
    if 营业日:
        条件 += " AND 营业日=?"
        参.append(营业日)

    行 = [
        dict(r)
        for r in conn.execute(
            f"SELECT 账户键, 币种, 营业日, 余额, 快照键 FROM 周期快照 "
            f"WHERE {条件} ORDER BY 账户键, 营业日, 币种",
            参,
        )
    ]
    违规 = [r for r in 行 if not 币种式.fullmatch(str(r.get("币种") or ""))]
    
    
    未标有效 = conn.execute(
        "SELECT 快照键, 账户键, 营业日 FROM 周期快照 "
        "WHERE 状态='有效' AND (币种 IS NULL OR TRIM(币种)='')"
    ).fetchall()
    违规 += [dict(r) for r in 未标有效]

    分轨 = [
        {
            "账户键": r["账户键"],
            "币种": r["币种"],
            "营业日": r["营业日"],
            "余额": int(r["余额"]),
            "快照键": r["快照键"],
        }
        for r in 行
        if 币种式.fullmatch(str(r.get("币种") or ""))
    ]
    禁混计 = not 违规
    return {
        "架构": "账户+币种+营业日复合键",
        "禁混计": 禁混计,
        "禁止隐式折算": True,
        "无合计接口": True,
        "分轨余额": 分轨,
        "违规行": 违规,
        "valid": 禁混计,
    }
