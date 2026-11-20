import { ExtrudeGeometry, Group, Mesh, MeshStandardMaterial, Shape, TorusGeometry } from "three";

export function createConciergeOrbit() {
  const root = new Group();
  const metal = new MeshStandardMaterial({
    color: "#b88b50", metalness: .81, roughness: .24,
    emissive: "#c4853b", emissiveIntensity: .10,
  });
  const pearl = new MeshStandardMaterial({
    color: "#f5d6a0", metalness: .58, roughness: .26,
    emissive: "#f1a64d", emissiveIntensity: .19,
  });

  const shape = new Shape();
  for (let index = 0; index < 8; index++) {
    const angle = Math.PI / 2 + index * Math.PI / 4;
    const radius = index % 2 === 0 ? 1 : .32;
    const x = Math.cos(angle) * radius;
    const y = Math.sin(angle) * radius * 1.13;
    if (index === 0) shape.moveTo(x, y);
    else shape.lineTo(x, y);
  }
  shape.closePath();
  const star = new ExtrudeGeometry(shape, {
    depth: .18, bevelEnabled: true, bevelSize: .08, bevelThickness: .08,
    bevelSegments: 1, steps: 1,
  });
  star.translate(0, 0, -.09);

  const paths = [
    { radius: 1.72, flatten: .80, pitch: -.47, roll: .58, height: .13, phase: .35, stars: 3 },
    { radius: 1.60, flatten: .54, pitch: .72, roll: -.66, height: -.17, phase: 1.4, stars: 2 },
  ].map((path, index) => {
    const orbit = new Group();
    const ring = new TorusGeometry(path.radius, index === 0 ? .026 : .023, 10, 96);
    const line = new Mesh(ring, metal);
    line.scale.y = path.flatten;
    orbit.add(line);
    orbit.position.y = path.height;
    root.add(orbit);
    const stars = Array.from({ length: path.stars }, (_, number) => {
      const charm = new Mesh(star, number % 2 === 0 ? pearl : metal);
      orbit.add(charm);
      return charm;
    });
    return { ...path, orbit, ring, stars };
  });

  return {
    root,
    update(time: number, energy: number) {
      paths.forEach(({ orbit, pitch, roll, radius, flatten, phase, stars }, layer) => {
        orbit.rotation.set(pitch + Math.sin(time * .52 + layer) * .13, .18 * Math.sin(time * .45), roll);
        stars.forEach((charm, index) => {
          const angle = phase + time * (layer === 0 ? .66 : -.73) + 2 * Math.PI * index / stars.length;
          charm.position.set(radius * Math.cos(angle), radius * flatten * Math.sin(angle), .01);
          charm.rotation.set(.22, time * .56 + index, angle + .35);
          charm.scale.setScalar((index === 0 ? .105 : .074) * (1 + .23 * Math.sin(angle * 2) + .19 * energy));
        });
      });
    },
    dispose() {
      paths.forEach(({ ring }) => ring.dispose());
      star.dispose();
      metal.dispose();
      pearl.dispose();
    },
  };
}
