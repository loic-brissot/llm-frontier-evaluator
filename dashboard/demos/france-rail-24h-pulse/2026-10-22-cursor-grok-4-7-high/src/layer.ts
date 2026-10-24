import type { CustomLayerInterface, CustomRenderMethodInput, Map as MlMap } from "maplibre-gl";

export type Frame = {
  cores: Float32Array;
  nCore: number;
  trails: Float32Array;
  nTrail: number;
  animating: boolean;
};

const VERT = `#version 300 es
in vec2 a_pos;
in vec3 a_color;
in float a_size;
in float a_alpha;
uniform mat4 u_matrix;
out vec3 v_color;
out float v_alpha;
void main() {
  gl_Position = u_matrix * vec4(a_pos, 0.0, 1.0);
  gl_PointSize = a_size;
  v_color = a_color;
  v_alpha = a_alpha;
}`;

const FRAG = `#version 300 es
precision mediump float;
in vec3 v_color;
in float v_alpha;
out vec4 fragColor;
void main() {
  vec2 p = gl_PointCoord * 2.0 - 1.0;
  float d = dot(p, p);
  if (d > 1.0) discard;
  float halo = smoothstep(1.0, 0.18, d);
  float core = smoothstep(0.30, 0.0, d);
  float a = (halo * 0.28 + core * 0.92) * v_alpha;
  fragColor = vec4(v_color * a, a);
}`;

function compile(gl: WebGL2RenderingContext, type: number, source: string) {
  const shader = gl.createShader(type)!;
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    throw new Error(gl.getShaderInfoLog(shader) || "shader");
  }
  return shader;
}

export function createTrainLayer(sample: () => Frame): CustomLayerInterface {
  let program: WebGLProgram;
  let buf: WebGLBuffer;
  let uMatrix: WebGLUniformLocation;
  let map: MlMap;
  const stride = 7 * 4;

  return {
    id: "trains",
    type: "custom",
    renderingMode: "2d",
    onAdd(m, gl) {
      map = m;
      const gl2 = gl as WebGL2RenderingContext;
      const vs = compile(gl2, gl2.VERTEX_SHADER, VERT);
      const fs = compile(gl2, gl2.FRAGMENT_SHADER, FRAG);
      program = gl2.createProgram()!;
      gl2.attachShader(program, vs);
      gl2.attachShader(program, fs);
      gl2.linkProgram(program);
      if (!gl2.getProgramParameter(program, gl2.LINK_STATUS)) {
        throw new Error(gl2.getProgramInfoLog(program) || "link");
      }
      uMatrix = gl2.getUniformLocation(program, "u_matrix")!;
      buf = gl2.createBuffer()!;
    },
    render(gl, options: CustomRenderMethodInput) {
      const frame = sample();
      const gl2 = gl as WebGL2RenderingContext;
      gl2.useProgram(program);
      gl2.uniformMatrix4fv(uMatrix, false, options.modelViewProjectionMatrix);
      gl2.bindBuffer(gl2.ARRAY_BUFFER, buf);
      gl2.enable(gl2.BLEND);
      gl2.blendFunc(gl2.ONE, gl2.ONE_MINUS_SRC_ALPHA);
      gl2.disable(gl2.DEPTH_TEST);
      const loc = (name: string) => gl2.getAttribLocation(program, name);
      const bind = (array: Float32Array, count: number) => {
        if (count <= 0) return;
        gl2.bufferData(gl2.ARRAY_BUFFER, array.subarray(0, count * 7), gl2.DYNAMIC_DRAW);
        const aPos = loc("a_pos");
        const aColor = loc("a_color");
        const aSize = loc("a_size");
        const aAlpha = loc("a_alpha");
        gl2.enableVertexAttribArray(aPos);
        gl2.enableVertexAttribArray(aColor);
        gl2.enableVertexAttribArray(aSize);
        gl2.enableVertexAttribArray(aAlpha);
        gl2.vertexAttribPointer(aPos, 2, gl2.FLOAT, false, stride, 0);
        gl2.vertexAttribPointer(aColor, 3, gl2.FLOAT, false, stride, 8);
        gl2.vertexAttribPointer(aSize, 1, gl2.FLOAT, false, stride, 20);
        gl2.vertexAttribPointer(aAlpha, 1, gl2.FLOAT, false, stride, 24);
        gl2.drawArrays(gl2.POINTS, 0, count);
      };
      bind(frame.trails, frame.nTrail);
      bind(frame.cores, frame.nCore);
      if (frame.animating) map.triggerRepaint();
    },
  };
}
