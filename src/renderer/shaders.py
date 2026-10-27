"""GLSL 3.3 Core reference lines and textured vertex-colored track surfaces."""

LINE_VERTEX_SHADER: str = """#version 330 core
layout(location = 0) in vec3 a_position;
layout(location = 1) in vec3 a_color;
uniform mat4 u_view_projection;
out vec3 v_color;
out vec3 v_world;
void main() {
    gl_Position = u_view_projection * vec4(a_position, 1.0);
    v_color = a_color;
    v_world = a_position;
}
"""

LINE_FRAGMENT_SHADER: str = """#version 330 core
in vec3 v_color;
in vec3 v_world;
uniform bool u_grid;
uniform vec3 u_grid_center;
uniform float u_grid_radius;
out vec4 frag_color;
void main() {
    float alpha = u_grid ? 0.65 * (1.0-smoothstep(0.45, 1.0, length(v_world-u_grid_center)/u_grid_radius)) : 1.0;
    frag_color = vec4(v_color, alpha);
}
"""

FOG_VERTEX: str = """
layout(std140) uniform Environment { vec4 fog_params; vec4 fog_color; };
noperspective out float v_fog;
float environment_fog(float depth) {
    float ndc = 15010.0 / 14990.0 - 300000.0 / (14990.0 * max(depth, 0.001));
    return fog_color.a * clamp((500.0 * (ndc + 1.0) - fog_params.x) / max(fog_params.y-fog_params.x, 5.0), 0.0, 1.0);
}
"""
FOG_FRAGMENT: str = """
layout(std140) uniform Environment { vec4 fog_params; vec4 fog_color; };
noperspective in float v_fog;
"""

TRACK_VERTEX_SHADER: str = """#version 330 core
""" + FOG_VERTEX + """
layout(location = 0) in vec3 a_position;
layout(location = 1) in vec4 a_color;
layout(location = 2) in vec2 a_uv;
uniform mat4 u_view_projection;
out vec4 v_color;
out vec2 v_uv;
void main() {
    gl_Position = u_view_projection * vec4(a_position, 1.0);
    v_fog = environment_fog(gl_Position.w);
    v_color = a_color;
    v_uv = a_uv;
}
"""

TRACK_FRAGMENT_SHADER: str = """#version 330 core
""" + FOG_FRAGMENT + """
in vec4 v_color;
in vec2 v_uv;
uniform bool u_vertex_colors;
uniform bool u_wireframe;
uniform bool u_textured;
uniform bool u_vertex_alpha;
uniform sampler2D u_texture;
out vec4 frag_color;
void main() {
    vec4 texel = u_textured ? texture(u_texture, v_uv) : vec4(1.0);
    vec3 color = u_vertex_colors ? v_color.rgb : (u_textured ? vec3(1.0) : vec3(0.68, 0.72, 0.77));
    frag_color = vec4(texel.rgb * color, texel.a * (u_vertex_alpha ? v_color.a : 1.0));
    if (u_wireframe) frag_color = vec4(0.035, 0.05, 0.075, 1.0);
    if (frag_color.a < 0.1) discard;
    if (!u_wireframe) frag_color.rgb = mix(frag_color.rgb, fog_color.rgb, v_fog);
}
"""

SPRITE_VERTEX_SHADER: str = """#version 330 core
""" + FOG_VERTEX + """
layout(location = 0) in vec3 a_center;
layout(location = 1) in vec2 a_offset;
layout(location = 2) in vec2 a_uv;
uniform mat4 u_view_projection;
uniform vec3 u_camera_right;
uniform vec3 u_camera_up;
uniform vec3 u_camera_position;
uniform bool u_upright;
out vec2 v_uv;
void main() {
    vec3 right = u_camera_right;
    vec3 up = u_camera_up;
    if (u_upright) {
        vec3 delta = u_camera_position - a_center;
        right = vec3(delta.z, 0.0, -delta.x);
        if (dot(right, right) < 0.00000001) right = vec3(u_camera_right.x, 0.0, u_camera_right.z);
        if (dot(right, right) < 0.00000001) right = vec3(1.0, 0.0, 0.0);
        right = normalize(right);
        up = vec3(0.0, 1.0, 0.0);
    }
    vec3 position = a_center + right * a_offset.x + up * a_offset.y;
    gl_Position = u_view_projection * vec4(position, 1.0);
    v_fog = environment_fog(gl_Position.w);
    v_uv = a_uv;
}
"""

SPRITE_FRAGMENT_SHADER: str = """#version 330 core
""" + FOG_FRAGMENT + """
in vec2 v_uv;
uniform sampler2D u_texture;
out vec4 frag_color;
void main() {
    frag_color = texture(u_texture, v_uv);
    if (frag_color.a < 0.1) discard;
    frag_color.rgb = mix(frag_color.rgb, fog_color.rgb, v_fog);
}
"""

BACKGROUND_VERTEX: str = """#version 330 core
out float v_height;
void main() {
    vec2 p = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);
    v_height = p.y;
    gl_Position = vec4(p * 2.0 - 1.0, 1.0, 1.0);
}
"""

WATER_FRAGMENT: str = """#version 330 core
""" + FOG_FRAGMENT + """
in vec4 v_color;
in vec2 v_uv;
uniform bool u_wireframe;
uniform bool u_textured;
uniform sampler2D u_texture;
uniform sampler2D u_detail;
uniform vec2 u_detail_scale;
out vec4 frag_color;
void main() {
    vec4 base = u_textured ? texture(u_texture, v_uv) : vec4(0.25, 0.65, 0.85, 1.0);
    vec4 detail = u_textured ? texture(u_detail, v_uv * u_detail_scale) : base;
    // f3ddkr.h G_CC_BLENDTEX_MODULATEA_1_PRIM then
    // G_CC_BLENDI_ENV_ALPHA_MODULATEA2, neutral environment color/alpha.
    frag_color = vec4(mix(base.rgb, detail.rgb, v_color.rgb), base.a * v_color.a);
    if (u_wireframe) frag_color = vec4(0.035, 0.05, 0.075, 1.0);
    if (frag_color.a < 0.1) discard;
}
"""
BACKGROUND_FRAGMENT: str = """#version 330 core
in float v_height;
uniform vec3 u_bottom;
uniform vec3 u_top;
out vec4 frag_color;
void main() { frag_color = vec4(mix(u_bottom, u_top, clamp(v_height, 0.0, 1.0)), 1.0); }
"""
