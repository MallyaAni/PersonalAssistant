# Validation loss by epoch: the positive-control runs (|g|) next to the registered runs (g), first three folds.
import sys
sys.path.insert(0, r"E:\AgentWorkspace\rtx-s4")
from backend.market import stage3_io as io  # noqa: E402
A = "E:\\AgentWorkspace\\rtx-data\\stage4\\audit\\"
O = "E:\\AgentWorkspace\\rtx-data\\stage4\\out\\"
for fam, af, rf in (("seq", "abs_seq", "stage4_seq"), ("cnn_i20", "abs_cnn", "stage4_cnn_i20")):
    for side in ("buy", "sell"):
        for label, path in (("|g|", A + f"{af}_{side}.npz"), ("g", O + f"{rf}_{side}.npz")):
            fc = io.load_forecast(path)
            parts = []
            for fo in fc.meta["folds"][:3]:
                c = fo["configs"][fo["chosen"]]
                h = c["val_loss_history"]
                parts.append(f"fold {fo['fold']}: best epoch {c['best_epoch']} of {c['epochs']}, val loss {h[0]:.3f} -> {min(h):.3f} ({(h[0]-min(h))/h[0]*100:.1f}% better)")
            print(f"{fam}_{side} {label:>3}: " + "; ".join(parts))
