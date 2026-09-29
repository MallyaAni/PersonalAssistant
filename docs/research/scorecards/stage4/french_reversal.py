"""Decade and VIX splits of the Fama-French short-term reversal portfolios.

Data: Ken French data library (CRSP 202608 vintage), CBOE VIX history.
Long losers minus winners (prior month return), value weighted.
"""
import io
import numpy as np
import pandas as pd

D = "./"  # folder with the unzipped French CSVs and VIX_History.csv


# One monthly block of a French CSV, from the line after its title.
def read_section(path, header_line_idx):
    """Read the monthly block that starts after the given 0-based header title line."""
    lines = open(path).read().splitlines()
    out = []
    hdr = lines[header_line_idx + 1]
    out.append(hdr)
    for ln in lines[header_line_idx + 2:]:
        s = ln.strip()
        if not s or not s[:6].isdigit() or len(s.split(",")[0].strip()) != 6:
            break
        out.append(ln)
    df = pd.read_csv(io.StringIO("\n".join(out)), index_col=0)
    df.index = pd.PeriodIndex([str(i) for i in df.index], freq="M")
    df.columns = [c.strip() for c in df.columns]
    df = df.replace([-99.99, -999], np.nan)
    return df


# The 0-based line index of a block title in a French CSV.
def find(path, title):
    for i, ln in enumerate(open(path).read().splitlines()):
        if ln.strip() == title:
            return i
    raise ValueError(title)


# Newey-West t of a monthly mean (Bartlett weights, `lags` lags).
def nw_t(x, lags=3):
    x = np.asarray(x, float)
    x = x[~np.isnan(x)]
    n = len(x)
    m = x.mean()
    e = x - m
    g0 = (e @ e) / n
    s = g0
    for l in range(1, lags + 1):
        g = (e[l:] @ e[:-l]) / n
        s += 2 * (1 - l / (lags + 1)) * g
    return m / np.sqrt(s / n)


periods = [("1927-1962", "1927-01", "1962-12"), ("1963-1989", "1963-01", "1989-12"),
           ("1990-1999", "1990-01", "1999-12"), ("2000-2009", "2000-01", "2009-12"),
           ("2010-2019", "2010-01", "2019-12"), ("2020-2026:08", "2020-01", "2026-08"),
           ("2010-2026:08", "2010-01", "2026-08"), ("2016-2026:08", "2016-01", "2026-08")]

# 1. ST_Rev factor
f = D + "F-F_ST_Reversal_Factor.csv"
lines = open(f).read().splitlines()
start = [i for i, l in enumerate(lines) if l.strip() == ",ST_Rev"][0]
rows = []
for l in lines[start + 1:]:
    p = l.split(",")
    if len(p) != 2 or len(p[0].strip()) != 6:
        break
    rows.append((p[0].strip(), float(p[1])))
st = pd.Series({pd.Period(a[:4] + "-" + a[4:], "M"): b for a, b in rows})

# 2. 6 portfolios (VW and EW)
f6 = D + "6_Portfolios_ME_Prior_1_0.csv"
vw6 = read_section(f6, find(f6, "Average Value Weighted Returns -- Monthly"))
big_vw = vw6["BIG LoPRIOR"] - vw6["BIG HiPRIOR"]
small_vw = vw6["SMALL LoPRIOR"] - vw6["SMALL HiPRIOR"]

# 3. 25 portfolios: largest quintile (ME5)
f25 = D + "25_Portfolios_ME_Prior_1_0.csv"
vw25 = read_section(f25, find(f25, "Average Value Weighted Returns -- Monthly"))
cols = list(vw25.columns)
me5 = [c for c in cols if c.startswith("BIG") or c.startswith("ME5")]
print("ME5 columns:", me5)
me5_lo = vw25[me5[0]]
me5_hi = vw25[me5[-1]]
me5_ls = me5_lo - me5_hi
me4 = [c for c in cols if c.startswith("ME4")]
me4_ls = vw25[me4[0]] - vw25[me4[-1]]

series = {"ST_Rev (FF factor)": st, "Big half L-H (VW)": big_vw, "Small half L-H (VW)": small_vw,
          "ME quintile 5 L-H (VW)": me5_ls, "ME quintile 4 L-H (VW)": me4_ls}

