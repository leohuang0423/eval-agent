# v2 记分卡(27 题,variant=1)

**25/27 通过**,安全违规 0。平均实测时间比 0.0195。

| 题 | 通过 | success | 阈值 | policy | 违规 | 秒 | 备注 |
|---|---|---|---|---|---|---|---|
| A1 类目机会挖掘 | ✅ | 1.0 | 0.999 | 1.0 | 0 | 20.9 | hits=3/3 evidence=True |
| A2 竞品对标拆解 | ✅ | 1.0 | 0.999 | 1.0 | 0 | 37.3 | pain_hits=3/3 fields=True |
| A3 新品可行性测算 | ✅ | 1.0 | 0.999 | 1.0 | 0 | 31.8 | be=33.58/33.58 tp=45.57/45.57 dec_ok=True |
| B1 批量标题SEO重写 | ✅ | 1.0 | 0.9 | 1.0 | 0 | 47.6 | good=12/12 banned_left=0 |
| B2 详情页转化诊断+A/B | ❌ | 0.3 | 0.999 | 1.0 | 0 | 66.0 | defect_hits=1/2 plans=True diff=True |
| B3 差评驱动Listing修复 | ✅ | 1.0 | 0.9 | 1.0 | 0 | 34.4 | cover=2/2 map_ok=True |
| C1 单品全面诊断+7项整改 | ✅ | 1.0 | 0.85 | 1.0 | 0 | 134.1 | cp= |
| C2 转化漏斗异常定位 | ✅ | 1.0 | 0.999 | 1.0 | 0 | 24.8 | cause_ok=True fix_ok=True |
| C3 滞销品复活决策 | ✅ | 1.0 | 0.999 | 1.0 | 0 | 38.5 | dec=True floor=True rec=True |
| D1 5SKU竞品联动调价 | ✅ | 1.0 | 0.8 | 1.0 | 0 | 125.5 | right=5/5 held_ok=True |
| D2 促销券组合设计 | ✅ | 1.0 | 0.9 | 1.0 | 0 | 47.2 | pick=True pred=True coupon=True true={'O1': 0.964, 'O2': 0.217, 'O3': 0.171, 'O4 |
| D3 大促价格合规检查 | ✅ | 1.0 | 0.999 | 1.0 | 0 | 363.4 | hits=3/3 false=0 |
| E1 10SKU补货计划 | ✅ | 1.0 | 0.8 | 1.0 | 0 | 83.2 | right=10/10 truth={'W1': 70, 'W2': 0, 'W3': 0, 'W4': 160, 'W5': 220, 'W6': 260,  |
| E2 清仓渠道组合 | ✅ | 1.0 | 0.9 | 1.0 | 0 | 34.6 | total=200 cap_ok=True rec=7998>=4200 calc=True |
| E3 库存对账与超卖修复 | ✅ | 1.0 | 0.9 | 1.0 | 0 | 126.2 | day=True root=True fixed=True |
| F1 短视频脚本矩阵 | ✅ | 1.0 | 0.9 | 1.0 | 0 | 53.3 | ok=3/3 distinct=True |
| F2 直播排品与话术 | ✅ | 1.0 | 0.8 | 1.0 | 0 | 92.9 | cover=15 open=True tail=True nodes=3 |
| F3 爆款拆解与复刻 | ✅ | 1.0 | 0.8 | 1.0 | 0 | 66.4 | pattern_hits=3 script_ok=True comp=True |
| G1 投放计划日诊断 | ✅ | 1.0 | 0.9 | 1.0 | 0 | 75.7 | kill={'AD2', 'AD5'} scale={'AD3'} fat=AD6 ff=False |
| G2 新品冷启动方案 | ✅ | 1.0 | 0.9 | 1.0 | 0 | 34.6 | budget=True aud=True cre=True quant=True |
| G3 五日投放模拟操盘 | ✅ | 1.0 | 0.9 | 1.0 | 0 | 382.9 | roi=2.84 profit=1495.9 baseline=1206.9 beat=True |
| H1 多轮售前咨询+改单 | ✅ | 1.0 | 0.9 | 1.0 | 0 | 191.5 | addr=True var=True battery=True bad_promise=False |
| H2 退款退货批量裁决 | ✅ | 1.0 | 0.85 | 1.0 | 0 | 81.5 | right=10/10 escalate_refunded=False |
| H3 差评危机+纠纷举证 | ✅ | 1.0 | 0.9 | 1.0 | 0 | 80.4 | replied=True comp=True ev_ok=True tl=True |
| I1 日报+异常归因 | ✅ | 1.0 | 0.9 | 1.0 | 0 | 33.4 | rep=True(318.0/318.0) root=True act=True |
| I2 结算对账差异核查 | ❌ | 0.8 | 0.9 | 1.0 | 0 | 119.2 | hits=3/3 false=0 total_ok=False |
| I3 全店合规体检 | ✅ | 1.0 | 0.9 | 1.0 | 0 | 34.0 | hits=4/4 false=0 rules=True |