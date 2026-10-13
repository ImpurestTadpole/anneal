"""Does the overhang filter build support under a frozen load boss? Usage: am_frozen.py mode
mode: plain | keep (frozen printed as specified, 0.4.0-rc behaviour) | nokeep (frozen must be supported)"""
import json
import sys
import time
import numpy as np
from anneal.fem import Grid, FEM
from anneal.optimize import simp, EMIN
from anneal.amfilter import AMFilter, unsupported_fraction

mode = sys.argv[1]
g = Grid((48, 8, 24), 1.0, (0, 0, 0))
nn = np.arange(g.nnode); p = g.node_coords(nn)
clamp = nn[p[:, 0] < 1e-9]
fixed = (3 * clamp[:, None] + np.arange(3)).ravel()
tip = nn[(abs(p[:, 0] - 48) < 1e-9) & (abs(p[:, 2] - 12) < 1e-9)]
F = np.zeros(3 * g.nnode); F[3 * tip + 2] = -1.0 / tip.size
i, j, k = g.elem_ijk(np.arange(g.nelem))
frz = (i >= 42) & (k >= 9) & (k < 16)                  # load boss floating at mid-height
fill = np.ones(g.nelem); act = np.ones(g.nelem, bool)
A3, K3 = g.to3d(act.astype(float)), g.to3d(frz.astype(float))
am = None if mode == "plain" else AMFilter(g.shape, 2, 1, active=A3, keep=K3 if mode == "keep" else None)
t = time.time()
r = simp(g, fill, act, frz, fixed, {"c": F}, {"c": 1.0}, 1000.0, 0.3, 0.25, iters=120, r_mm=1.6,
         log=lambda *a: None, am=am)
x = r["x"].copy()
xb = np.maximum((x > 0.5), frz).astype(float)           # as built: frozen boss always present
fem = FEM(g, act, fixed, 0.3); Fr = fem.reduce_load(F)
u = fem.solve(fem.assemble(1000.0 * (EMIN + xb * (1 - EMIN))), [Fr])[0]
c = float(Fr @ u); v = float(xb.mean())
out = {"mode": mode, "unsupported_incl_boss": unsupported_fraction(g.to3d(xb)),
       "grey": float(((x > 0.1) & (x < 0.9)).mean()), "c_times_v": c * v, "vol01": v, "seconds": time.time() - t}
# voxels of the boss's lowest layer that have solid support below
s = g.to3d(xb)
low = s[42:, :, 9]; below = np.pad(s[:, :, 8], 1)
sup = np.maximum.reduce([below[43:-1, 1:-1], below[44:, 1:-1], below[42:-2, 1:-1], below[43:-1, 2:], below[43:-1, :-2]])
out["boss_bottom_supported_share"] = float((sup[low > 0] > 0).mean())
np.save(f"research/frozen_{mode}.npy", x)
print(json.dumps(out))
json.dump(out, open(f"research/frozen_{mode}.json", "w"))
