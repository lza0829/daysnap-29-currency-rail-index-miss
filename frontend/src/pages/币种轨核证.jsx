import React, {useEffect, useState} from "react";
import {api} from "../api.js";

export default function 币种轨核证() {
  const [户, set户] = useState("");
  const [日, set日] = useState("");
  const [证, set证] = useState(null);
  const [讯, set讯] = useState("");

  const 刷新 = () => {
    const q = new URLSearchParams();
    if (户) q.set("账户键", 户);
    if (日) q.set("营业日", 日);
    const qs = q.toString();
    return api.轨核证(qs ? `?${qs}` : "").then(set证);
  };

  useEffect(() => {
    刷新().catch((e) => set讯(String(e.message || e)));
  }, []);

  return (
    <div>
      <h1 className="题">币种轨核证</h1>
      <p className="述">
        口径：<b>账户 + 币种 + 营业日</b> 复合键周期快照。同户同日两币种必须两行；
        禁止未标币种的单行总余额、禁止跨币种并键、禁止隐式折算。本接口只给分轨余额，
        <b>不提供任何跨币合计</b>（合计不可作核销口径）。
      </p>
      <div className="行">
        <input value={户} onChange={(e) => set户(e.target.value)} placeholder="筛选账户键，可空" />
        <input value={日} onChange={(e) => set日(e.target.value)} placeholder="筛选营业日，可空" />
        <button className="次" onClick={() => 刷新().catch((e) => set讯(String(e.message || e)))}>核证</button>
      </div>
      {讯 ? <p className="讯">{讯}</p> : null}
      {证 ? (
        <>
          <div className="行">
            <span className={`徽章 ${证.valid ? "通" : "败"}`}>
              valid：{证.valid ? "通过" : "失败"}
            </span>
            <span className={`徽章 ${证.禁混计 ? "通" : "败"}`}>
              禁混计：{证.禁混计 ? "成立" : "被破坏"}
            </span>
            <span className="徽章 通">禁止隐式折算：{证.禁止隐式折算 ? "是" : "否"}</span>
            <span className="徽章 通">无合计接口：{证.无合计接口 ? "是" : "否"}</span>
          </div>
          <p className="讯">架构：{证.架构} ｜ 分轨余额行数：{证.分轨余额.length}</p>
          {证.违规行?.length ? (
            <div className="段">
              <h2 className="段题">违规行（未标币种 / 混轨）</h2>
              <table>
                <thead><tr><th>快照键</th><th>账户键</th><th>营业日</th></tr></thead>
                <tbody>
                  {证.违规行.map((r, i) => (
                    <tr key={i}><td>{r.快照键 || "—"}</td><td>{r.账户键}</td><td>{r.营业日}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
          <div className="段">
            <h2 className="段题">分轨余额（逐轨列示，不轧总）</h2>
            {!证.分轨余额.length ? (
              <div className="空态">暂无有效镜</div>
            ) : (
              <table>
                <thead>
                  <tr><th>账户键</th><th>币种</th><th>营业日</th><th>余额（分）</th><th>快照键</th></tr>
                </thead>
                <tbody>
                  {证.分轨余额.map((r) => (
                    <tr key={r.快照键}>
                      <td>{r.账户键}</td>
                      <td><span className="徽章 通">{r.币种}</span></td>
                      <td>{r.营业日}</td>
                      <td>{r.余额}</td>
                      <td style={{wordBreak: "break-all"}}>{r.快照键}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </>
      ) : null}
    </div>
  );
}
