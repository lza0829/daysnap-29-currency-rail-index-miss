from datetime import datetime, timezone

from app.db import 连接

建表 = """
CREATE TABLE IF NOT EXISTS 币种轨索引表 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  索引号 TEXT, 账户键 TEXT, 营业日 TEXT, 币种集合 TEXT, 禁核销 INTEGER,
  时刻 TEXT NOT NULL DEFAULT '',
  载荷 TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS 台参 (
  键 TEXT PRIMARY KEY,
  值 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 账户 (
  账户键 TEXT PRIMARY KEY,
  户名 TEXT NOT NULL,
  币种 TEXT NOT NULL DEFAULT 'CNY',
  多币种 INTEGER NOT NULL DEFAULT 0,
  开户营业日 TEXT NOT NULL,
  状态 TEXT NOT NULL DEFAULT '正常'
);
CREATE TABLE IF NOT EXISTS 变动流水 (
  流水号 TEXT PRIMARY KEY,
  账户键 TEXT NOT NULL,
  币种 TEXT NOT NULL DEFAULT 'CNY',
  营业日 TEXT NOT NULL,
  发生时 TEXT NOT NULL,
  变动额 INTEGER NOT NULL,
  摘要 TEXT NOT NULL DEFAULT '',
  批次编号 TEXT NOT NULL DEFAULT '',
  命运 TEXT NOT NULL DEFAULT '已入账'
);
CREATE TABLE IF NOT EXISTS 抽取批次 (
  编号 TEXT PRIMARY KEY,
  营业日 TEXT NOT NULL,
  时刻 TEXT NOT NULL,
  报告 TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS 周期快照 (
  快照键 TEXT PRIMARY KEY,
  账户键 TEXT NOT NULL,
  币种 TEXT NOT NULL,
  营业日 TEXT NOT NULL,
  余额 INTEGER NOT NULL,
  抽取批次编号 TEXT NOT NULL,
  来源 TEXT NOT NULL DEFAULT '日终抽取',
  状态 TEXT NOT NULL DEFAULT '有效',
  UNIQUE(账户键, 币种, 营业日)
);
CREATE TABLE IF NOT EXISTS 回放批次 (
  编号 TEXT PRIMARY KEY,
  营业日 TEXT NOT NULL,
  时刻 TEXT NOT NULL,
  报告 TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS 差额行 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  回放批次编号 TEXT NOT NULL,
  账户键 TEXT NOT NULL,
  币种 TEXT NOT NULL DEFAULT 'CNY',
  营业日 TEXT NOT NULL,
  快照余额 INTEGER,
  回放余额 INTEGER,
  差额 INTEGER NOT NULL,
  原因 TEXT NOT NULL,
  时刻 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 断档记录 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  账户键 TEXT NOT NULL,
  币种 TEXT NOT NULL DEFAULT 'CNY',
  缺营业日 TEXT NOT NULL,
  检出批次编号 TEXT NOT NULL,
  处置 TEXT NOT NULL DEFAULT '待处理',
  时刻 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 跳变记录 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  账户键 TEXT NOT NULL,
  币种 TEXT NOT NULL DEFAULT 'CNY',
  营业日 TEXT NOT NULL,
  前日余额 INTEGER,
  当日余额 INTEGER,
  流水净额 INTEGER,
  偏离 INTEGER NOT NULL,
  检出批次编号 TEXT NOT NULL,
  时刻 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 旁置簿 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  原因 TEXT NOT NULL,
  账户键 TEXT NOT NULL DEFAULT '',
  营业日 TEXT NOT NULL DEFAULT '',
  载荷 TEXT NOT NULL,
  时刻 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 装载批次 (
  编号 TEXT PRIMARY KEY,
  时刻 TEXT NOT NULL,
  报告 TEXT NOT NULL DEFAULT '{}'
);
"""

空桩模块 = [
    "开户首日无前日",
    "同日重复抽取幂等",
    "流水迟到补抽",
    "销户终镜",
    "负余额闸",
    "半截抽取回滚",
    "快照封印写闸",
    "回放权威择定",
    "断档补齐",
    "断档旁置",
    "跳变阈值",
    "账户分片抽取",
    "抽取时钟漂移",
    "流水序缺口",
    "并户继承镜",
    "子户汇总镜",
    "假期跳日日历",
    "差额分桶",
    "三日连环守恒",
    "抽取重试预算",
    "跨日切点策略",
]


