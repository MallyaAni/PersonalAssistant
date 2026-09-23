from engine import *
import engine, pandas as pd
irx=np.nan_to_num(CLOSE[:,IDX["^IRX"]])/100

def policy_wrapper2(policy, every=20, index_eligible=False, **kw):
    """GPT's funded path with the new budget parameters (merged branch code)."""
    state={"comp":None,"n":0}; prices=np.where(np.isfinite(CLOSE),CLOSE,np.nan)
    def f(t,held):
        if state["comp"] is None or state["n"]%every==0: state["comp"]=incumbent_weights(t)
        state["n"]+=1
        desired={k:v for k,v in state["comp"].items() if v>0}
        h={k:v for k,v in held.items() if k in IDX and v>0}; tot=sum(h.values())
        if tot>1: h={k:v/tot for k,v in h.items()}
        d=alloc.decide(DATES[:t+1],prices[:t+1],TICK,t,desired,h,regime_cap=1.0,event_cap=1.0,policy=policy,index_eligible=index_eligible,**kw)
        return d.desired_weights
    return f

class BookQ(Book):
    """A3 overlay but the braked half is parked in QQQ instead of cash."""
    def __call__(self,t,held):
        out=super().__call__(t,held)
        if out is None: return None
        gross=sum(v for k,v in self.comp.items()); s=self.scale
        if s<1.0:
            out=dict(out); out["QQQ"]=out.get("QQQ",0)+gross*(1-s)
        return out

W=[("2016-01-04",None,"2016-26"),("2016-01-04","2020-12-31","2016-20"),("2021-01-04",None,"2021-26")]
cfg=[
 ("QQQ", None),
 ("A1 hold20 + deferred buy leg", lambda: dict(fn=Book(deferred=True),recycle=False)),
 ("A3 A1 + trend brake (hysteresis) -> cash", lambda: dict(fn=Book(deferred=True,overlay='trend_hyst'),recycle=False)),
 ("A3q A1 + trend brake -> park in QQQ", lambda: dict(fn=BookQ(deferred=True,overlay='trend_hyst'),recycle=False)),
 ("vol_trend fixed: hysteresis + QQQx1.5 budget + SPY residual", lambda: dict(fn=policy_wrapper2('vol_trend',index_eligible=True,budget_reference='qqq',budget_multiplier=1.5),recycle=False,min_trade=0.005)),
 ("vol_trend fixed: hysteresis + QQQx2 budget, no residual", lambda: dict(fn=policy_wrapper2('vol_trend',budget_reference='qqq',budget_multiplier=2.0),recycle=False,min_trade=0.005)),
 ("vol_trend as GPT built it (min budget), now with hysteresis", lambda: dict(fn=policy_wrapper2('vol_trend'),recycle=False,min_trade=0.005,sell_threshold=0.0)),
]
rows=[]
for s,e,lab in W:
    for name,mk in cfg:
        if mk is None: r=buy_hold(name,s,e)[1]
        else:
            k=mk(); fn=k.pop('fn'); r=run(fn,s,e,cash_yield=irx,**k)[1]
        r['name']=name; r['window']=lab; rows.append(r)
df=pd.DataFrame(rows); pd.set_option("display.width",250)
for lab in [w[2] for w in W]:
    print("==",lab); print(df[df.window==lab].drop(columns='window').set_index('name').round(3).to_string())
df.to_csv("run5.csv",index=False)
