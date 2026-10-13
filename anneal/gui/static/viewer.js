// 3D viewer: the part, picked regions, load arrows, and result colours.
// Z is up (CAD convention). Units are mm.
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { STLLoader } from "three/addons/loaders/STLLoader.js";

const VIRIDIS = [[0, 68, 1, 84], [.125, 71, 44, 122], [.25, 59, 81, 139], [.375, 44, 113, 142], [.5, 33, 144, 141],
  [.625, 39, 173, 129], [.75, 92, 200, 99], [.875, 170, 220, 50], [1, 253, 231, 37]];

export function viridis(t) {
  t = Math.min(1, Math.max(0, t));
  for (let i = 1; i < VIRIDIS.length; i++) {
    if (t <= VIRIDIS[i][0]) {
      const a = VIRIDIS[i - 1], b = VIRIDIS[i], u = (t - a[0]) / (b[0] - a[0]);
      return [(a[1] + u * (b[1] - a[1])) / 255, (a[2] + u * (b[2] - a[2])) / 255, (a[3] + u * (b[3] - a[3])) / 255];
    }
  }
  return [253 / 255, 231 / 255, 37 / 255];
}

function cssColor(name, fallback = "#888") {
  return new THREE.Color(getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback);
}

function smoothNormals(geom) {
  // the STL is a triangle soup: average normals of corners that share a position
  const p = geom.attributes.position.array, n = geom.attributes.normal.array;
  const acc = new Map(), keys = new Array(p.length / 3);
  const q = 1e3;
  for (let i = 0; i < p.length; i += 3) {
    const k = `${Math.round(p[i] * q)},${Math.round(p[i + 1] * q)},${Math.round(p[i + 2] * q)}`;
    keys[i / 3] = k;
    const a = acc.get(k) || [0, 0, 0];
    a[0] += n[i]; a[1] += n[i + 1]; a[2] += n[i + 2];
    acc.set(k, a);
  }
  const out = new Float32Array(n.length);
  for (let i = 0; i < keys.length; i++) {
    const a = acc.get(keys[i]); const l = Math.hypot(a[0], a[1], a[2]) || 1;
    out[3 * i] = a[0] / l; out[3 * i + 1] = a[1] / l; out[3 * i + 2] = a[2] / l;
  }
  geom.setAttribute("normal", new THREE.BufferAttribute(out, 3));
}

const LABEL_FONT = (fs) => `600 ${fs}px "IBM Plex Mono", Consolas, ui-monospace, monospace`;
function labelSprite(text, color, chip = true) {
  // a square readout chip: dark plate, coloured bar, light text (the same in both themes)
  const c = document.createElement("canvas"), dpr = 2, fs = 24;
  const ctx = c.getContext("2d");
  ctx.font = LABEL_FONT(fs);
  const w = Math.ceil(ctx.measureText(text).width) + (chip ? 30 : 8);
  c.width = w * dpr; c.height = (fs + 16) * dpr;
  ctx.scale(dpr, dpr);
  if (chip) {
    ctx.fillStyle = "rgba(20,22,24,0.88)"; ctx.fillRect(0, 0, w, fs + 16);
    ctx.fillStyle = color; ctx.fillRect(0, 0, 5, fs + 16);
  }
  ctx.font = LABEL_FONT(fs);
  ctx.fillStyle = chip ? "#f2efe6" : color; ctx.textBaseline = "middle"; ctx.fillText(text, chip ? 16 : 4, (fs + 16) / 2 + 1);
  const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace;
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, depthTest: false, transparent: true }));
  s.userData.aspect = w / (fs + 16);
  s.renderOrder = 10;
  return s;
}

