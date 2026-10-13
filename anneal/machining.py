"""CNC machining (3-axis and 5-axis): an optimizer filter and machinability checks.

Milling filter (3-axis, in the optimizer)
    A 3-axis cutter reaches a point only along the tool axis of a setup. From the top (+Z) it
    removes material from above, so a void can only exist where everything above it is void too.
    The filter makes every design obey that: the physical density at a voxel is the smooth maximum of
    the densities on the tool side of it (a cumulative maximum along the tool axis; Gersborg and
    Andreasen 2011 use the same idea for casting). With several setups a voxel may be cut from any
    of them, so the result is the smooth minimum over the setups. The filter only adds material, so
    frozen supports and loads stay. Applied after the projection step.

Machinability check (3-axis and 5-axis, after the run)
    On the as-built voxels: the cutter centre must stay half a tool diameter away from the part
    (distance transform of the empty space), and it must reach each centre in a straight line from
    outside along an allowed direction (the setup axes for 3-axis; the 26 grid directions on the open
    side of the fixture for 5-axis). The space the cutter sweeps is those centres grown by the tool
    radius. Part surface next to empty space the cutter cannot sweep is not machinable: an undercut,
    a slot narrower than the tool, or an inside corner sharper than the tool radius.
"""
import numpy as np
from scipy import ndimage

AXES = {"+x": (0, 1), "-x": (0, -1), "+y": (1, 1), "-y": (1, -1), "+z": (2, 1), "-z": (2, -1)}
EPS = 1e-8


def _smax(a, b):
    r = np.sqrt((a - b) ** 2 + EPS)
    return 0.5 * (a + b + r) - 0.5 * np.sqrt(EPS), 0.5 * (1 + (a - b) / r), 0.5 * (1 - (a - b) / r)


def _smin(a, b):
    r = np.sqrt((a - b) ** 2 + EPS)
    return 0.5 * (a + b - r) + 0.5 * np.sqrt(EPS), 0.5 * (1 - (a - b) / r), 0.5 * (1 + (a - b) / r)


class MillFilter:
    """setups: names like "+z" = the tool comes from the +Z side."""

    def __init__(self, shape, setups):
        self.shape = tuple(shape)
        self.setups = [AXES[s.lower()] for s in setups]
        if not self.setups:
            raise ValueError("A 3-axis process needs at least one setup direction, for example [\"+z\"].")

    @staticmethod
    def _to(a, ax, sg):          # tool side last along axis 2 index nz-1 ... we process from the tool side
        a = np.moveaxis(a, ax, 2)
        return a if sg > 0 else a[:, :, ::-1]

    @staticmethod
    def _back(a, ax, sg):
        a = a if sg > 0 else a[:, :, ::-1]
        return np.moveaxis(a, 2, ax)

    def _cummax(self, x3, ax, sg):
        x = np.ascontiguousarray(self._to(x3, ax, sg))
        n = x.shape[2]
        y = np.empty_like(x)
        da = np.ones_like(x)
        db = np.zeros_like(x)
        y[:, :, n - 1] = x[:, :, n - 1]                 # the voxel nearest the tool
        for k in range(n - 2, -1, -1):
            y[:, :, k], da[:, :, k], db[:, :, k] = _smax(x[:, :, k], y[:, :, k + 1])
        return y, (da, db)

    def _cummax_T(self, g3, cache, ax, sg):
        da, db = cache
        g = np.ascontiguousarray(self._to(g3, ax, sg))
        n = g.shape[2]
        out = np.zeros_like(g)
        lam = np.zeros(g.shape[:2])
        for k in range(0, n):
            lam = g[:, :, k] + lam               # total dF/dy_k (from y_k itself and from y_{k-1})
            out[:, :, k] = lam * da[:, :, k]
            lam = lam * db[:, :, k]
        return self._back(out, ax, sg)

    def forward(self, x3):
        x3 = np.asarray(x3, float)
        self._c = []
        res = None
        for ax, sg in self.setups:
            y, cache = self._cummax(x3, ax, sg)
            y = self._back(y, ax, sg)
            if res is None:
                res, dres = y, [np.ones_like(y)]
                self._c.append((ax, sg, cache))
            else:
                res, d1, d2 = _smin(res, y)
                dres = [d * d1 for d in dres] + [d2]
                self._c.append((ax, sg, cache))
        self._d = dres
        return res

    def backward(self, g3):
        g3 = np.asarray(g3, float)
        out = np.zeros_like(g3)
        for (ax, sg, cache), d in zip(self._c, self._d):
            out += self._cummax_T(g3 * d, cache, ax, sg)
        return out

    def state(self):
        return (self._c, self._d)

    def restore(self, s):
        self._c, self._d = s


