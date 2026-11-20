const mascotVertex = `
  attribute vec2 uv;
  uniform vec2 angles;
  varying vec2 texCoord;
  varying float light;

  float relief(vec2 p, vec2 center, vec2 radius, float depth) {
    vec2 d = (p - center) / radius;
    return sqrt(max(0.0, 1.0 - dot(d, d))) * depth;
  }

  void main() {
    float dome = relief(uv, vec2(.50, .419), vec2(.385, .362), .38);
    float base = relief(uv, vec2(.50, .892), vec2(.29, .089), .09);
    vec3 p = vec3(uv.x * 2.0 - 1.0, 1.0 - uv.y * 2.0, max(dome, base));
    float sx = sin(angles.x), cx = cos(angles.x);
    float sy = sin(angles.y), cy = cos(angles.y);
    p.yz = mat2(cx, sx, -sx, cx) * p.yz;
    p.xz = mat2(cy, -sy, sy, cy) * p.xz;
    float perspective = .95 / (1.0 - .17 * p.z);
    gl_Position = vec4(p.xy * perspective, 0.0, 1.0);
    texCoord = uv;
    light = 1.0 + .28 * dome * (sy * p.x + sx * p.y);
  }
`;

const mascotFragment = `
  precision mediump float;
  uniform sampler2D artwork;
  varying vec2 texCoord;
  varying float light;
  void main() {
    vec4 color = texture2D(artwork, texCoord);
    gl_FragColor = vec4(color.rgb * color.a * light, color.a);
  }
`;

function createMascotDepth(host) {
  const actor = host.querySelector(".wavo-mascot-actor");
  const image = actor?.querySelector("img");
  if (!image?.complete || !image.naturalWidth) return;
  const canvas = document.createElement("canvas");
  canvas.className = "wavo-mascot-depth";
  canvas.setAttribute("aria-hidden", "true");
  const gl = canvas.getContext("webgl", { alpha: true, antialias: true, powerPreference: "low-power" });
  if (!gl) return;

  const program = gl.createProgram();
  for (const [type, source] of [[gl.VERTEX_SHADER, mascotVertex], [gl.FRAGMENT_SHADER, mascotFragment]]) {
    const shader = gl.createShader(type);
    gl.shaderSource(shader, source);
    gl.compileShader(shader);
    gl.attachShader(program, shader);
    gl.deleteShader(shader);
  }
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) return;
  gl.useProgram(program);

  const divisions = 40;
  const vertices = [];
  const indices = [];
  for (let row = 0; row <= divisions; row++) {
    for (let col = 0; col <= divisions; col++) {
      vertices.push(col / divisions, row / divisions);
      if (row === divisions || col === divisions) continue;
      const current = row * (divisions + 1) + col;
      const next = current + divisions + 1;
      indices.push(current, next, current + 1, current + 1, next, next + 1);
    }
  }

  gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(vertices), gl.STATIC_DRAW);
  const uv = gl.getAttribLocation(program, "uv");
  gl.enableVertexAttribArray(uv);
  gl.vertexAttribPointer(uv, 2, gl.FLOAT, false, 0, 0);
  gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, gl.createBuffer());
  gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, new Uint16Array(indices), gl.STATIC_DRAW);
  gl.bindTexture(gl.TEXTURE_2D, gl.createTexture());
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, image);
  const angles = gl.getUniformLocation(program, "angles");
  let x = 0, y = 0, targetX = 0, targetY = 0, frame = 0;

  function draw() {
    frame = 0;
    if (!canvas.isConnected) return;
    const size = Math.round(canvas.clientWidth * Math.min(devicePixelRatio, 2));
    if (!size) return;
    if (canvas.width !== size || canvas.height !== size) {
      canvas.width = canvas.height = size;
      gl.viewport(0, 0, size, size);
    }
    x += (targetX - x) * .2;
    y += (targetY - y) * .2;
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.uniform2f(angles, x, y);
    gl.drawElements(gl.TRIANGLES, indices.length, gl.UNSIGNED_SHORT, 0);
    if (Math.abs(targetX - x) + Math.abs(targetY - y) > .002) {
      frame = requestAnimationFrame(draw);
    }
  }
  function tilt(pitch, yaw) {
    targetX = pitch;
    targetY = yaw;
    if (!frame) frame = requestAnimationFrame(draw);
  }

  actor.append(canvas);
  actor.classList.add("has-depth");
  canvas.addEventListener("webglcontextlost", () => actor.classList.remove("has-depth"));
  tilt(0, 0);
  return { tilt };
}