export class Viewer {
  constructor(host) {
    this.host = host;
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    this.renderer.autoClear = false;
    host.appendChild(this.renderer.domElement);
    this.scene = new THREE.Scene();
    this.persp = new THREE.PerspectiveCamera(32, 1, 0.1, 1e6);
    this.persp.up.set(0, 0, 1);
    this.orthoCam = new THREE.OrthographicCamera(-1, 1, 1, -1, -1e5, 1e6);   // the same view without perspective
    this.orthoCam.up.set(0, 0, 1);
    this.orthoH = 100;                                                       // ortho frustum height at zoom 1, mm
    this.camera = this.persp;
    this.scene.add(this.persp, this.orthoCam);
    this.scene.add(new THREE.HemisphereLight(0xfbf8f0, 0x8a9198, 1.5));   // warm sky, cool ground
    this.head = new THREE.DirectionalLight(0xffffff, 1.65);                  // key light rides with the camera
    this.head.position.set(0.4, 0.8, 1);
    this.camera.add(this.head);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.12;
    this.controls.screenSpacePanning = true;
    this.renderer.domElement.addEventListener("contextmenu", e => e.preventDefault());   // right drag moves the view
    this.controls.listenToKeyEvents(window);                                            // arrow keys move the view
    this.overlay = new THREE.Group();
    this.scene.add(this.overlay);
    this.meshes = { model: null, result: null, ghost: null };
    this.size = 100;
    this.loader = new STLLoader();
    // axes inset
    this.axScene = new THREE.Scene();
    this.axCam = new THREE.OrthographicCamera(-1.6, 1.6, 1.6, -1.6, 0.1, 10);
    this.axCam.up.set(0, 0, 1);
    for (const [d, c, t] of [[[1, 0, 0], 0xe0533f, "X"], [[0, 1, 0], 0x4fb35c, "Y"], [[0, 0, 1], 0x4a8fe0, "Z"]]) {
      const v = new THREE.Vector3(...d);
      this.axScene.add(new THREE.ArrowHelper(v, new THREE.Vector3(), 1, c, 0.3, 0.14));
      const s = labelSprite(t, "#" + c.toString(16).padStart(6, "0"), false);
      s.position.copy(v.clone().multiplyScalar(1.35)); s.scale.set(0.5 * s.userData.aspect, 0.5, 1);
      this.axScene.add(s);
    }
    new ResizeObserver(() => this.resize()).observe(host);
    this.resize();
    const loop = () => { requestAnimationFrame(loop); this.controls.update(); this.render(); };
    loop();
  }

  resize() {
    const w = this.host.clientWidth || 1, h = this.host.clientHeight || 1;
    this.renderer.setSize(w, h, false);
    this.persp.aspect = w / h;
    this.persp.updateProjectionMatrix();
    this._orthoFrustum();
  }

  _orthoFrustum() {
    const a = (this.host.clientWidth || 1) / (this.host.clientHeight || 1), h = this.orthoH / 2;
    Object.assign(this.orthoCam, { left: -h * a, right: h * a, top: h, bottom: -h, near: this.size / 100, far: this.size * 60 });
    this.orthoCam.updateProjectionMatrix();
  }

  get isOrtho() { return this.camera === this.orthoCam; }

  setOrtho(on) {
    // switch between perspective and orthographic; the part keeps its size on the screen
    if (!!on === this.isOrtho) return;
    const t = this.controls.target, tan = Math.tan(THREE.MathUtils.degToRad(this.persp.fov / 2));
    const from = this.camera, to = on ? this.orthoCam : this.persp;
    const dir = new THREE.Vector3().subVectors(from.position, t).normalize();
    if (on) {
      const dist = from.position.distanceTo(t);
      this.orthoH = 2 * dist * tan;
      this.orthoCam.zoom = 1;
      this.orthoCam.position.copy(t).add(dir.multiplyScalar(Math.max(dist, this.size * 2)));
      this._orthoFrustum();
    } else {
      const dist = this.orthoH / this.orthoCam.zoom / (2 * tan);
      this.persp.position.copy(t).add(dir.multiplyScalar(dist));
      this.persp.near = this.size / 500; this.persp.far = this.size * 50;
      this.persp.updateProjectionMatrix();
    }
    to.up.copy(from.up);
    to.add(this.head);
    this.camera = to;
    this.controls.object = to;
    this.controls.update();
  }

  applyTheme() {
    // colours that come from the CSS theme: floor grid (the part colours are read when it is painted)
    if (this.box) { this._grid(); if (this.plateDir) this.setPlate(this.plateDir); }
  }

