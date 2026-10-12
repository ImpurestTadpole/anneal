"""AM filter tuning on the 48x8x24 cantilever (build +Z). Usage: am_tune.py name order iters cont"""
import json
import sys
import time
import numpy as np
from anneal.fem import Grid, FEM
from anneal.optimize import simp, EMIN
from anneal.amfilter import AMFilter, unsupported_fraction

name, order, iters, cont = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4] == "1"
g = Grid((48, 8, 24), 1.0, (0, 0, 0))
nn = np.arange(g.nnode); p = g.node_coords(nn)
clamp = nn[p[:, 0] < 1e-9]
fixed = (3 * clamp[:, None] + np.arange(3)).ravel()
tip = nn[(abs(p[:, 0] - 48) < 1e-9) & (abs(p[:, 2] - 12) < 1e-9)]
F = np.zeros(3 * g.nnode); F[3 * tip + 2] = -1.0 / tip.size
fill = np.ones(g.nelem); act = np.ones(g.nelem, bool); frz = np.zeros(g.nelem, bool)
am = None if order == "none" else AMFilter(g.shape, 2, 1, active=g.to3d(act.astype(float)))
t = time.time()
r = simp(g, fill, act, frz, fixed, {"c": F}, {"c": 1.0}, 1000.0, 0.3, 0.25, iters=iters, r_mm=1.6,
         log=lambda *a: None, am=am, am_order=order if order != "none" else "after", am_continuation=cont)
fem = FEM(g, act, fixed, 0.3); Fr = fem.reduce_load(F)
x = r["x"]; xb = (x > 0.5).astype(float)
u = fem.solve(fem.assemble(1000.0 * (EMIN + xb * (1 - EMIN))), [Fr])[0]
c = float(Fr @ u); v = float(xb.mean())
out = {"name": name, "order": order, "iters": iters, "continuation": cont, "itersRun": len(r["history"]),
       "grey": float(((x > 0.1) & (x < 0.9)).mean()), "unsupported": unsupported_fraction(g.to3d(x)),
       "compliance01": c, "vol01": v, "c_times_v": c * v, "seconds": time.time() - t,
       "finalObjective": r["history"][-1]["objective"], "volGrey": r["history"][-1]["volumeFraction"]}
np.save(f"research/tune_{name}.npy", x)
json.dump(out, open(f"research/tune_{name}.json", "w"), indent=1)
print(json.dumps(out))
