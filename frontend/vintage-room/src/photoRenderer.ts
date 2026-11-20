// Runtime pixel deformation of the unmodified original photograph.
export function createPhotoRenderer(
  canvas: HTMLCanvasElement,
  cleaned: HTMLImageElement,
  daylight: HTMLImageElement,
  brownPlate: HTMLImageElement,
  lightPlate: HTMLImageElement,
) {
  const gl = canvas.getContext("webgl", {
    alpha: false,
    antialias: false,
    depth: false,
    powerPreference: "low-power",
  });
  if (!gl) return null;
  const vertex = `attribute vec2 position;varying vec2 uv;void main(){uv=vec2((position.x+1.)*.5,(1.-position.y)*.5);gl_Position=vec4(position,0.,1.);}`;
  const fragment = `precision highp float;varying vec2 uv;uniform sampler2D clean;uniform sampler2D dayPhoto;uniform sampler2D brownPlate;uniform sampler2D lightPlate;uniform float time;uniform float darkness;uniform float motion;
 const vec2 size=vec2(1670.,941.);
 float oval(vec2 p,vec2 c,vec2 r){return 1.-smoothstep(.6,1.,length((p-c)/r));}
 float luma(vec3 c){return dot(c,vec3(.299,.587,.114));}
 // Matte only foliage pixels from the brown photograph. It is shared by both themes.
 // Wall/pot/wood pixels never move; uncovered foliage reveals a stationary clean plate.
 float matte(vec2 p){
  if(p.x>735.&&p.x<963.&&p.y>592.){
   vec3 c=texture2D(clean,p/size).rgb;
   float green=smoothstep(.025,.065,c.g-1.75*c.b)*smoothstep(.48,.62,c.g/(c.r+.001));
   float canopy=oval(p,vec2(832.,674.),vec2(112.,89.));
   float vine=oval(p,vec2(901.,824.),vec2(65.,134.));
   return green*max(canopy,vine);
  }
  if(p.x<278.&&p.y>55.&&p.y<625.){
   vec3 c=texture2D(clean,p/size).rgb;
   float petal=smoothstep(.11,.22,c.b)*smoothstep(.23,.4,c.g);
   float beside=min(luma(texture2D(clean,(p+vec2(3.,0.))/size).rgb),luma(texture2D(clean,(p-vec2(3.,0.))/size).rgb));
   float stem=smoothstep(.035,.095,luma(c)-beside)*smoothstep(.38,.53,c.g/(c.r+.001));
   // Fixed wooden panel uprights cannot become part of the foreground matte.
   float upright=(1.-smoothstep(1.5,3.5,abs(p.x-47.)))*(1.-petal);
   float upright2=(1.-smoothstep(1.5,3.5,abs(p.x-77.)))*(1.-petal);
   float molding=(1.-smoothstep(7.,14.,abs(p.x-251.)))*(1.-petal);
   return max(petal,stem)*(1.-upright)*(1.-upright2)*(1.-molding)*(1.-smoothstep(615.,625.,p.y));
  }
  return 0.;
 }
 vec2 breeze(vec2 p){
  float wave=sin(time*.64)+.14*sin(time*1.07);
  if(p.x>720.&&p.x<980.&&p.y>580.){
   float crown=oval(p,vec2(832.,674.),vec2(125.,105.));
   float trail=oval(p,vec2(900.,823.),vec2(80.,150.));
   float height=clamp((720.-p.y)/115.,0.,1.);
   float hanging=clamp((p.y-727.)/190.,0.,1.);
   return vec2((crown*5.0*height+trail*7.0*hanging)*wave,(crown*.55*height+trail*.9*hanging)*sin(time*.8));
  }
  float tip=clamp((638.-p.y)/565.,0.,1.);
  float flowerArea=(1.-smoothstep(268.,294.,p.x))*(1.-smoothstep(620.,645.,p.y));
  return vec2(7.0*tip*wave,.65*tip*sin(time*.78))*flowerArea;
 }
 void main(){
  vec2 p=uv*size,src=p;
  if(motion>.5){for(int i=0;i<4;i++){src=p-breeze(src);}}
  vec3 brown=texture2D(clean,uv).rgb,day=texture2D(dayPhoto,uv).rgb;
  if(motion>.5){
   float oldAlpha=matte(p),newAlpha=matte(src);
   if(oldAlpha>.001){brown=mix(brown,texture2D(brownPlate,uv).rgb,oldAlpha);day=mix(day,texture2D(lightPlate,uv).rgb,oldAlpha);}
   if(newAlpha>.001){brown=mix(brown,texture2D(clean,src/size).rgb,newAlpha);day=mix(day,texture2D(dayPhoto,src/size).rgb,newAlpha);}
   // Keep the wick and glass rim still while the visible flame bends and breathes.
   if(p.x>361.&&p.x<444.&&p.y>681.&&p.y<754.){
    float flicker=.54*sin(time*9.)+.29*sin(time*15.7)+.17*sin(time*26.3);
    float flame=oval(p,vec2(402.5,713.),vec2(10.,16.))*smoothstep(700.,705.,p.y);
    float tip=clamp((728.-p.y)/26.,0.,1.);
    if(flame>.001){
     vec2 sway=vec2((2.7*sin(time*6.2)+1.35*flicker)*tip,1.7*flicker*tip);
     vec2 flameUV=(p-sway*flame)/size;
     brown=texture2D(clean,flameUV).rgb;
     day=texture2D(dayPhoto,flameUV).rgb;
    }
    float halo=oval(p,vec2(402.5,710.),vec2(36.,31.));
    vec3 warmth=vec3(.12,.057,.017)*halo*flicker;
    brown+=warmth;
    day+=warmth*.64;
   }
  }
  float t=clamp((p.y-205.)/247.,0.,1.);float width=mix(102.,197.,t);float shade=(1.-smoothstep(width-4.,width+2.,abs(p.x-596.)))*smoothstep(198.,208.,p.y)*(1.-smoothstep(447.,461.,p.y));shade*=smoothstep(.42,.75,max(brown.r,max(brown.g,brown.b)));float glow=oval(p,vec2(568.,548.),vec2(200.,130.));brown*=.93-.28*shade-.10*glow;gl_FragColor=vec4(mix(brown,day,darkness),1.);
 }`;
  function compile(type: number, source: string) {
    const shader = gl!.createShader(type)!;
    gl!.shaderSource(shader, source);
    gl!.compileShader(shader);
    if (!gl!.getShaderParameter(shader, gl!.COMPILE_STATUS))
      throw new Error(
        gl!.getShaderInfoLog(shader) ?? "Shader compilation failed",
      );
    return shader;
  }
  const vs = compile(gl.VERTEX_SHADER, vertex),
    fs = compile(gl.FRAGMENT_SHADER, fragment),
    program = gl.createProgram()!;
  gl.attachShader(program, vs);
  gl.attachShader(program, fs);
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS))
    throw new Error("Shader linking failed");
  gl.useProgram(program);
  const buffer = gl.createBuffer()!;
  gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
  gl.bufferData(
    gl.ARRAY_BUFFER,
    new Float32Array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1]),
    gl.STATIC_DRAW,
  );
  const pos = gl.getAttribLocation(program, "position");
  gl.enableVertexAttribArray(pos);
  gl.vertexAttribPointer(pos, 2, gl.FLOAT, false, 0, 0);
  const cleanTexture = gl.createTexture()!;
  gl.activeTexture(gl.TEXTURE1);
  gl.bindTexture(gl.TEXTURE_2D, cleanTexture);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, cleaned);
  gl.uniform1i(gl.getUniformLocation(program, "clean"), 1);
  gl.activeTexture(gl.TEXTURE0);
  const dayTexture = gl.createTexture()!;
  gl.activeTexture(gl.TEXTURE2);
  gl.bindTexture(gl.TEXTURE_2D, dayTexture);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, daylight);
  gl.uniform1i(gl.getUniformLocation(program, "dayPhoto"), 2);
  gl.activeTexture(gl.TEXTURE0);
  function plateTexture(image: HTMLImageElement, unit: number, name: string) {
    const tex = gl!.createTexture()!;
    gl!.activeTexture(gl!.TEXTURE0 + unit);
    gl!.bindTexture(gl!.TEXTURE_2D, tex);
    gl!.texParameteri(gl!.TEXTURE_2D, gl!.TEXTURE_WRAP_S, gl!.CLAMP_TO_EDGE);
    gl!.texParameteri(gl!.TEXTURE_2D, gl!.TEXTURE_WRAP_T, gl!.CLAMP_TO_EDGE);
    gl!.texParameteri(gl!.TEXTURE_2D, gl!.TEXTURE_MIN_FILTER, gl!.LINEAR);
    gl!.texParameteri(gl!.TEXTURE_2D, gl!.TEXTURE_MAG_FILTER, gl!.LINEAR);
    gl!.texImage2D(
      gl!.TEXTURE_2D,
      0,
      gl!.RGBA,
      gl!.RGBA,
      gl!.UNSIGNED_BYTE,
      image,
    );
    gl!.uniform1i(gl!.getUniformLocation(program, name), unit);
    return tex;
  }
  const brownBackground = plateTexture(brownPlate, 3, "brownPlate"),
    lightBackground = plateTexture(lightPlate, 4, "lightPlate");
  gl.activeTexture(gl.TEXTURE0);
  const loc = {
    time: gl.getUniformLocation(program, "time"),
    dark: gl.getUniformLocation(program, "darkness"),
    motion: gl.getUniformLocation(program, "motion"),
  };
  return {
    draw(time: number, dark: number, motion: boolean) {
      const rect = canvas.getBoundingClientRect(),
        dpr = Math.min(devicePixelRatio, 1.5),
        w = Math.max(1, Math.round(rect.width * dpr)),
        h = Math.max(1, Math.round(rect.height * dpr));
      if (canvas.width !== w || canvas.height !== h) {
        canvas.width = w;
        canvas.height = h;
        gl.viewport(0, 0, w, h);
      }
      gl.uniform1f(loc.time, time);
      gl.uniform1f(loc.dark, dark);
      gl.uniform1f(loc.motion, motion ? 1 : 0);
      gl.drawArrays(gl.TRIANGLES, 0, 6);
    },
    dispose() {
      gl.deleteTexture(brownBackground);
      gl.deleteTexture(lightBackground);
      gl.deleteTexture(cleanTexture);
      gl.deleteTexture(dayTexture);
      gl.deleteBuffer(buffer);
      gl.deleteProgram(program);
      gl.deleteShader(vs);
      gl.deleteShader(fs);
    },
  };
}