# ---------------------------------------------------------------- machinability check
def directions(axes, setups, fixture="-z"):
    if int(axes) == 3:
        return [np.array(v, int) for v in ({"+x": (1, 0, 0), "-x": (-1, 0, 0), "+y": (0, 1, 0), "-y": (0, -1, 0),
                                             "+z": (0, 0, 1), "-z": (0, 0, -1)}[s.lower()] for s in setups)]
    fx = {"+x": (1, 0, 0), "-x": (-1, 0, 0), "+y": (0, 1, 0), "-y": (0, -1, 0), "+z": (0, 0, 1), "-z": (0, 0, -1)}[fixture.lower()]
    out = []
    for i in (-1, 0, 1):
        for j in (-1, 0, 1):
            for k in (-1, 0, 1):
                d = np.array([i, j, k])
                if d.any() and d @ np.array(fx) <= 0:      # not into the fixture
                    out.append(d)
    return out


def _reach(free, d):
    """free cells that see the outside of the grid along +d in a straight line."""
    A = np.zeros_like(free)
    pad = np.pad(free, 1, constant_values=True)
    R = np.pad(A, 1, constant_values=True)
    sl = tuple(slice(1, -1) for _ in range(3))
    sh = tuple(slice(1 + d[i], free.shape[i] + 1 + d[i]) for i in range(3))
    for _ in range(int(max(free.shape)) + 1):
        new = pad[sl] & R[sh]
        if (new == R[sl]).all():
            break
        R[sl] = new
    return R[sl]


def assess(solid3, h, tool_d, dirs):
    """Machinability of a voxel part. Returns dict with unreachable surface area and a mask."""
    solid = np.asarray(solid3, bool)
    pad = int(np.ceil(tool_d / h)) + 2
    S = np.pad(solid, pad, constant_values=False)
    free = ~S
    dist = ndimage.distance_transform_edt(free) * h          # distance from each empty cell to the part
    centre_ok = dist >= tool_d / 2 - 1e-9
    reach = np.zeros_like(free)
    for d in dirs:
        reach |= _reach(centre_ok, d)
    # cells swept by the cutter: reachable centres grown by the tool radius
    r = tool_d / 2 / h
    sweep = ndimage.distance_transform_edt(~reach) <= r + 1e-9
    # only the stock matters: empty cells inside the part's bounding box (outside it there is no
    # material to cut; faces on the box are faces of the stock)
    idx = np.argwhere(S)
    stock = np.zeros_like(S)
    lo, hi = idx.min(0), idx.max(0) + 1
    stock[lo[0]:hi[0], lo[1]:hi[1], lo[2]:hi[2]] = True
    unreached = free & ~sweep & stock
    # deepest cut below the stock face along each tool axis (tool reach)
    depth = 0.0
    for d in dirs:
        if np.count_nonzero(d) != 1:
            continue
        ax = int(np.flatnonzero(d)[0])
        cut = free & sweep & stock
        if not cut.any():
            continue
        coords = np.argwhere(cut)[:, ax]
        face = hi[ax] if d[ax] > 0 else lo[ax]
        depth = max(depth, float(np.abs(face - coords).max()) * h)
    # part surface faces next to unreached empty space
    area_faces = 0
    for ax in range(3):
        for sh in (1, -1):
            nb = np.roll(unreached, sh, axis=ax)
            area_faces += int((S & nb).sum())
    total_faces = 0
    for ax in range(3):
        for sh in (1, -1):
            total_faces += int((S & np.roll(free, sh, axis=ax)).sum())
    sl = tuple(slice(pad, -pad) for _ in range(3))
    return {"unreachableAreaMM2": area_faces * h * h, "surfaceAreaMM2": total_faces * h * h,
            "unreachableShare": area_faces / max(total_faces, 1),
            "unreachableVolumeMM3": float(unreached[sl].sum() * h ** 3), "deepestCutMM": depth,
            "stockMM": ((hi - lo) * h).tolist(), "stockVolumeMM3": float(np.prod(hi - lo) * h ** 3),
            "mask": unreached[sl]}
