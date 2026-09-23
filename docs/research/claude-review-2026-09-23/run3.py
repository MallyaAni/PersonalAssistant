from engine import *
import pandas as pd
irx=np.nan_to_num(CLOSE[:,IDX["^IRX"]])/100
W=[("2016-01-04",None,"full 2016-26"),("2016-01-04","2020-12-31","2016-20"),("2021-01-04",None,"2021-26")]
cfg=[("SPY",lambda:None),("QQQ",lambda:None),
 ("A live-like: hold20, sells@close no recycle",lambda:dict(fn=Book(),recycle=False)),
 ("A1 + deferred next-day buy leg",lambda:dict(fn=Book(deferred=True),recycle=False)),
 ("A2 recycle proceeds (upper bound)",lambda:dict(fn=Book(),recycle=True)),
 ("A3 A1 + trend overlay w/ hysteresis",lambda:dict(fn=Book(deferred=True,overlay='trend_hyst'),recycle=False)),
 ("A4 A1 + vol cap 1.25x QQQ vol",lambda:dict(fn=Book(deferred=True,overlay='vol_qqq'),recycle=False)),
 ("GPT vol (as built)",lambda:dict(fn=policy_wrapper('vol'),recycle=False,min_trade=0.005,sell_threshold=0.0)),
 ("GPT vol_trend (as built)",lambda:dict(fn=policy_wrapper('vol_trend'),recycle=False,min_trade=0.005,sell_threshold=0.0)),
]
rows=[]
for s,e,lab in W:
    for name,mk in cfg:
        if name in("SPY","QQQ"):
            r=buy_hold(name,s,e)[1]
        else:
            k=mk(); fn=k.pop('fn'); r=run(fn,s,e,cash_yield=irx,**k)[1]
        r['name']=name; r['window']=lab; rows.append(r)
df=pd.DataFrame(rows)
pd.set_option("display.width",250)
for lab in [w[2] for w in W]:
    print("==",lab); print(df[df.window==lab].drop(columns='window').set_index('name').round(3).to_string())
df.to_csv("run3.csv",index=False)
