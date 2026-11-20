import {
  CanvasTexture, CatmullRomCurve3, Color, CylinderGeometry, ExtrudeGeometry,
  Group, Mesh, MeshPhysicalMaterial, RepeatWrapping, Shape, SphereGeometry,
  SRGBColorSpace, TorusGeometry, TubeGeometry, Vector3,
  type BufferGeometry, type Material,
} from "three";

type Point = [number, number, number];

export function createConcierge() {
  const root = new Group();
  const geometries = new Set<BufferGeometry>();
  const materials = new Set<Material>();
  const globe = new SphereGeometry(1, 44, 32);

  // A repeatable, low-contrast brushed finish. The texture follows the entire shell.
  const textureCanvas = document.createElement("canvas");
  textureCanvas.width = textureCanvas.height = 256;
  const context = textureCanvas.getContext("2d")!;
  const pixels = context.createImageData(256, 256);
  let seed = 74231;
  for (let y = 0; y < 256; y++) {
    for (let x = 0; x < 256; x++) {
      seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
      const grain = seed / 4294967296;
      const tarnish = Math.sin(x * .061 + Math.cos(y * .067) * 2) * 9;
      const shade = 195 + 31 * grain + Math.sin(y * 1.74) * 9 + tarnish;
      const offset = (y * 256 + x) * 4;
      pixels.data.set([shade, shade, shade, 255], offset);
    }
  }
  context.putImageData(pixels, 0, 0);
  const texture = new CanvasTexture(textureCanvas);
  texture.colorSpace = SRGBColorSpace;
  texture.wrapS = texture.wrapT = RepeatWrapping;
  texture.repeat.set(2, 1);

  function alloy(color: string, metalness: number, roughness: number, textured = false) {
    const material = new MeshPhysicalMaterial({
      color: new Color(color), metalness, roughness,
      clearcoat: .22, clearcoatRoughness: .31,
      map: textured ? texture : null,
    });
    materials.add(material);
    return material;
  }

  const bronze = alloy("#b17b3b", .75, .34, true);
  const gold = alloy("#e5ad5e", .79, .25);
  const edge = alloy("#a76330", .79, .34, true);
  const dark = alloy("#59371d", .63, .39, true);
  const rubber = alloy("#2a1c13", .15, .5);
  const black = alloy("#23120a", .1, .25);
  const copper = alloy("#bd7743", .78, .27);
  const amber = alloy("#ffa331", .28, .26);
  amber.emissive.set("#ff8209");
  amber.emissiveIntensity = .57;
  amber.clearcoat = 1;
  const pupil = alloy("#5e2a0d", .25, .33);
  const glint = alloy("#ffe2af", .03, .2);
  glint.emissive.set("#ffb864");
  glint.emissiveIntensity = .72;
  const mouthInside = alloy("#351807", .21, .52);
  const tongue = alloy("#ad5c34", .24, .49);

  function part(parent: Group, geometry: BufferGeometry, material: Material, [x, y, z]: Point = [0, 0, 0]) {
    geometries.add(geometry);
    const mesh = new Mesh(geometry, material);
    mesh.position.set(x, y, z);
    parent.add(mesh);
    return mesh;
  }
  function ball(parent: Group, material: Material, at: Point, scale: Point) {
    const mesh = part(parent, globe, material, at);
    mesh.scale.set(...scale);
    return mesh;
  }
  function tube(parent: Group, material: Material, points: Point[], thickness: number) {
    const curve = new CatmullRomCurve3(points.map((p) => new Vector3(...p)), false, "centripetal");
    return part(parent, new TubeGeometry(curve, 28, thickness, 8), material);
  }
  function ring(parent: Group, material: Material, at: Point, radius: number, thickness: number) {
    return part(parent, new TorusGeometry(radius, thickness, 12, 48), material, at);
  }
  function cylinder(parent: Group, material: Material, at: Point, top: number, bottom: number, height: number) {
    return part(parent, new CylinderGeometry(top, bottom, height, 40), material, at);
  }
  function group(parent: Group, at: Point = [0, 0, 0]) {
    const child = new Group();
    child.position.set(...at);
    parent.add(child);
    return child;
  }

  const shell = group(root, [0, .17, 0]);
  ball(shell, bronze, [0, 0, 0], [1.04, .98, .86]);
  const waist = ring(shell, edge, [0, -.54, 0], .846, .034);
  waist.rotation.x = Math.PI / 2;
  waist.scale.y = .85;
  const upperSeam = ring(shell, dark, [0, .56, 0], .849, .021);
  upperSeam.rotation.x = Math.PI / 2;
  upperSeam.scale.y = .83;
  const cap = cylinder(shell, dark, [0, .925, 0], .25, .33, .061);
  cap.scale.z = .83;
  ball(shell, gold, [0, .973, 0], [.23, .044, .18]);
  ball(shell, bronze, [0, 1.055, 0], [.107, .107, .107]);
  ball(shell, gold, [-.019, 1.096, .039], [.029, .018, .016]);

  // The inset face and rear service hatch are different solid surfaces.
  ball(shell, dark, [0, .035, .507], [.846, .797, .253]);
  ball(shell, gold, [0, .033, .526], [.812, .757, .265]);
  ball(shell, bronze, [0, .031, .555], [.784, .73, .258]);
  const hatch = group(shell, [0, -.02, -.714]);
  hatch.rotation.y = Math.PI;
  ball(hatch, dark, [0, 0, 0], [.533, .539, .17]);
  ring(hatch, gold, [0, 0, .101], .447, .019);
  ring(hatch, edge, [0, 0, .144], .365, .021);
  ball(hatch, rubber, [0, 0, .141], [.328, .328, .043]);
  for (let row = -4; row <= 4; row++) {
    const y = row * .057;
    const half = Math.sqrt(.296 ** 2 - y * y);
    tube(hatch, row % 2 === 0 ? gold : edge, [[-half, y, .184], [0, y + .009, .195], [half, y, .184]], .012);
  }
  for (let index = 0; index < 10; index++) {
    const angle = index * Math.PI / 5;
    const x = Math.sin(angle) * .486, y = Math.cos(angle) * .486;
    ball(hatch, gold, [x, y, .102], [.024, .024, .015]);
    tube(hatch, dark, [[x - .011, y - .006, .117], [x + .011, y + .006, .117]], .0028);
  }

  const eyes = [-1, 1].map((side) => {
    const eye = group(shell, [side * .33, .18, .77]);
    eye.rotation.y = side * .12;
    ball(eye, dark, [0, 0, 0], [.254, .238, .085]);
    const trim = ring(eye, gold, [0, 0, .069], .21, .022);
    trim.scale.y = .9;
    const inset = ring(eye, copper, [0, 0, .092], .184, .012);
    inset.scale.y = .9;
    ball(eye, black, [0, 0, .08], [.193, .171, .042]);
    const aperture = group(eye, [0, 0, .113]);
    ball(aperture, amber, [0, 0, 0], [.162, .149, .059]);
    ball(aperture, pupil, [0, -.006, .049], [.076, .093, .036]);
    ball(aperture, glint, [-.046, .069, .068], [.033, .024, .009]);
    ball(aperture, glint, [.04, -.056, .058], [.012, .012, .006]);
    const lid = ball(eye, bronze, [0, 0, .124], [.181, .157, .04]);
    const brow = group(eye, [0, .28, -.014]);
    tube(brow, gold, [[-.146, -.012, 0], [-.047, .052, .017], [.052, .051, .017], [.132, .011, -.003]], .021);
    return { aperture, lid, brow };
  });

  const mouth = group(shell, [0, -.225, .81]);
  const smile = new Shape();
  smile.moveTo(-.207, .035);
  smile.quadraticCurveTo(0, -.025, .207, .035);
  smile.quadraticCurveTo(.18, -.11, .037, -.137);
  smile.quadraticCurveTo(-.126, -.15, -.207, .035);
  part(mouth, new ExtrudeGeometry(smile, {
    depth: .015, bevelEnabled: true, bevelSegments: 3, steps: 1,
    bevelSize: .012, bevelThickness: .007, curveSegments: 28,
  }), mouthInside);
  tube(mouth, gold, [[-.209, .026, .009], [-.127, -.088, .027], [.004, -.138, .03], [.138, -.082, .025], [.207, .03, .009]], .008);
  const lowerLip = ball(mouth, tongue, [0, -.1, .027], [.065, .021, .007]);

  const feet = [-1, 1].map((side) => {
    const ear = group(shell, [side * .96, -.015, 0]);
    ear.rotation.y = side * Math.PI / 2;
    ball(ear, dark, [0, 0, .038], [.335, .335, .17]);
    ball(ear, gold, [0, 0, .135], [.283, .283, .151]);
    ring(ear, edge, [0, 0, .236], .213, .028);
    ball(ear, bronze, [0, 0, .244], [.187, .187, .095]);
    ring(ear, gold, [0, 0, .307], .11, .017);
    ball(ear, dark, [0, 0, .311], [.074, .074, .035]);
    for (let tooth = 0; tooth < 16; tooth++) {
      const angle = tooth * Math.PI / 8;
      ball(ear, gold, [Math.sin(angle) * .24, Math.cos(angle) * .24, .216], [.018, .018, .024]);
    }
    tube(shell, copper, [
      [side * .98, .31, -.133], [side * 1.277, .225, -.234],
      [side * 1.269, -.169, -.273], [side * 1.071, -.48, -.28],
      [side * .753, -.551, -.449], [side * .57, -.386, -.616],
    ], .041);
    tube(shell, dark, [
      [side * .999, -.24, .292], [side * 1.086, -.436, .365],
      [side * .948, -.636, .396], [side * .682, -.692, .43],
    ], .024);
    ball(shell, gold, [side * .668, -.684, .43], [.049, .049, .049]);
    tube(shell, gold, [
      [side * .064, .63, .691], [side * .225, .65, .683],
      [side * .418, .593, .664], [side * .497, .499, .664],
    ], .012);
    tube(shell, edge, [
      [side * .034, -.574, .609], [side * .219, -.546, .67],
      [side * .463, -.47, .677], [side * .59, -.389, .648],
    ], .014);
    ball(shell, gold, [side * .604, -.374, .648], [.025, .025, .025]);
    ball(shell, gold, [side * .708, .006, .65], [.027, .027, .029]);

    const hip = group(root, [side * .353, -.605, -.025]);
    hip.rotation.z = side * .045;
    ball(hip, dark, [0, -.091, 0], [.192, .153, .173]);
    cylinder(hip, copper, [0, -.206, 0], .106, .125, .192);
    ring(hip, gold, [0, -.184, 0], .111, .017).rotation.x = Math.PI / 2;
    const ankle = group(hip, [0, -.282, .012]);
    ball(ankle, edge, [0, -.008, 0], [.152, .124, .143]);
    ball(ankle, rubber, [0, -.245, .104], [.273, .066, .36]);
    ball(ankle, dark, [0, -.203, .107], [.266, .083, .352]);
    ball(ankle, bronze, [0, -.157, .127], [.245, .135, .327]);
    ball(ankle, gold, [0, -.168, .25], [.217, .107, .205]);
    tube(ankle, edge, [[-.184, -.17, .248], [-.13, -.083, .272], [0, -.068, .285], [.13, -.083, .272], [.184, -.17, .248]], .01);
    ball(ankle, gold, [side * .205, -.088, .013], [.043, .038, .043]);
    return { hip, ankle };
  });

  function pose(leftOpen: number, rightOpen: number, talking: number, smile: number, step: number, stride: number) {
    for (const [index, openness] of [leftOpen, rightOpen].entries()) {
      const eye = eyes[index];
      eye.aperture.scale.y = Math.max(.038, openness);
      eye.lid.scale.y = .157 * Math.max(.004, 1 - openness);
      eye.lid.position.y = .142 * openness;
      eye.brow.position.y = .28 + .043 * (1 - openness) + .025 * smile;
    }
    mouth.scale.set(1 + .14 * smile - .1 * talking, .78 + .86 * talking + .19 * smile, 1);
    lowerLip.visible = talking > .27;
    feet.forEach(({ hip, ankle }, index) => {
      const swing = Math.sin(step + index * Math.PI) * stride;
      hip.position.y = -.605 + Math.max(0, swing) * .102;
      hip.rotation.x = swing * .23;
      ankle.rotation.x = swing * -.19;
    });
  }

  return {
    root,
    pose,
    dispose() {
      geometries.forEach((geometry) => geometry.dispose());
      materials.forEach((material) => material.dispose());
      texture.dispose();
    },
  };
}
