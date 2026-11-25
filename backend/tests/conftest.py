import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app import db, seed


@pytest.fixture
def 库(tmp_path, monkeypatch):
    """每个测试一个隔离 sqlite 库。"""
    monkeypatch.setattr(db, "库路径", tmp_path / "测-日镜.db")
    seed.初始化库()
    return db


def 清业务(db):
    conn = db.连接()
    try:
        for t in (
            "变动流水",
            "抽取批次",
            "周期快照",
            "回放批次",
            "差额行",
            "断档记录",
            "跳变记录",
            "旁置簿",
            "装载批次",
        ):
            conn.execute(f"DELETE FROM {t}")
        conn.commit()
    finally:
        conn.close()