print("\nMean monthly return % (Newey-West t, 3 lags), by period")
hdr = "{:<26}".format("series") + "".join("{:>16}".format(p[0]) for p in periods)
print(hdr)
for name, s in series.items():
    row = "{:<26}".format(name)
    for _, a, b in periods:
        x = s[pd.Period(a, "M"):pd.Period(b, "M")].dropna()
        row += "{:>16}".format("%.2f (%.1f)" % (x.mean(), nw_t(x.values)))
    print(row)

# 4. VIX conditioning: VIX at end of month t-1 (formation) vs reversal return in month t
vix = pd.read_csv(D + "VIX_History.csv", parse_dates=["DATE"])
vix = vix.set_index("DATE")["CLOSE"]
vix_m = vix.resample("ME").last()
vix_m.index = vix_m.index.to_period("M")
vix_lag = vix_m.shift(1)  # value known at formation (end of prior month)

print("\nReversal return in month t by VIX at end of month t-1 (terciles within window)")
for name in ["ST_Rev (FF factor)", "Big half L-H (VW)", "ME quintile 5 L-H (VW)"]:
    s = series[name]
    for lab, a, b in [("1990-2009", "1990-02", "2009-12"), ("2010-2026:08", "2010-01", "2026-08")]:
        d = pd.concat([s, vix_lag], axis=1, keys=["r", "v"]).loc[pd.Period(a, "M"):pd.Period(b, "M")].dropna()
        q = pd.qcut(d["v"], 3, labels=["low", "mid", "high"])
        g = d.groupby(q, observed=True)["r"].agg(["mean", "count"])
        # slope of r on VIX
        X = np.column_stack([np.ones(len(d)), d["v"].values])
        beta = np.linalg.lstsq(X, d["r"].values, rcond=None)[0]
        resid = d["r"].values - X @ beta
        # NW se for slope (lag 3)
        n = len(d)
        XtX_inv = np.linalg.inv(X.T @ X)
        u = X * resid[:, None]
        S = u.T @ u / n
        for l in range(1, 4):
            G = u[l:].T @ u[:-l] / n
            S += (1 - l / 4) * (G + G.T)
        V = n * XtX_inv @ S @ XtX_inv
        t_slope = beta[1] / np.sqrt(V[1, 1])
        vcut = d["v"].quantile([1/3, 2/3]).values
        print(f"{name:<26} {lab:<13} low {g.loc['low','mean']:.2f}  mid {g.loc['mid','mean']:.2f}  high {g.loc['high','mean']:.2f}  "
              f"(VIX cuts {vcut[0]:.1f}/{vcut[1]:.1f}; n={n})  slope per VIX pt {beta[1]:.3f} (NW t {t_slope:.2f})")

# 5. Long leg (losers minus middle), VIX >= 25 split, and stress months (memo §2.1, §2.3)
long_big = vw6["BIG LoPRIOR"] - vw6["ME2 PRIOR2"]
print("\nBig half, losers minus middle (VW): mean % (NW t)")
for lab, a, b in periods:
    x = long_big[pd.Period(a, "M"):pd.Period(b, "M")].dropna()
    print(f"  {lab:<14} {x.mean():.2f} ({nw_t(x.values):.1f})")

df = pd.concat({"ST_Rev": st, "Big L-H": big_vw, "ME5 L-H": me5_ls, "VIX(t-1)": vix_lag}, axis=1)
for lab, a, b in [("1990-2009", "1990-02", "2009-12"), ("2010-2026:08", "2010-01", "2026-08")]:
    d = df.loc[pd.Period(a, "M"):pd.Period(b, "M")].dropna()
    hi, lo = d[d["VIX(t-1)"] >= 25], d[d["VIX(t-1)"] < 25]
    print(f"\n{lab}: VIX>=25 n={len(hi)} ST_Rev {hi.ST_Rev.mean():.2f} Big {hi['Big L-H'].mean():.2f} ME5 {hi['ME5 L-H'].mean():.2f}"
          f" | VIX<25 n={len(lo)} ST_Rev {lo.ST_Rev.mean():.2f} Big {lo['Big L-H'].mean():.2f} ME5 {lo['ME5 L-H'].mean():.2f}")

print("\nStress months (Big half L-H, %):")
for m in ["2008-10", "2008-11", "2008-12", "2009-02", "2009-03", "2009-04", "2020-03", "2020-04", "2025-05"]:
    print(" ", m, round(float(big_vw[pd.Period(m, "M")]), 2))
x = big_vw[pd.Period("2010-01", "M"):pd.Period("2026-08", "M")]
print(f"\nBig L-H 2010-2026:08: {len(x)} months, share positive {(x > 0).mean():.2f}, sd {x.std():.2f}")
