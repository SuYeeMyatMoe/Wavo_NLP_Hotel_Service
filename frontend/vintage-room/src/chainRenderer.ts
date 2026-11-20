import { ChainPhysics } from "./chainPhysics";
import * as THREE from "three";
export function createChainRenderer(canvas: HTMLCanvasElement) {
  const renderer = new THREE.WebGLRenderer({
    canvas,
    alpha: true,
    antialias: true,
    powerPreference: "low-power",
  });
  renderer.setClearColor(0, 0);
  renderer.setPixelRatio(Math.min(devicePixelRatio, 1.5));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  const scene = new THREE.Scene(),
    camera = new THREE.PerspectiveCamera(
      (2 * Math.atan(941 / 2000) * 180) / Math.PI,
      1670 / 941,
      0.1,
      3000,
    );
  camera.position.set(835, 470.5, 1000);
  camera.lookAt(835, 470.5, 0);
  const ambient = new THREE.AmbientLight("#ffe0ad", 1.2);
  scene.add(ambient);
  const key = new THREE.DirectionalLight("#fff2d7", 3.8);
  key.position.set(250, 800, 600);
  scene.add(key);
  const rim = new THREE.DirectionalLight("#ad7030", 1.8);
  rim.position.set(1000, 400, 200);
  scene.add(rim);
  const envCanvas = document.createElement("canvas");
  envCanvas.width = 512;
  envCanvas.height = 256;
  const ctx = envCanvas.getContext("2d")!;
  ctx.fillStyle = "#392a19";
  ctx.fillRect(0, 0, 512, 256);
  const gradient = ctx.createLinearGradient(0, 0, 0, 256);
  gradient.addColorStop(0, "#e7cf9d");
  gradient.addColorStop(0.45, "#806345");
  gradient.addColorStop(1, "#24170d");
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, 512, 256);
  ctx.fillStyle = "#fff3d9";
  ctx.fillRect(55, 25, 50, 170);
  ctx.fillStyle = "#d0b586";
  ctx.fillRect(310, 55, 28, 100);
  const env = new THREE.CanvasTexture(envCanvas);
  env.mapping = THREE.EquirectangularReflectionMapping;
  env.colorSpace = THREE.SRGBColorSpace;
  scene.environment = env;
  const material = new THREE.MeshStandardMaterial({
    color: "#d7a349",
    metalness: 0.88,
    roughness: 0.24,
  });
  const count = 29,
    length = 185,
    spacing = length / (count - 1),
    anchor = new THREE.Vector3(551, 941 - 447, 0);
  const beads = new THREE.InstancedMesh(
    new THREE.SphereGeometry(1.75, 12, 10),
    material,
    count,
  );
  scene.add(beads);
  const links = new THREE.InstancedMesh(
    new THREE.CylinderGeometry(0.5, 0.5, 1, 6),
    material,
    count - 1,
  );
  scene.add(links);
  const ball = new THREE.Mesh(new THREE.SphereGeometry(14.8, 40, 28), material);
  scene.add(ball);
  const collar = new THREE.Mesh(
    new THREE.CylinderGeometry(3.8, 3.8, 5, 16),
    material,
  );
  scene.add(collar);
  const physics = new ChainPhysics();
  const temp = new THREE.Object3D(),
    up = new THREE.Vector3(0, 1, 0),
    direction = new THREE.Vector3();
  let width = 0,
    height = 0;
  return {
    draw(
      dt: number,
      targetX: number,
      targetY: number,
      active: boolean,
      dragging: boolean,
      light: boolean,
    ) {
      const rect = canvas.getBoundingClientRect();
      if (rect.width !== width || rect.height !== height) {
        width = rect.width;
        height = rect.height;
        renderer.setSize(width, height, false);
      }
      const points = physics.advance(dt, {
        x: targetX,
        y: targetY,
        active,
        dragging,
      });
      const positions = points.map((p) => new THREE.Vector3(p.x, p.y, p.z));
      for (let i = 0; i < count; i++) {
        temp.position.copy(positions[i]).add(anchor);
        temp.rotation.set(0, 0, 0);
        temp.scale.setScalar(1);
        temp.updateMatrix();
        beads.setMatrixAt(i, temp.matrix);
        if (i < count - 1) {
          const a = positions[i],
            b = positions[i + 1];
          direction.copy(b).sub(a);
          temp.position.copy(a).add(b).multiplyScalar(0.5).add(anchor);
          temp.quaternion.setFromUnitVectors(up, direction.clone().normalize());
          temp.scale.set(1, direction.length(), 1);
          temp.updateMatrix();
          links.setMatrixAt(i, temp.matrix);
        }
      }
      beads.instanceMatrix.needsUpdate = true;
      links.instanceMatrix.needsUpdate = true;
      ball.position.copy(positions[count - 1]).add(anchor);
      ball.rotation.y = targetX * 0.015;
      collar.position.copy(ball.position);
      collar.position.y += 14;
      ambient.intensity = light ? 1.55 : 1.05;
      key.intensity = light ? 4.3 : 2.6;
      renderer.render(scene, camera);
      const projected = ball.position.clone().project(camera);
      return {
        x: (projected.x + 1) * 835,
        y: (1 - projected.y) * 470.5,
        z: ball.position.z,
      };
    },
    dispose() {
      beads.geometry.dispose();
      links.geometry.dispose();
      ball.geometry.dispose();
      collar.geometry.dispose();
      material.dispose();
      env.dispose();
      renderer.dispose();
    },
  };
}
