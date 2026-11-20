import { Group, Mesh, MeshStandardMaterial, TorusGeometry } from "three";

export function createConciergeOrbit() {
  const root = new Group();
  const metal = new MeshStandardMaterial({
    color: "#b88b50", metalness: .81, roughness: .24,
    emissive: "#c4853b", emissiveIntensity: .10,
  });
  const paths = [
    { radius: 1.72, flatten: .80, pitch: -.47, roll: .58, height: .13 },
    { radius: 1.60, flatten: .54, pitch: .72, roll: -.66, height: -.17 },
  ].map((path, index) => {
    const orbit = new Group();
    const ring = new TorusGeometry(path.radius, index === 0 ? .026 : .023, 10, 96);
    const line = new Mesh(ring, metal);
    line.scale.y = path.flatten;
    orbit.add(line);
    orbit.position.y = path.height;
    root.add(orbit);
    return { orbit, ring, pitch: path.pitch, roll: path.roll };
  });

  return {
    root,
    update(time: number) {
      paths.forEach(({ orbit, pitch, roll }, layer) => {
        orbit.rotation.set(pitch + Math.sin(time * .52 + layer) * .13, .18 * Math.sin(time * .45), roll);
      });
    },
    dispose() {
      paths.forEach(({ ring }) => ring.dispose());
      metal.dispose();
    },
  };
}
