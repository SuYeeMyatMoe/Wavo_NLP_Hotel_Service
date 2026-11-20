export type Point3 = { x: number; y: number; z: number };
export type ChainInput = {
  x: number;
  y: number;
  active: boolean;
  dragging: boolean;
};
const copy = (p: Point3): Point3 => ({ ...p });
export class ChainPhysics {
  readonly count = 29;
  readonly length = 185;
  readonly positions: Point3[];
  readonly previous: Point3[];
  private accumulator = 0;
  private ropeLength = 185;
  private target: Point3 = { x: 0, y: -185, z: 0 };
  private wasActive = false;
  constructor() {
    this.positions = Array.from({ length: this.count }, (_, i) => ({
      x: 0,
      y: (-this.length * i) / (this.count - 1),
      z: 0,
    }));
    this.previous = this.positions.map(copy);
  }
  advance(dt: number, input: ChainInput) {
    this.accumulator += Math.min(Math.max(dt, 0), 0.1);
    const h = 1 / 120;
    while (this.accumulator >= h) {
      this.step(h, input);
      this.accumulator -= h;
    }
    const alpha = this.accumulator / h;
    return this.positions.map((p, i) => ({
      x: this.previous[i].x + (p.x - this.previous[i].x) * alpha,
      y: this.previous[i].y + (p.y - this.previous[i].y) * alpha,
      z: this.previous[i].z + (p.z - this.previous[i].z) * alpha,
    }));
  }
  private step(h: number, input: ChainInput) {
    const desired: Point3 = {
      x: input.x,
      y: -185 - input.y,
      z: input.active ? Math.sin(input.x * 0.02) * 48 : 0,
    };
    const radius = Math.hypot(desired.x, desired.y, desired.z);
    if (radius > 235) {
      desired.x *= 235 / radius;
      desired.y *= 235 / radius;
      desired.z *= 235 / radius;
    }
    if (input.active && !this.wasActive)
      this.target = copy(this.positions[this.count - 1]);
    const follow = 1 - Math.exp(-(input.dragging ? 28 : 10) * h);
    this.target.x += (desired.x - this.target.x) * follow;
    this.target.y += (desired.y - this.target.y) * follow;
    this.target.z += (desired.z - this.target.z) * follow;
    const targetLength = input.active
      ? Math.max(
          this.length,
          Math.hypot(this.target.x, this.target.y, this.target.z),
        )
      : this.length;
    this.ropeLength +=
      (targetLength - this.ropeLength) * (1 - Math.exp(-9 * h));
    const damping = Math.exp(-0.8 * h);
    for (let i = 1; i < this.count; i++) {
      const p = this.positions[i],
        old = this.previous[i];
      let dx = (p.x - old.x) * damping,
        dy = (p.y - old.y) * damping,
        dz = (p.z - old.z) * damping;
      const speed = Math.hypot(dx, dy, dz);
      const cap = 500 * h;
      if (speed > cap) {
        dx *= cap / speed;
        dy *= cap / speed;
        dz *= cap / speed;
      }
      old.x = p.x;
      old.y = p.y;
      old.z = p.z;
      p.x += dx;
      p.y += dy - 1050 * h * h;
      p.z += dz;
    }
    const spacing = this.ropeLength / (this.count - 1);
    for (let iteration = 0; iteration < 22; iteration++) {
      Object.assign(this.positions[0], { x: 0, y: 0, z: 0 });
      if (input.active)
        Object.assign(this.positions[this.count - 1], this.target);
      for (let i = 0; i < this.count - 1; i++) {
        const a = this.positions[i],
          b = this.positions[i + 1];
        const dx = b.x - a.x,
          dy = b.y - a.y,
          dz = b.z - a.z,
          d = Math.hypot(dx, dy, dz);
        if (d < 1e-8) continue;
        const wa = i === 0 ? 0 : 1,
          wb = i === this.count - 2 ? (input.active ? 0 : 0.25) : 1,
          total = wa + wb;
        if (!total) continue;
        const correction = (d - spacing) / d;
        a.x += (dx * correction * wa) / total;
        a.y += (dy * correction * wa) / total;
        a.z += (dz * correction * wa) / total;
        b.x -= (dx * correction * wb) / total;
        b.y -= (dy * correction * wb) / total;
        b.z -= (dz * correction * wb) / total;
      }
    }
    Object.assign(this.positions[0], { x: 0, y: 0, z: 0 });
    this.wasActive = input.active;
  }
}