  render() {
    const r = this.renderer, w = this.host.clientWidth, h = this.host.clientHeight;
    r.setViewport(0, 0, w, h); r.setScissorTest(false); r.clear();
    r.render(this.scene, this.camera);
    const s = 84, o = 34;   // axis triad, bottom left, above the navigation help line
    const dir = new THREE.Vector3().subVectors(this.camera.position, this.controls.target).normalize();
    this.axCam.position.copy(dir.multiplyScalar(4)); this.axCam.up.copy(this.camera.up); this.axCam.lookAt(0, 0, 0);
    r.setViewport(10, o, s, s); r.setScissor(10, o, s, s); r.setScissorTest(true); r.clearDepth();
    r.render(this.axScene, this.axCam);
    r.setScissorTest(false);
    this._cube();
  }

  _cube() {
    // turn the HTML view cube (#vcBox) with the camera: world axes to CSS axes (y down)
    const box = this._vc || (this._vc = document.getElementById("vcBox"));
    if (!box) return;
    const e = this.camera.matrixWorldInverse.elements, f = v => (+v).toFixed(4);
    const m = `matrix3d(${f(e[0])},${f(-e[1])},${f(e[2])},0,${f(e[4])},${f(-e[5])},${f(e[6])},0,${f(e[8])},${f(-e[9])},${f(e[10])},0,0,0,0,1)`;
    if (m !== this._vcm) { box.style.transform = m; this._vcm = m; }
  }

  async loadSTL(url) {
    const buf = await (await fetch(url)).arrayBuffer();
    const g = this.loader.parse(buf);
    if (!g.attributes.normal) g.computeVertexNormals();
    return g;
  }

