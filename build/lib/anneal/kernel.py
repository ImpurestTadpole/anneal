"""Shape kernel: frames and base shapes as signed distance functions (mm, negative inside).

This plays the role ShapeKernel plays on top of PicoGK: small, exact building blocks
placed in local frames and combined with Booleans. Here they are evaluated on the voxel
grid as fill fractions. A PicoGK backend can replace this module on Windows or macOS
without changing the rest of the program.
"""
import numpy as np


def _unit(v, name="vector"):
    v = np.asarray(v, dtype=float)
    n = np.linalg.norm(v)
    if n < 1e-12:
        raise ValueError(f"The {name} has zero length. Give a non-zero direction such as [0,0,1].")
    return v / n


class Frame:
    """Local frame: origin, z axis (normal) and x axis. y = z cross x."""

    def __init__(self, origin, z=(0, 0, 1), x=None):
        self.o = np.asarray(origin, dtype=float)
        self.z = _unit(z, "normal")
        if x is None:
            x = (1, 0, 0) if abs(self.z[0]) < 0.9 else (0, 1, 0)
        x = np.asarray(x, dtype=float)
        x = x - self.z * (x @ self.z)
        self.x = _unit(x, "xdir (it must not be parallel to the normal)")
        self.y = np.cross(self.z, self.x)

    def to_local(self, p):
        d = np.asarray(p, dtype=float) - self.o
        return np.stack([d @ self.x, d @ self.y, d @ self.z], axis=-1)

    def to_world(self, q):
        q = np.asarray(q, dtype=float)
        return self.o + q[..., :1] * self.x + q[..., 1:2] * self.y + q[..., 2:3] * self.z


def _box_sdf(q, half):
    d = np.abs(q) - half
    outside = np.linalg.norm(np.maximum(d, 0), axis=-1)
    inside = np.minimum(np.max(d, axis=-1), 0)
    return outside + inside


class Shape:
    def sdf(self, p):
        raise NotImplementedError

    def bounds(self):
        raise NotImplementedError


class Box(Shape):
    """Axis-aligned box from min to max, or an oriented box: frame + size (centred in x, y; z from z0 to z0+size[2])."""

    def __init__(self, min=None, max=None, frame=None, size=None, z0=0.0):
        if frame is None:
            self.lo, self.hi = np.asarray(min, float), np.asarray(max, float)
            if np.any(self.hi <= self.lo):
                raise ValueError(f"Box min {list(self.lo)} must be below max {list(self.hi)} on every axis.")
            self.frame = None
        else:
            self.frame, self.size, self.z0 = frame, np.asarray(size, float), float(z0)

    def sdf(self, p):
        if self.frame is None:
            c, half = (self.lo + self.hi) / 2, (self.hi - self.lo) / 2
            return _box_sdf(np.asarray(p) - c, half)
        q = self.frame.to_local(p)
        q[..., 2] -= self.z0 + self.size[2] / 2
        return _box_sdf(q, self.size / 2)

    def bounds(self):
        if self.frame is None:
            return self.lo, self.hi
        s = self.size / 2
        corners = np.array([[sx, sy, self.z0 + sz] for sx in (-s[0], s[0]) for sy in (-s[1], s[1])
                            for sz in (0, self.size[2])])
        w = self.frame.to_world(corners)
        return w.min(0), w.max(0)


class Sphere(Shape):
    def __init__(self, center, r):
        self.c, self.r = np.asarray(center, float), float(r)

    def sdf(self, p):
        return np.linalg.norm(np.asarray(p) - self.c, axis=-1) - self.r

    def bounds(self):
        return self.c - self.r, self.c + self.r


class Cylinder(Shape):
    """Capped cylinder from 'a' to 'b' with radius r. With r_in > 0 it is a pipe (tube)."""

    def __init__(self, a, b, r, r_in=0.0):
        self.a, self.b = np.asarray(a, float), np.asarray(b, float)
        self.r, self.r_in = float(r), float(r_in)
        self.L = np.linalg.norm(self.b - self.a)
        if self.L < 1e-9:
            raise ValueError("A cylinder needs 'from' and 'to' at different points.")
        if self.r_in >= self.r:
            raise ValueError(f"Pipe inner radius {self.r_in} must be smaller than outer radius {self.r}.")
        self.ax = (self.b - self.a) / self.L

    def sdf(self, p):
        d = np.asarray(p) - self.a
        t = d @ self.ax
        rad = np.linalg.norm(d - t[..., None] * self.ax, axis=-1)
        dr = rad - self.r
        if self.r_in > 0:
            dr = np.maximum(dr, self.r_in - rad)
        dz = np.maximum(-t, t - self.L)
        return np.linalg.norm(np.maximum(np.stack([dr, dz], -1), 0), axis=-1) + np.minimum(np.maximum(dr, dz), 0)

    def bounds(self):
        lo = np.minimum(self.a, self.b) - self.r
        hi = np.maximum(self.a, self.b) + self.r
        return lo, hi


class Union(Shape):
    def __init__(self, shapes):
        self.shapes = list(shapes)

    def sdf(self, p):
        return np.min([s.sdf(p) for s in self.shapes], axis=0)

    def bounds(self):
        b = [s.bounds() for s in self.shapes]
        return np.min([x[0] for x in b], 0), np.max([x[1] for x in b], 0)


def make_region(d, where="region"):
    """Build a shape from a spec dict: box / sphere / cylinder / pipe."""
    if not isinstance(d, dict) or "type" not in d:
        raise ValueError(f"{where}: give a dict with 'type' (box, obox, sphere, cylinder or pipe).")
    t = d["type"]
    try:
        if t == "box":
            return Box(d["min"], d["max"])
        if t == "sphere":
            return Sphere(d["center"], d["r"])
        if t == "cylinder":
            return Cylinder(d["from"], d["to"], d["r"])
        if t == "pipe":
            return Cylinder(d["from"], d["to"], d["r"], d["rIn"])
        if t == "obox":
            size = np.asarray(d["size"], float)
            return Box(frame=Frame(d["center"], d["normal"], d.get("xdir")), size=size, z0=-size[2] / 2)
    except KeyError as k:
        need = {"box": "min, max", "sphere": "center, r", "cylinder": "from, to, r",
                "pipe": "from, to, r, rIn", "obox": "center, normal, size (xdir optional)"}[t]
        raise ValueError(f"{where}: a {t} needs {need}; {k} is missing.") from None
    raise ValueError(f"{where}: unknown type '{t}'. Use box, obox, sphere, cylinder or pipe.")


def fill_fraction(shape, centers, h):
    """Approximate volume fraction of each voxel inside the shape (linear ramp over one voxel)."""
    return np.clip(0.5 - shape.sdf(centers) / h, 0.0, 1.0)


# Clearance holes (medium fit, ISO 273) and washer-face boss diameters, mm
FASTENERS = {"M2": (2.4, 5.0), "M2.5": (2.9, 6.0), "M3": (3.4, 7.0), "M4": (4.5, 9.0),
             "M5": (5.5, 10.0), "M6": (6.6, 12.0), "M8": (9.0, 16.0), "M10": (11.0, 20.0),
             "M12": (13.5, 24.0)}
