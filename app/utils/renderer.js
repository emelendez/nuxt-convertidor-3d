// Render de previsualización 3D desde vídeo SBS: anaglifo Dubois (rojo-cian)
// o entrelazado. WebGPU si está disponible; fallback WebGL2.

const DUBOIS_L = [0.456, 0.500, 0.176, -0.040, -0.038, -0.016, -0.015, -0.021, -0.005];
const DUBOIS_R = [-0.043, -0.088, -0.002, 0.378, 0.734, -0.018, -0.072, -0.113, 1.226];

const WGSL = `
struct Uniforms { mode: f32, _pad: vec3f };
@group(0) @binding(0) var samp: sampler;
@group(0) @binding(1) var tex: texture_external;
@group(0) @binding(2) var<uniform> u: Uniforms;

struct VOut { @builtin(position) pos: vec4f, @location(0) uv: vec2f };
@vertex fn vs(@builtin(vertex_index) i: u32) -> VOut {
  var p = array<vec2f, 3>(vec2f(-1.0, -3.0), vec2f(-1.0, 1.0), vec2f(3.0, 1.0));
  var o: VOut;
  o.pos = vec4f(p[i], 0.0, 1.0);
  o.uv = vec2f((p[i].x + 1.0) * 0.5, (1.0 - p[i].y) * 0.5);
  return o;
}
@fragment fn fs(v: VOut) -> @location(0) vec4f {
  let l = textureSampleBaseClampToEdge(tex, samp, vec2f(v.uv.x * 0.5, v.uv.y)).rgb;
  let r = textureSampleBaseClampToEdge(tex, samp, vec2f(0.5 + v.uv.x * 0.5, v.uv.y)).rgb;
  if (u.mode > 0.5) { // entrelazado por filas
    let row = u32(v.pos.y);
    return vec4f(select(l, r, (row & 1u) == 1u), 1.0);
  }
  // DUBOIS_* van por filas; vec*mat hace el producto fila·color (equivale a M·color
  // con M no transpuesta). Con mat*vec saldría transpuesto (tinte azulado).
  let ml = mat3x3f(${DUBOIS_L.join(',')});
  let mr = mat3x3f(${DUBOIS_R.join(',')});
  return vec4f(clamp(l * ml + r * mr, vec3f(0.0), vec3f(1.0)), 1.0);
}`;

const GLSL_FRAG = `#version 300 es
precision highp float;
uniform sampler2D tex; uniform float mode; uniform float rowY;
in vec2 uv; out vec4 color;
void main() {
  vec3 l = texture(tex, vec2(uv.x * 0.5, uv.y)).rgb;
  vec3 r = texture(tex, vec2(0.5 + uv.x * 0.5, uv.y)).rgb;
  if (mode > 0.5) {
    color = vec4(mod(gl_FragCoord.y, 2.0) < 1.0 ? l : r, 1.0);
  } else {
    // DUBOIS_* van por filas; vec*mat hace fila·color (M no transpuesta).
    mat3 ml = mat3(${DUBOIS_L.join(',')});
    mat3 mr = mat3(${DUBOIS_R.join(',')});
    color = vec4(clamp(l * ml + r * mr, 0.0, 1.0), 1.0);
  }
}`;

export async function createSbsRenderer(canvas, video) {
  // WebGL2 primero: probado y fiable en todas las GPUs. La ruta WebGPU con
  // `texture_external` renderiza en NEGRO en algunas iGPU (verificado en Intel
  // UHD 770 con Dawn: device e importExternalTexture existen, pero el render da
  // negro), así que solo se usa como último recurso si no hay WebGL2.
  return createWebGL(canvas, video) || await tryWebGPU(canvas, video);
}

async function tryWebGPU(canvas, video) {
  if (!navigator.gpu) return null;
  try {
    const adapter = await navigator.gpu.requestAdapter();
    if (!adapter) return null;
    const device = await adapter.requestDevice();
    const ctx = canvas.getContext('webgpu');
    const format = navigator.gpu.getPreferredCanvasFormat();
    ctx.configure({ device, format, alphaMode: 'opaque' });
    const module = device.createShaderModule({ code: WGSL });
    const pipeline = device.createRenderPipeline({
      layout: 'auto',
      vertex: { module, entryPoint: 'vs' },
      fragment: { module, entryPoint: 'fs', targets: [{ format }] },
    });
    const sampler = device.createSampler({ magFilter: 'linear', minFilter: 'linear' });
    const ubuf = device.createBuffer({ size: 16, usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST });
    let mode = 0;
    return {
      backend: 'WebGPU',
      setMode(m) { mode = m === 'interlaced' ? 1 : 0; },
      draw() {
        if (video.readyState < 2) return;
        device.queue.writeBuffer(ubuf, 0, new Float32Array([mode, 0, 0, 0]));
        const ext = device.importExternalTexture({ source: video });
        const bind = device.createBindGroup({
          layout: pipeline.getBindGroupLayout(0),
          entries: [{ binding: 0, resource: sampler },
                    { binding: 1, resource: ext },
                    { binding: 2, resource: { buffer: ubuf } }],
        });
        const enc = device.createCommandEncoder();
        const pass = enc.beginRenderPass({
          colorAttachments: [{ view: ctx.getCurrentTexture().createView(),
            loadOp: 'clear', storeOp: 'store', clearValue: [0, 0, 0, 1] }],
        });
        pass.setPipeline(pipeline);
        pass.setBindGroup(0, bind);
        pass.draw(3);
        pass.end();
        device.queue.submit([enc.finish()]);
      },
    };
  } catch (_) {
    return null;
  }
}

function createWebGL(canvas, video) {
  const gl = canvas.getContext('webgl2');
  if (!gl) return null;
  const vsSrc = `#version 300 es
    out vec2 uv;
    void main() {
      // triángulo a pantalla completa sin buffers
      vec2 p = vec2(float((gl_VertexID << 1) & 2), float(gl_VertexID & 2));
      gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
      uv = vec2(p.x, 1.0 - p.y);
    }`;
  const compile = (type, src) => {
    const s = gl.createShader(type);
    gl.shaderSource(s, src); gl.compileShader(s);
    return s;
  };
  const prog = gl.createProgram();
  gl.attachShader(prog, compile(gl.VERTEX_SHADER, vsSrc));
  gl.attachShader(prog, compile(gl.FRAGMENT_SHADER, GLSL_FRAG));
  gl.linkProgram(prog);
  gl.useProgram(prog);
  const tex = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D, tex);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  const uMode = gl.getUniformLocation(prog, 'mode');
  let mode = 0;
  return {
    backend: 'WebGL2',
    setMode(m) { mode = m === 'interlaced' ? 1 : 0; },
    draw() {
      if (video.readyState < 2) return;
      gl.viewport(0, 0, canvas.width, canvas.height);
      gl.bindTexture(gl.TEXTURE_2D, tex);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGB, gl.RGB, gl.UNSIGNED_BYTE, video);
      gl.uniform1f(uMode, mode);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
    },
  };
}