  _mesh(geom, smooth) {
    if (smooth) smoothNormals(geom);
    const n = geom.attributes.position.count;
    geom.setAttribute("color", new THREE.BufferAttribute(new Float32Array(n * 3).fill(0.75), 3));
    geom.userData.base = geom.attributes.position.array.slice();
    const mat = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.62, metalness: 0.08 });
    const m = new THREE.Mesh(geom, mat);
    m.userData.faces = n / 3;
    return m;
  }

  setModel(geom) {
    if (this.meshes.model) { this.scene.remove(this.meshes.model); this.meshes.model.geometry.dispose(); }
    this.meshes.model = this._mesh(geom, false);
    this.scene.add(this.meshes.model);
    geom.computeBoundingBox();
    this.box = geom.boundingBox.clone();
    this.size = this.box.getSize(new THREE.Vector3()).length();
    this._grid();
  }

  setResult(geom) {
    for (const k of ["result", "ghost"]) {
      if (this.meshes[k]) { this.scene.remove(this.meshes[k]); if (k === "result") this.meshes[k].geometry.dispose(); }
      this.meshes[k] = null;
    }
    if (!geom) return;
    this.meshes.result = this._mesh(geom, true);
    this.scene.add(this.meshes.result);
    const gm = new THREE.MeshBasicMaterial({ color: 0x8a96a0, transparent: true, opacity: 0.16, depthWrite: false });
    this.meshes.ghost = new THREE.Mesh(this.meshes.model.geometry, gm);
    this.meshes.ghost.visible = false;
    this.scene.add(this.meshes.ghost);
  }

  show(which, ghost) {
    if (this.meshes.model) this.meshes.model.visible = which === "model";
    if (this.meshes.result) this.meshes.result.visible = which === "result";
    if (this.meshes.ghost) this.meshes.ghost.visible = which === "result" && !!ghost;
    this.current = which;
  }

  _grid() {
    if (this.grid) this.scene.remove(this.grid);
    const step = Math.pow(10, Math.floor(Math.log10(this.size / 4)));
    const n = Math.ceil(this.size * 1.6 / step);
    this.grid = new THREE.GridHelper(n * step, n, cssColor("--grid-major", "#8e98a0"), cssColor("--grid-minor", "#b4bcc2"));
    this.grid.material.transparent = true; this.grid.material.opacity = 0.55;
    this.grid.rotation.x = Math.PI / 2;
    const c = this.box.getCenter(new THREE.Vector3());
    this.grid.position.set(c.x, c.y, this.box.min.z - 0.002 * this.size);
    this.scene.add(this.grid);
    this.gridStep = step;
  }

  view(kind) {
    if (!this.box) return;
    const c = this.box.getCenter(new THREE.Vector3());
    const d = this.size * 1.9;
    const dirs = { iso: [1, -1.25, 0.85], front: [0, -1, 0.0001], top: [0, -0.001, 1], right: [1, 0, 0.0001],
      back: [0, 1, 0.0001], left: [-1, 0, 0.0001], bottom: [0, -0.001, -1], fit: null };
    let v = dirs[kind];
    if (kind === "under") {   // look up at the part from below its build plate
      const B = new THREE.Vector3(...(this.plateDir || [0, 0, 1])).normalize();
      const x = Math.abs(B.x) < 0.9 ? new THREE.Vector3(1, 0, 0) : new THREE.Vector3(0, 1, 0);
      x.sub(B.clone().multiplyScalar(x.dot(B))).normalize();
      const y = new THREE.Vector3().crossVectors(B, x);
      v = x.multiplyScalar(0.9).add(y.multiplyScalar(-1.1)).add(B.clone().multiplyScalar(-0.9)).toArray();
    }
    if (!v) v = new THREE.Vector3().subVectors(this.camera.position, this.controls.target).normalize().toArray();
    const dir = new THREE.Vector3(...v).normalize();
    this.controls.target.copy(c);
    this.camera.position.copy(c).add(dir.multiplyScalar(d));
    if (this.isOrtho) {   // the same framing as the perspective camera at this distance
      this.orthoH = 2 * d * Math.tan(THREE.MathUtils.degToRad(this.persp.fov / 2));
      this.orthoCam.zoom = 1; this._orthoFrustum();
    } else {
      this.camera.near = this.size / 500; this.camera.far = this.size * 50;
      this.camera.updateProjectionMatrix();
    }
    this.controls.update();
  }

  pickAt(ev) {
    const m = this.meshes.model;
    if (!m || !m.visible) return null;
    const r = this.renderer.domElement.getBoundingClientRect();
    const ndc = new THREE.Vector2(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
    const ray = new THREE.Raycaster(); ray.setFromCamera(ndc, this.camera);
    const hit = ray.intersectObject(m, false)[0];
    if (!hit) return null;
    return { face: hit.faceIndex, point: hit.point.toArray() };
  }

  // ---- colours -----------------------------------------------------------
  paintShape(which, faceColors) {
    // faceColors: array of [faceIndexArray, THREE.Color]; everything else steel
    const m = this.meshes[which]; if (!m) return;
    const col = m.geometry.attributes.color.array;
    const base = which === "result" ? cssColor("--part-result", "#9fb0bd") : cssColor("--part-model", "#b9c1c7");
    for (let i = 0; i < col.length; i += 3) { col[i] = base.r; col[i + 1] = base.g; col[i + 2] = base.b; }
    for (const [faces, c] of faceColors || []) {
      for (const f of faces) {
        for (let k = 0; k < 3; k++) { const j = 9 * f + 3 * k; col[j] = c.r; col[j + 1] = c.g; col[j + 2] = c.b; }
      }
    }
    m.geometry.attributes.color.needsUpdate = true;
    this.resetShape(which);
  }

  paintField(which, data, kind) {
    // data: Float32Array [dx,dy,dz,vm] per corner. Returns {min,max,clipped} for the legend.
    const m = this.meshes[which]; if (!m || !data) return null;
    const n = m.geometry.attributes.position.count;
    if (data.length !== n * 4) return null;
    const v = new Float32Array(n);
    for (let i = 0; i < n; i++) {
      v[i] = kind === "disp" ? Math.hypot(data[4 * i], data[4 * i + 1], data[4 * i + 2]) : data[4 * i + 3];
    }
    const sorted = Float32Array.from(v).sort();
    const max = kind === "stress" ? sorted[Math.floor(0.99 * (n - 1))] : sorted[n - 1];
    const col = m.geometry.attributes.color.array;
    for (let i = 0; i < n; i++) { const c = viridis(max > 0 ? v[i] / max : 0); col[3 * i] = c[0]; col[3 * i + 1] = c[1]; col[3 * i + 2] = c[2]; }
    m.geometry.attributes.color.needsUpdate = true;
    return { min: 0, max, clipped: kind === "stress" && sorted[n - 1] > max * 1.001, peak: sorted[n - 1] };
  }

  deform(which, data, scale) {
    const m = this.meshes[which]; if (!m) return;
    const p = m.geometry.attributes.position.array, b = m.geometry.userData.base;
    if (!data || !scale) { p.set(b); }
    else for (let i = 0, n = p.length / 3; i < n; i++) {
      p[3 * i] = b[3 * i] + scale * data[4 * i]; p[3 * i + 1] = b[3 * i + 1] + scale * data[4 * i + 1];
      p[3 * i + 2] = b[3 * i + 2] + scale * data[4 * i + 2];
    }
    m.geometry.attributes.position.needsUpdate = true;
    m.geometry.computeBoundingSphere();
  }

  resetShape(which) { this.deform(which, null, 0); }

  paintOverhang(which, b, maxDeg) {
    // faces steeper than maxDeg from vertical (facing down) need support; faces flat on the plate do not
    const m = this.meshes[which]; if (!m) return null;
    const p = m.geometry.attributes.position.array, col = m.geometry.attributes.color.array;
    const B = new THREE.Vector3(...b).normalize();
    let hmin = Infinity;
    for (let i = 0; i < p.length; i += 3) hmin = Math.min(hmin, p[i] * B.x + p[i + 1] * B.y + p[i + 2] * B.z);
    const tol = this.size * 0.004;
    const need = cssColor("--warn"), plate = new THREE.Color(0x3b4b57), ok = cssColor("--part-model", "#b9c1c7");
    const a = new THREE.Vector3(), c = new THREE.Vector3(), d = new THREE.Vector3(), n = new THREE.Vector3();
    let needArea = 0, total = 0, plateArea = 0;
    const lim = Math.sin(THREE.MathUtils.degToRad(Math.min(90, maxDeg)));
    for (let f = 0; f < p.length / 9; f++) {
      const o = 9 * f;
      a.set(p[o], p[o + 1], p[o + 2]); c.set(p[o + 3], p[o + 4], p[o + 5]); d.set(p[o + 6], p[o + 7], p[o + 8]);
      n.subVectors(c, a).cross(d.clone().sub(a));
      const area = n.length() / 2; total += area;
      if (area === 0) continue;
      n.normalize();
      const nb = n.dot(B), h = (a.dot(B) + c.dot(B) + d.dot(B)) / 3;
      let k = ok;
      if (nb < -0.98 && h - hmin < tol) { k = plate; plateArea += area; }
      else if (maxDeg < 90 && nb < 0 && -nb > lim + 1e-9) { k = need; needArea += area; }
      for (let j = 0; j < 3; j++) { const q = o + 3 * j; col[q] = k.r; col[q + 1] = k.g; col[q + 2] = k.b; }
    }
    m.geometry.attributes.color.needsUpdate = true;
    return { needArea, total, plateArea };
  }

  setPlate(b) {
    // turn the floor grid so it lies under the part, across the build direction
    if (!this.grid || !this.box) return;
    const B = new THREE.Vector3(...(b || [0, 0, 1])).normalize();
    this.plateDir = B.toArray();
    this.grid.rotation.set(0, 0, 0);
    this.grid.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), B);
    const pts = [];
    for (const x of [this.box.min.x, this.box.max.x]) for (const y of [this.box.min.y, this.box.max.y])
      for (const z of [this.box.min.z, this.box.max.z]) pts.push(new THREE.Vector3(x, y, z).dot(B));
    const c = this.box.getCenter(new THREE.Vector3());
    this.grid.position.copy(c).add(B.clone().multiplyScalar(Math.min(...pts) - c.dot(B) - 0.002 * this.size));
  }

  // ---- overlays ------------------------------------------------------------
  clearOverlay() {
    for (const o of [...this.overlay.children]) {
      this.overlay.remove(o);
      o.traverse(x => { if (x.geometry) x.geometry.dispose(); if (x.material) { if (x.material.map) x.material.map.dispose(); x.material.dispose(); } });
    }
  }

  setPanMode(on) {
    this.controls.mouseButtons.LEFT = on ? THREE.MOUSE.PAN : THREE.MOUSE.ROTATE;
    this.controls.touches.ONE = on ? THREE.TOUCH.PAN : THREE.TOUCH.ROTATE;
  }

  orbitAround(point) {   // turn around a clicked point instead of the part centre
    const p = new THREE.Vector3(...point), d = p.clone().sub(this.controls.target);
    this.camera.position.add(d);
    this.controls.target.copy(p);
    this.controls.update();
  }

  region(reg, colorVar) {
    const color = cssColor(colorVar);
    const mat = new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.16, depthWrite: false, side: THREE.DoubleSide });
    let g = null, obj = new THREE.Group();
    const V = a => new THREE.Vector3(...a);
    if (reg.type === "sphere") { g = new THREE.SphereGeometry(reg.r, 28, 18); obj.position.copy(V(reg.center)); }
    else if (reg.type === "pipe" || reg.type === "cylinder") {
      const a = V(reg.from), b = V(reg.to), len = a.distanceTo(b) || 0.01;
      g = new THREE.CylinderGeometry(reg.r, reg.r, len, 36, 1, reg.type === "pipe");
      obj.position.copy(a.clone().add(b).multiplyScalar(0.5));
      obj.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), b.clone().sub(a).normalize());
    } else if (reg.type === "obox") {
      g = new THREE.BoxGeometry(...reg.size);
      const z = V(reg.normal).normalize();
      let x = reg.xdir ? V(reg.xdir) : (Math.abs(z.x) < 0.9 ? new THREE.Vector3(1, 0, 0) : new THREE.Vector3(0, 1, 0));
      x.sub(z.clone().multiplyScalar(x.dot(z))).normalize();
      const y = new THREE.Vector3().crossVectors(z, x);
      obj.quaternion.setFromRotationMatrix(new THREE.Matrix4().makeBasis(x, y, z));
      obj.position.copy(V(reg.center));
    } else if (reg.type === "prism") {
      // the picked face outline, extruded from z0 to z1 along the face normal
      const z = V(reg.normal).normalize();
      const x = V(reg.xdir).sub(z.clone().multiplyScalar(V(reg.xdir).dot(z))).normalize();
      const y = new THREE.Vector3().crossVectors(z, x);
      const pos = [], key = (a, b) => a < b ? a + "|" + b : b + "|" + a, cnt = new Map();
      const P = (u, v, w) => [u, v, w];
      for (const t of reg.tris) {
        const q = [[t[0], t[1]], [t[2], t[3]], [t[4], t[5]]];
        pos.push(...P(...q[0], reg.z1), ...P(...q[1], reg.z1), ...P(...q[2], reg.z1));
        pos.push(...P(...q[0], reg.z0), ...P(...q[2], reg.z0), ...P(...q[1], reg.z0));
        for (let i = 0; i < 3; i++) {
          const a = q[i].map(v => v.toFixed(4)).join(","), b = q[(i + 1) % 3].map(v => v.toFixed(4)).join(",");
          const k = key(a, b); cnt.set(k, (cnt.get(k) || []).concat([[q[i], q[(i + 1) % 3]]]));
        }
      }
      for (const [, list] of cnt) if (list.length === 1) {
        const [a, b] = list[0];
        pos.push(...P(...a, reg.z0), ...P(...b, reg.z0), ...P(...b, reg.z1), ...P(...a, reg.z0), ...P(...b, reg.z1), ...P(...a, reg.z1));
      }
      g = new THREE.BufferGeometry();
      g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
      g.computeVertexNormals();
      obj.quaternion.setFromRotationMatrix(new THREE.Matrix4().makeBasis(x, y, z));
      obj.position.copy(V(reg.origin));
    } else if (reg.type === "box") {
      const lo = V(reg.min), hi = V(reg.max);
      g = new THREE.BoxGeometry(...hi.clone().sub(lo).toArray());
      obj.position.copy(lo.clone().add(hi).multiplyScalar(0.5));
    }
    if (!g) return;
    obj.add(new THREE.Mesh(g, mat));
    const edges = new THREE.LineSegments(new THREE.EdgesGeometry(g, 30),
      new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.7 }));
    obj.add(edges);
    this.overlay.add(obj);
  }

  arrow(centre, force, label) {
    const f = new THREE.Vector3(...force);
    const mag = f.length(); if (!mag) return;
    const dir = f.clone().normalize(), len = this.size * 0.22;
    const tip = new THREE.Vector3(...centre);
    const tail = tip.clone().sub(dir.clone().multiplyScalar(len));
    const c = cssColor("--push");
    const a = new THREE.ArrowHelper(dir, tail, len, c, len * 0.22, len * 0.11);
    for (const part of [a.line, a.cone]) {   // draw through the part so the head is never hidden
      part.material.depthTest = false; part.material.transparent = true; part.renderOrder = 6;
    }
    this.overlay.add(a);
    const s = labelSprite(label, "#" + c.getHexString());
    const h = this.size * 0.035;
    s.scale.set(h * s.userData.aspect, h, 1);
    s.position.copy(tail.clone().sub(dir.clone().multiplyScalar(h * 0.8)));
    this.overlay.add(s);
  }

  // Torque glyph: a curved arrow (270 degrees) about the torque axis, turning by the right-hand rule,
  // and a short line on the axis. moment = [Mx, My, Mz] in N·m.
  torque(centre, moment, label) {
    const m = new THREE.Vector3(...moment);
    if (!m.length()) return;
    const ax = m.clone().normalize(), c = new THREE.Vector3(...centre);
    const ref = Math.abs(ax.z) < 0.9 ? new THREE.Vector3(0, 0, 1) : new THREE.Vector3(1, 0, 0);
    const u = new THREE.Vector3().crossVectors(ref, ax).normalize();
    const v = new THREE.Vector3().crossVectors(ax, u);              // u x v = ax: growing angle turns about +ax
    const r = this.size * 0.07, end = 1.5 * Math.PI, n = 48;
    const at = t => c.clone().add(u.clone().multiplyScalar(r * Math.cos(t))).add(v.clone().multiplyScalar(r * Math.sin(t)));
    const pts = [];
    for (let k = 0; k <= n; k++) pts.push(at(end * k / n));
    const col = cssColor("--push");
    const lineMat = () => new THREE.LineBasicMaterial({ color: col, depthTest: false, transparent: true });
    const g = new THREE.Group();
    g.userData.kind = "torque";
    const arc = new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), lineMat());
    const axis = new THREE.Line(new THREE.BufferGeometry().setFromPoints([c.clone().sub(ax.clone().multiplyScalar(r * 0.8)),
      c.clone().add(ax.clone().multiplyScalar(r * 1.3))]), lineMat());
    const tan = u.clone().multiplyScalar(-Math.sin(end)).add(v.clone().multiplyScalar(Math.cos(end))).normalize();
    const cone = new THREE.Mesh(new THREE.ConeGeometry(r * 0.16, r * 0.45, 16),
      new THREE.MeshBasicMaterial({ color: col, depthTest: false, transparent: true }));
    cone.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), tan);
    cone.position.copy(at(end)).add(tan.clone().multiplyScalar(r * 0.2));
    for (const part of [arc, axis, cone]) { part.renderOrder = 6; g.add(part); }
    this.overlay.add(g);
    const s = labelSprite(label, "#" + col.getHexString());
    const h = this.size * 0.035;
    s.scale.set(h * s.userData.aspect, h, 1);
    s.position.copy(c).add(ax.clone().multiplyScalar(r * 1.3 + h * 0.8));
    this.overlay.add(s);
  }
}
