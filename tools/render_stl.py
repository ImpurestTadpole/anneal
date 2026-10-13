"""Quick shaded pictures of STL files: python tools/render_stl.py out.png "Title A" a.stl "Title B" b.stl ..."""
import sys
import numpy as np
import trimesh
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

out, args = sys.argv[1], sys.argv[2:]
pairs = list(zip(args[::2], args[1::2]))
meshes = [trimesh.load(f) for _, f in pairs]
lo = np.min([m.bounds[0] for m in meshes], 0)
hi = np.max([m.bounds[1] for m in meshes], 0)
c, r = (lo + hi) / 2, (hi - lo).max() / 2
fig = plt.figure(figsize=(5.5 * len(pairs), 5), facecolor="#f4f6f8")
light = np.array([0.4, -0.5, 0.8]) / np.linalg.norm([0.4, -0.5, 0.8])
for i, ((title, _), m) in enumerate(zip(pairs, meshes)):
    ax = fig.add_subplot(1, len(pairs), i + 1, projection="3d", facecolor="#f4f6f8")
    shade = 0.25 + 0.75 * np.clip(m.face_normals @ light, 0, 1)
    ax.add_collection3d(Poly3DCollection(m.triangles, facecolors=plt.cm.Greys(0.25 + 0.6 * shade), edgecolor="none"))
    for k, f in enumerate((ax.set_xlim, ax.set_ylim, ax.set_zlim)):
        f(c[k] - r, c[k] + r)
    ax.set_box_aspect((1, 1, 1))
    ax.view_init(22, -60)
    ax.set_title(title, fontsize=11)
    ax.set_axis_off()
plt.tight_layout()
plt.savefig(out, dpi=90, facecolor="#f4f6f8")
