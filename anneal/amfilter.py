"""Overhang (AM) filter for SIMP: Langelaar's layer-by-layer printability filter.

Langelaar 2016, Additive Manufacturing 12:60-70 (3-D); Langelaar 2017, Struct. Multidisc.
Optim. 55(3):871-883 (2-D). Each voxel's printed density may not exceed a smooth maximum of
the printed densities in its support region: the voxel directly below and that voxel's four
in-layer neighbours. On cubic voxels this is a 45 degree overhang limit.

Differences from the papers, found while testing Anneal (roadmap verification, 2026-10-12):
- The derivative of the smooth maximum is evaluated in logarithms. The direct product gives
  inf * 0 = NaN when a support region is almost empty, and the solver then fails.
- The build plate is the lowest layer that holds design-space voxels, not grid layer 0
  (Anneal pads the grid, so layer 0 is empty and would starve every layer above it).
- Frozen voxels (anchors, keep-ins) are printed as specified. They may need support, which the
  DFM report still measures.

Arrays are indexed [i, j, k] like Grid.to3d. build_axis 0/1/2; sign +1 builds toward
increasing index along that axis.
"""
import numpy as np

AXES = {"+x": (0, 1), "-x": (0, -1), "+y": (1, 1), "-y": (1, -1), "+z": (2, 1), "-z": (2, -1)}


def axis_of(direction):
    """Map a build direction vector such as [0, 0, 1] to (axis, sign). Only axis directions."""
    d = np.asarray(direction, float)
    a = int(np.argmax(np.abs(d)))
    if np.abs(d).sum() - abs(d[a]) > 1e-9:
        raise ValueError("The overhang filter supports only build directions along x, y or z.")
    return a, (1 if d[a] > 0 else -1)


class AMFilter:
    def __init__(self, shape, build_axis=2, sign=1, active=None, keep=None, P=40.0, eps=1e-4, xi0=0.5):
        self.shape, self.ax, self.sign = tuple(shape), int(build_axis), int(sign)
        self.P, self.eps = float(P), float(eps)
        self.set_xi0(xi0)
        self.keep = None if keep is None else self._to(np.asarray(keep, float))
        self.base = 0
        if active is not None:
            a = self._to(np.asarray(active, float))
            layers = np.flatnonzero(a.reshape(-1, a.shape[2]).max(0) > 0)
            self.base = int(layers[0]) if layers.size else 0
        self._cache = None

    def set_xi0(self, xi0):
        """xi0: density at which the smooth maximum of a full support region is exact."""
        self.xi0 = float(xi0)
        self.Q = self.P + np.log(5.0) / np.log(self.xi0)

    def _to(self, a):
        a = np.moveaxis(a, self.ax, 2)
        return a[:, :, ::-1] if self.sign < 0 else a

    def _back(self, a):
        a = a[:, :, ::-1] if self.sign < 0 else a
        return np.moveaxis(a, 2, self.ax)

    @staticmethod
    def _stencil(a):
        p = np.pad(a, 1)
        return np.stack([p[1:-1, 1:-1], p[2:, 1:-1], p[:-2, 1:-1], p[1:-1, 2:], p[1:-1, :-2]])

    @staticmethod
    def _stencil_T(s):
        p = np.zeros((s.shape[1] + 2, s.shape[2] + 2))
        p[2:, 1:-1] += s[1]
        p[:-2, 1:-1] += s[2]
        p[1:-1, 2:] += s[3]
        p[1:-1, :-2] += s[4]
        return s[0] + p[1:-1, 1:-1]

    def forward(self, x3):
        x = np.ascontiguousarray(self._to(np.asarray(x3, float)))
        nz = x.shape[2]
        xi = np.zeros_like(x)
        b = min(self.base, nz - 1)
        xi[:, :, :b + 1] = x[:, :, :b + 1]
        cache = []
        e = self.eps
        for k in range(b + 1, nz):
            st = self._stencil(xi[:, :, k - 1])
            sp_ = (st ** self.P).sum(0)
            sig = sp_ ** (1.0 / self.Q)
            xk = x[:, :, k]
            r = np.sqrt((xk - sig) ** 2 + e)
            v = 0.5 * (xk + sig - r + np.sqrt(e))
            dx = 0.5 * (1 - (xk - sig) / r)
            ds = 0.5 * (1 + (xk - sig) / r)
            if self.keep is not None:
                kk = self.keep[:, :, k] > 0
                v = np.where(kk, xk, v)
                dx = np.where(kk, 1.0, dx)
                ds = np.where(kk, 0.0, ds)
            xi[:, :, k] = v
            with np.errstate(divide="ignore", over="ignore"):
                ls = np.log(np.maximum(st, 1e-300))
                lsp = np.log(np.maximum(sp_, 1e-300))
                dsig = np.where(st > 1e-30,
                                (self.P / self.Q) * np.exp((self.P - 1) * ls + (1.0 / self.Q - 1) * lsp), 0.0)
            cache.append((dx, ds, dsig))
        self._cache = (b, cache)
        return self._back(xi)

    def backward(self, g3):
        """dF/d(blueprint) from dF/d(printed), at the point of the last forward()."""
        b, cache = self._cache
        g = np.ascontiguousarray(self._to(np.asarray(g3, float)))
        nz = g.shape[2]
        out = np.zeros_like(g)
        lam = g[:, :, nz - 1].copy()
        for k in range(nz - 1, b, -1):
            dx, ds, dsig = cache[k - b - 1]
            out[:, :, k] = lam * dx
            lam = g[:, :, k - 1] + self._stencil_T((lam * ds)[None] * dsig)
        out[:, :, b] = lam
        out[:, :, :b] = g[:, :, :b]
        return self._back(out)

    def state(self):
        return self._cache

    def restore(self, c):
        self._cache = c


def unsupported_fraction(x3, build_axis=2, sign=1, thr=0.5, active=None):
    """Fraction of solid voxels above the plate layer with nothing solid in their support region."""
    f = AMFilter(np.shape(x3), build_axis, sign, active=active)
    s = f._to((np.asarray(x3) > thr).astype(float))
    bad = tot = 0
    for k in range(f.base + 1, s.shape[2]):
        sup = f._stencil(s[:, :, k - 1]).max(0)
        lay = s[:, :, k] > 0
        bad += int((lay & (sup == 0)).sum())
        tot += int(lay.sum())
    return bad / max(tot, 1)


def design_space_check(active3, keep3=None, threshold=0.5):
    """Share of the design space that cannot print without support, per axis direction: the
    filter applied to a completely solid design space. If this is large, the optimizer cannot
    connect the part along that direction, whatever it does (the design space overhangs)."""
    out = {}
    a = np.asarray(active3, float)
    for name, (ax, sg) in AXES.items():
        y = AMFilter(a.shape, ax, sg, active=a, keep=keep3).forward(a)
        out[name] = float(((a > 0) & (y < threshold)).sum() / max((a > 0).sum(), 1))
    return out
