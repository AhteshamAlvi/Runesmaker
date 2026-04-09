#version 450

layout(location = 0) in vec3 fragNormal;
layout(location = 1) in vec3 fragWorldPos;

layout(location = 0) out vec4 outColor;

void main() {
    vec3 lightDir = normalize(vec3(1.0, 1.0, 1.0));
    vec3 normal = normalize(fragNormal);

    float ambient = 0.15;
    float diffuse = max(dot(normal, lightDir), 0.0);

    vec3 runeColor = vec3(0.7, 0.85, 1.0); // pale blue glow
    vec3 color = runeColor * (ambient + diffuse * 0.85);

    outColor = vec4(color, 1.0);
}
