# ML audit evaluation (read-only): out-of-sample skill of the positive-control
# runs (the same code trained on |g|) against the registered runs (on g).
import json
import sys

import numpy as np

sys.path.insert(0, r"E:\AgentWorkspace\rtx-s4")
from backend.market import stage3_io as io  # noqa: E402
from backend.cli import market_stage4_labels as lab  # noqa: E402

A = "E:\\AgentWorkspace\\rtx-data\\stage4\\audit\\"
O = "E:\\AgentWorkspace\\rtx-data\\stage4\\out\\"
dates, tickers, g_buy, g_sell, _ = lab.load("E:\\AgentWorkspace\\rtx-data\\stage4\\stage4_labels.npz")
labels = {"buy": g_buy, "sell": g_sell}


# Pooled Spearman and the mean per-date Spearman IC over finite pairs.
def skill(yhat, y, d):
    keep = np.isfinite(yhat) & np.isfinite(y)
    pooled = io.spearman(yhat[keep], y[keep])
    ics = []
    for day in np.unique(d[keep]):
        m = keep & (d == day)
        if m.sum() >= 5:
            v = io.spearman(yhat[m], y[m])
            if np.isfinite(v):
                ics.append(v)
    return int(keep.sum()), pooled, float(np.mean(ics)) if ics else float("nan"), len(ics)


out = {}
for fam, files in (("lgbm", ("abs_lgbm", "stage4_lgbm")), ("cnn_i20", ("abs_cnn", "stage4_cnn_i20")), ("seq", ("abs_seq", "stage4_seq"))):
    for side in ("buy", "sell"):
        audit = io.load_forecast(A + f"{files[0]}_{side}.npz")
        reg = io.load_forecast(O + f"{files[1]}_{side}.npz")
        y = labels[side]
        a_rows = np.isfinite(audit.yhat)
        n1, p1, ic1, d1 = skill(audit.yhat, np.abs(y), dates)
        # The registered run on the same rows as the audit run (its first folds for the networks).
        reg_yhat = np.where(a_rows, reg.yhat, np.nan)
        n2, p2, ic2, d2 = skill(reg_yhat, y, dates)
        # And the registered run's magnitude skill, for reference: does its forecast rank |g|?
        n3, p3, ic3, _ = skill(np.abs(reg_yhat), np.abs(y), dates)
        last = str(dates[a_rows].max()) if a_rows.any() else None
        out[f"{fam}_{side}"] = {
            "test_rows": n1, "test_dates": [str(dates[a_rows].min()), last],
            "abs_target": {"pooled_spearman": p1, "mean_daily_ic": ic1, "days": d1},
            "signed_target_registered": {"pooled_spearman": p2, "mean_daily_ic": ic2, "days": d2},
            "registered_abs_forecast_vs_abs_label": {"pooled_spearman": p3, "mean_daily_ic": ic3},
        }
        print(f"{fam}_{side}: {n1:,} test rows {out[f'{fam}_{side}']['test_dates']}; |g| target: pooled {p1:+.3f}, daily IC {ic1:+.3f} | g target (registered, same rows): pooled {p2:+.3f}, daily IC {ic2:+.3f}")
json.dump(out, open(A + "eval_audit.json", "w"), indent=1)