def 此刻() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _迁移旧库(conn) -> None:
    """把单币种旧库补成分轨结构。

    旧库的 周期快照 UNIQUE(账户键, 营业日) 无法容纳同户同日两币种，
    检测到旧约束即按新复合键重建；旧有效镜全部归入 CNY 轨，绝不产生未标币种行。
    """
    def 有列(表: str, 列: str) -> bool:
        return any(r["name"] == 列 for r in conn.execute(f"PRAGMA table_info({表})"))

    if not 有列("账户", "多币种"):
        conn.execute("ALTER TABLE 账户 ADD COLUMN 多币种 INTEGER NOT NULL DEFAULT 0")
    if not 有列("变动流水", "币种"):
        conn.execute("ALTER TABLE 变动流水 ADD COLUMN 币种 TEXT NOT NULL DEFAULT 'CNY'")
    if not 有列("差额行", "币种"):
        conn.execute("ALTER TABLE 差额行 ADD COLUMN 币种 TEXT NOT NULL DEFAULT 'CNY'")
    if not 有列("断档记录", "币种"):
        conn.execute("ALTER TABLE 断档记录 ADD COLUMN 币种 TEXT NOT NULL DEFAULT 'CNY'")
    if not 有列("跳变记录", "币种"):
        conn.execute("ALTER TABLE 跳变记录 ADD COLUMN 币种 TEXT NOT NULL DEFAULT 'CNY'")

    if 有列("周期快照", "币种"):
        return
    conn.executescript(
        """
        CREATE TABLE 周期快照_旧 (
          快照键 TEXT PRIMARY KEY,
          账户键 TEXT NOT NULL,
          营业日 TEXT NOT NULL,
          余额 INTEGER NOT NULL,
          抽取批次编号 TEXT NOT NULL,
          来源 TEXT NOT NULL DEFAULT '日终抽取',
          状态 TEXT NOT NULL DEFAULT '有效'
        );
        INSERT INTO 周期快照_旧 SELECT 快照键, 账户键, 营业日, 余额, 抽取批次编号, 来源, 状态 FROM 周期快照;
        DROP TABLE 周期快照;
        CREATE TABLE 周期快照 (
          快照键 TEXT PRIMARY KEY,
          账户键 TEXT NOT NULL,
          币种 TEXT NOT NULL,
          营业日 TEXT NOT NULL,
          余额 INTEGER NOT NULL,
          抽取批次编号 TEXT NOT NULL,
          来源 TEXT NOT NULL DEFAULT '日终抽取',
          状态 TEXT NOT NULL DEFAULT '有效',
          UNIQUE(账户键, 币种, 营业日)
        );
        INSERT INTO 周期快照(快照键, 账户键, 币种, 营业日, 余额, 抽取批次编号, 来源, 状态)
        SELECT 快照键, 账户键, 'CNY', 营业日, 余额, 抽取批次编号, 来源, 状态 FROM 周期快照_旧;
        DROP TABLE 周期快照_旧;
        """
    )


def 初始化库() -> None:
    conn = 连接()
    conn.executescript(建表)
    _迁移旧库(conn)
    if conn.execute("SELECT COUNT(*) AS c FROM 台参").fetchone()["c"] == 0:
        for k, v in {
            "站名": "日镜账",
            "骨架": "日终余额抽取→周期快照落行→变动流水回放核对→断档跳变检出→快照与回放差额清单",
            "跳变阈值分": "0",
            "断档处置": "记断档并继续",
            "缺前日策略": "以零为开端",
            "重复抽取": "盖写同日快照",
            "币种隔离": "账户+币种+营业日复合键分轨，禁混计，禁止隐式折算",
        }.items():
            conn.execute("INSERT INTO 台参(键, 值) VALUES (?, ?)", (k, v))
    if conn.execute("SELECT COUNT(*) AS c FROM 账户").fetchone()["c"] == 0:
        
        for 键, 名, 币, 多币, 日 in [
            ("户甲", "甲收单户", "CNY", 0, "2026-11-01"),
            ("户乙", "乙结算户", "CNY", 0, "2026-11-01"),
            ("户丙", "丙备用户", "CNY", 0, "2026-11-05"),
            ("户双", "双币种结算户", "CNY", 1, "2026-11-01"),
        ]:
            conn.execute(
                "INSERT INTO 账户(账户键, 户名, 币种, 多币种, 开户营业日, 状态) VALUES (?,?,?,?,?,?)",
                (键, 名, 币, 多币, 日, "正常"),
            )
    conn.commit()
    conn.close()
