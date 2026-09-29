# Per-epoch validation loss of every chosen network configuration, from the
# stage-4 forecast files' meta (read-only diagnostic for the ML audit).
import json
import sys

from backend.market import stage3_io as io

F = "/home/animallya96/deploy/anios/data/market/research/stage4/forecasts/"
out = {}
for fam in ("seq", "cnn_i20"):
    for side in ("buy", "sell"):
        fc = io.load_forecast(F + f"stage4_{fam}_{side}.npz")
        rows = []
        for fo in fc.meta["folds"]:
            ch = fo["chosen"]
            cfg = fo["configs"][ch]
            h = cfg.get("val_loss_history") or []
            rows.append({
                "fold": fo["fold"],
                "test_start": fo["dates"]["test"][0],
                "fit_units": fo["units"]["fit"],
                "val_units": fo["units"]["validation"],
                "chosen": fo["chosen_config"],
                "epochs": cfg["epochs"],
                "best_epoch": cfg["best_epoch"],
                "val_history": [round(x, 5) for x in h],
                "improve_pct": round((h[0] - min(h)) / h[0] * 100, 2) if h else None,
                "all_configs_best_epochs": [c["best_epoch"] for c in fo["configs"]],
                "all_configs_improve_pct": [round((c["val_loss_history"][0] - min(c["val_loss_history"])) / c["val_loss_history"][0] * 100, 2) for c in fo["configs"] if c.get("val_loss_history")],
            })
        out[f"{fam}_{side}"] = rows
for k, rows in out.items():
    print("==", k)
    for r in rows:
        print(f"  fold {r['fold']} test {r['test_start']}: fit {r['fit_units']:,} val {r['val_units']:,}; chosen {r['chosen']}; epochs {r['epochs']} best {r['best_epoch']}; val loss {r['val_history']}; best vs epoch 1: -{r['improve_pct']}%; every config's best epoch {r['all_configs_best_epochs']}; improvement % {r['all_configs_improve_pct']}")
json.dump(out, open(sys.argv[1], "w"), indent=1)
