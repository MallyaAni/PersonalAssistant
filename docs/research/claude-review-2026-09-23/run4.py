"""Test of the 'in volatile names on green days, in the index on potential red days' idea.
All signals are decided at close t from data <= t; the switch executes at the open of t+1."""
from engine import *
import pandas as pd
irx=np.nan_to_num(CLOSE[:,IDX["^IRX"]])/100
Q=IDX["QQQ"]

class Rotator:
    """Hold-20 momentum book; each close decide: stay in the book or park the book's
    exposure in QQQ for the next session, by `signal`. Trades only on a state change."""
    def __init__(self, signal, every=20):
        self.signal, self.every = signal, every
        self.comp=None; self.n=0; self.state=None; self.hist=[]
    def book_ret(self, t):
        cols=[IDX[k] for k in self.comp]; w=np.array(list(self.comp.values()))
        if not len(w): return 0.0
        r=RET[t,cols]; return float(np.nansum(r*w)/w.sum())
    def __call__(self, t, held):
        reb = self.comp is None or self.n % self.every == 0
        self.n += 1
        if reb: self.comp = incumbent_weights(t)
        gross = sum(self.comp.values())
        self.hist.append(self.book_ret(t))
        want_book = self.signal(self, t)
        if reb or want_book != self.state:
            self.state = want_book
            if want_book: return dict(self.comp)
            return {"QQQ": gross}
        return None

def ew_book_series(t, n):
    """Trailing n-session equal-weight return series of the current top-decile names."""
    return None

def s_follow(self_, t):   # green today -> stay tomorrow
    return self_.hist[-1] > 0
def s_revert(self_, t):   # red today -> in tomorrow (buy the dip), green -> park
    return self_.hist[-1] <= 0
def s_qqq10(self_, t):
    q=CLOSE[:t+1,Q]; return q[-1] > q[-10:].mean()
def s_volspike(self_, t):
    h=np.array(self_.hist);
    if len(h)<60: return True
    return h[-5:].std() <= 1.5*h[-60:].std()
def s_stretch(self_, t):  # book more than 2 sigma above its 21-day mean -> expect red -> park
    h=np.array(self_.hist)
    if len(h)<21: return True
    lvl=np.cumsum(h); ema=lvl[-21:].mean(); sd=h[-21:].std()*np.sqrt(21)
    return (lvl[-1]-ema) <= 2*sd if sd>0 else True
def s_dipentry(self_, t):  # in the book only after a pullback: 5-day book return < 0
    h=np.array(self_.hist)
    if len(h)<5: return True
    return h[-5:].sum() < 0
def s_combo(self_, t):
    return s_qqq10(self_,t) and s_stretch(self_,t)
def s_always(self_, t): return True

class Oracle(Rotator):
    """Perfect foresight of tomorrow's book return (NOT causal) - the ceiling of the idea."""
    def __call__(self, t, held):
        reb = self.comp is None or self.n % self.every == 0
        self.n += 1
        if reb: self.comp = incumbent_weights(t)
        gross=sum(self.comp.values())
        cols=[IDX[k] for k in self.comp]; w=np.array(list(self.comp.values()))
        nxt=float(np.nansum(RET[t+1,cols]*w)/w.sum()) if len(w) else 0
        want = nxt > RET[t+1,Q]
        if reb or want != self.state:
            self.state=want; return dict(self.comp) if want else {"QQQ":gross}
        return None

W=[("2016-01-04",None,"2016-26"),("2016-01-04","2020-12-31","2016-20"),("2021-01-04",None,"2021-26")]
sigs=[("always in book (baseline)",s_always),("green today -> stay, red -> QQQ",s_follow),
      ("red today -> in, green -> QQQ (buy dips)",s_revert),("QQQ above 10d mean -> book else QQQ",s_qqq10),
      ("vol spike -> QQQ",s_volspike),("book > +2sd stretch -> QQQ",s_stretch),
      ("5-day pullback -> in, else QQQ",s_dipentry),("QQQ 10d & not stretched",s_combo)]
rows=[]
for s,e,lab in W:
    rows.append(dict(buy_hold("QQQ",s,e)[1],window=lab))
    for name,sig in sigs:
        r=run(Rotator(sig),s,e,cash_yield=irx,recycle=True,min_trade=0.005)[1]; r['name']=name; r['window']=lab; rows.append(r)
    r=run(Oracle(s_always),s,e,cash_yield=irx,recycle=True,min_trade=0.005)[1]; r['name']="ORACLE: knows tomorrow (not causal)"; r['window']=lab; rows.append(r)
    r=run(Oracle(s_always),s,e,cash_yield=irx,recycle=True,min_trade=0.005,cost_bps=0)[1]; r['name']="ORACLE, zero cost"; r['window']=lab; rows.append(r)
df=pd.DataFrame(rows); pd.set_option("display.width",250)
for lab in [w[2] for w in W]:
    print("==",lab); print(df[df.window==lab].drop(columns='window').set_index('name').round(3).to_string())
df.to_csv("run4.csv",index=False)
