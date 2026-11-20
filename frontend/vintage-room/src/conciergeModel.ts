import {
  CanvasTexture, CatmullRomCurve3, Color, CylinderGeometry, ExtrudeGeometry,
  Group, LatheGeometry, Mesh, MeshPhysicalMaterial, RepeatWrapping, Shape, SphereGeometry,
  SRGBColorSpace, TorusGeometry, TubeGeometry, Vector2, Vector3,
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

  const bronze = alloy("#a77750", .81, .37, true);
  const trim = alloy("#c18b5e", .79, .3, true);
  const etching = alloy("#69442e", .75, .45);
  const patina = alloy("#66432f", .73, .37, true);
  const brass = alloy("#b78c62", .8, .3);
  const cloth = alloy("#252224", .03, .91, true);
  cloth.clearcoat = 0;
  const lapel = alloy("#181719", .07, .69);
  lapel.clearcoat = 0;
  const shirt = alloy("#ebddc8", .02, .78);
  const leather = alloy("#2b211e", .3, .29, true);
  const sole = alloy("#30241d", .28, .49);
  const eyesBlack = alloy("#160f0d", .25, .16);
  eyesBlack.clearcoat = .85;
  const mouthInside = alloy("#20100b", .08, .58);
  const tongue = alloy("#813d29", .17, .54);

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

  const depth = .81;
  const crown: [number, number][] = [
    [0, -.421], [1.119, -.421], [1.15, -.401], [1.167, -.362],
    [1.171, -.294], [1.17, -.175], [1.159, -.01], [1.132, .169],
    [1.086, .34], [1.025, .488], [.965, .581], [.883, .668],
    [.774, .761], [.659, .828], [.522, .887], [.366, .926],
    [.235, .945], [0, .948],
  ];

  function lathe(parent: Group, material: Material, profile: [number, number][]) {
    const mesh = part(parent, new LatheGeometry(profile.map(([r, y]) => new Vector2(r, y)), 72), material);
    mesh.scale.z = depth;
    return mesh;
  }

  function band(parent: Group, material: Material, radius: number, y: number, size: number, scaleZ = depth) {
    const rim = ring(parent, material, [0, y, 0], radius, size);
    rim.rotation.x = Math.PI / 2;
    rim.scale.y = scaleZ;
    return rim;
  }

  function bodyRadius(y: number) {
    const index = crown.findIndex(([, height]) => height > y);
    const [inner, low] = crown[index - 1];
    const [outer, high] = crown[index];
    return inner + (outer - inner) * (y - low) / (high - low);
  }

  function scroll(center: number, height: number, direction: number, width: number, rise: number) {
    const points: Point[] = [];
    for (let index = 0; index <= 24; index++) {
      const progress = index / 24;
      const radius = 1 - progress * .92;
      const turn = progress * Math.PI * 2.45 - .7;
      const theta = center + direction * width * radius * Math.cos(turn);
      const y = height + rise * radius * Math.sin(turn);
      const body = bodyRadius(y) + .012;
      points.push([body * Math.sin(theta), y, body * depth * Math.cos(theta)]);
    }
    tube(root, etching, points, .016);
    const highlight = points.map(([x, y, z]): Point => [x * 1.009, y + .009, z * 1.009]);
    tube(root, trim, highlight, .007);
  }

  lathe(root, bronze, crown);
  band(root, patina, .974, .566, .027);
  band(root, trim, .995, .551, .026);
  band(root, brass, 1.016, .515, .016);
  band(root, patina, 1.139, -.39, .025);
  for (let index = 0; index < 6; index++) {
    const center = index * Math.PI / 3;
    scroll(center + .185, .727, 1, .257, .097);
    scroll(center - .185, .727, -1, .257, .097);
  }
  for (const side of [-1, 1]) {
    scroll(side * .77, -.251, side, .178, .115);
    scroll(side * .947, -.139, -side, .108, .21);
  }

  const plungerBase = cylinder(root, bronze, [0, .965, 0], .20, .232, .06);
  plungerBase.scale.z = .92;
  band(root, trim, .212, .992, .017, .93);
  cylinder(root, bronze, [0, 1.045, 0], .112, .142, .123);
  cylinder(root, patina, [0, 1.173, 0], .062, .063, .162);
  cylinder(root, trim, [0, 1.245, 0], .096, .074, .055);
  ball(root, patina, [0, 1.279, 0], [.224, .04, .204]);
  ball(root, bronze, [0, 1.309, 0], [.225, .054, .205]);
  band(root, trim, .210, 1.299, .011, .90);

  // A separate cloth body runs all the way around the bell.
  lathe(root, cloth, [
    [0, -.825], [1.20, -.825], [1.238, -.795], [1.241, -.759],
    [1.206, -.688], [1.175, -.607], [1.15, -.495], [1.131, -.385], [0, -.385],
  ]);
  lathe(root, bronze, [[0, -.848], [1.205, -.848], [1.245, -.823], [1.251, -.781], [1.242, -.755], [0, -.754]]);
  band(root, brass, 1.245, -.78, .012);

  function tailoring(material: Material, points: [number, number][], lift = .025) {
    const shape = new Shape(points.map(([x, y]) => new Vector2(x, y)));
    shape.closePath();
    const geometry = new ExtrudeGeometry(shape, {
      depth: .01, bevelEnabled: true, bevelSegments: 2, steps: 1,
      bevelSize: .009, bevelThickness: .007,
    });
    const position = geometry.attributes.position;
    for (let index = 0; index < position.count; index++) {
      const x = position.getX(index);
      const y = position.getY(index);
      const radius = 1.14 + .25 * (-y - .39);
      position.setZ(index, depth * Math.sqrt(radius * radius - x * x) + lift + position.getZ(index));
    }
    geometry.computeVertexNormals();
    part(root, geometry, material);
  }

  tailoring(shirt, [[-.463, -.397], [0, -.406], [.463, -.397], [.263, -.526], [0, -.635], [-.263, -.526]], .031);
  for (const side of [-1, 1]) {
    tailoring(cloth, [[side * .02, -.761], [side * .637, -.692], [side * .438, -.789], [side * .15, -.918]], .065);
    tailoring(lapel, [[side * .507, -.409], [side * .428, -.532], [side * .003, -.637], [side * .287, -.489]], .05);
    tailoring(lapel, [[side * .041, -.46], [side * .206, -.421], [side * .206, -.561], [side * .045, -.511]], .091);
  }
  ball(root, lapel, [0, -.486, 1.069], [.059, .057, .047]);
  ball(root, brass, [0, -.585, .993], [.017, .017, .011]);
  ball(root, trim, [0, -.679, 1.005], [.032, .032, .021]);
  ball(root, trim, [0, -.759, 1.023], [.031, .031, .021]);
  tube(root, lapel, [[.359, -.66, .96], [.505, -.645, .91], [.621, -.623, .851]], .017);

  // The back has a jacket seam and a discreet inset service plate.
  tube(root, lapel, [[0, -.414, -.925], [0, -.571, -.956], [0, -.734, -.994]], .01);
  const hatch = group(root, [0, -.068, -.919]);
  hatch.rotation.y = Math.PI;
  ball(hatch, patina, [0, 0, 0], [.207, .148, .037]);
  const rim = ring(hatch, trim, [0, 0, .025], .173, .009);
  rim.scale.y = .70;
  for (const y of [-.048, 0, .048]) {
    tube(hatch, etching, [[-.101, y, .032], [0, y, .045], [.101, y, .032]], .012);
  }

  const eyes = [-1, 1].map((side) => {
    const eye = group(root, [side * .386, .043, .884]);
    eye.rotation.y = side * .24;
    ball(eye, patina, [0, 0, -.006], [.102, .15, .025]);
    const aperture = ball(eye, eyesBlack, [0, 0, .013], [.093, .137, .042]);
    const lid = ball(eye, bronze, [0, 0, .039], [.097, .141, .022]);
    const brow = group(eye, [0, .265, -.033]);
    tube(brow, etching, [
      [-.104, side * .035 - .023, -.014], [-.049, .035, .012],
      [.041, .035, .018], [.101, -side * .035 - .019, 0],
    ], .018);
    return { aperture, lid, brow };
  });

  const mouth = group(root, [0, -.209, .949]);
  const smileShape = new Shape();
  smileShape.moveTo(-.171, .026);
  smileShape.quadraticCurveTo(0, -.026, .171, .026);
  smileShape.quadraticCurveTo(.116, -.112, .003, -.101);
  smileShape.quadraticCurveTo(-.124, -.103, -.171, .026);
  part(mouth, new ExtrudeGeometry(smileShape, {
    depth: .014, bevelEnabled: true, bevelSegments: 3, steps: 1,
    bevelSize: .008, bevelThickness: .004, curveSegments: 24,
  }), mouthInside);
  tube(mouth, brass, [[-.164, .02, .022], [-.093, -.065, .021], [0, -.105, .023], [.093, -.065, .021], [.164, .02, .022]], .007);
  const lowerLip = ball(mouth, tongue, [0, -.07, .024], [.059, .017, .005]);

  const limbs = [-1, 1].map((side) => {
    const axle = group(root, [side * 1.146, -.137, -.008]);
    axle.rotation.y = side * Math.PI / 2;
    ball(axle, patina, [0, 0, .02], [.231, .235, .093]);
    ring(axle, trim, [0, 0, .076], .194, .022);
    for (let index = 0; index < 18; index++) {
      const angle = index * Math.PI / 9;
      ball(axle, bronze, [Math.sin(angle) * .201, Math.cos(angle) * .201, .089], [.016, .016, .037]);
    }

    const arm = group(root, [side * 1.272, -.155, -.008]);
    ball(arm, bronze, [0, 0, 0], [.133, .132, .127]);
    cylinder(arm, bronze, [0, -.199, 0], .079, .069, .288);
    const elbow = group(arm, [0, -.355, .004]);
    ball(elbow, patina, [0, 0, 0], [.101, .105, .092]);
    cylinder(elbow, bronze, [0, -.164, .007], .087, .074, .237);
    ball(elbow, trim, [0, -.285, .012], [.078, .061, .073]);
    const hand = group(elbow, [0, -.353, .039]);
    ball(hand, bronze, [0, 0, 0], [.075, .084, .052]);
    for (const finger of [-1, 0, 1]) {
      const x = finger * .032;
      tube(hand, bronze, [[x, -.05, .016], [x, -.11, .043], [x - side * .016, -.145 + Math.abs(finger) * .011, .077]], .016);
    }
    tube(hand, trim, [[-side * .051, -.015, .004], [-side * .078, -.054, .042], [-side * .064, -.078, .067]], .021);

    const hip = group(root, [side * .379, -.798, -.02]);
    cylinder(hip, patina, [0, -.145, 0], .079, .061, .278);
    const ankle = group(hip, [0, -.248, .012]);
    cylinder(ankle, bronze, [0, -.007, 0], .153, .138, .049);
    ball(ankle, leather, [0, -.114, .015], [.153, .147, .153]);
    ball(ankle, sole, [0, -.244, .105], [.256, .053, .293]);
    ball(ankle, bronze, [0, -.218, .106], [.251, .054, .284]);
    ball(ankle, leather, [0, -.172, .147], [.239, .115, .253]);
    tube(ankle, patina, [[-.174, -.19, .23], [-.116, -.09, .224], [0, -.061, .223], [.119, -.09, .216], [.175, -.19, .229]], .007);
    return { side, arm, elbow, hip, ankle };
  });

  function pose(leftOpen: number, rightOpen: number, talking: number, smile: number, step: number, stride: number) {
    for (const [index, openness] of [leftOpen, rightOpen].entries()) {
      const eye = eyes[index];
      eye.aperture.scale.y = .137 * Math.max(.055, openness);
      eye.lid.scale.y = .141 * Math.max(.005, 1 - openness);
      eye.lid.position.y = .123 * openness;
      eye.brow.position.y = .265 + .035 * (1 - openness) + .021 * smile;
    }
    mouth.scale.set(1 + .11 * smile - .14 * talking, .81 + .91 * talking + .19 * smile, 1);
    lowerLip.visible = talking > .27;
    limbs.forEach(({ side, arm, elbow, hip, ankle }, index) => {
      const swing = Math.sin(step + index * Math.PI) * stride;
      arm.rotation.set(-swing * .16, 0, side * (.32 + .025 * smile));
      elbow.rotation.set(-.14 - Math.max(0, -swing) * .21, 0, -side * .065);
      hip.position.y = -.798 + Math.max(0, swing) * .104;
      hip.rotation.x = swing * .23;
      ankle.rotation.x = swing * -.19;
    });
  }
  pose(1, 1, 0, 0, 0, 0);

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
