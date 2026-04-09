#pragma once

#include <glm/glm.hpp>

class Camera {
public:
    Camera();

    void rotate(float dx, float dy);
    void zoom(float delta);

    glm::mat4 view_matrix() const;
    glm::mat4 projection_matrix(float aspect) const;

private:
    float m_yaw = 0.0f;
    float m_pitch = 0.0f;
    float m_distance = 3.0f;
    float m_fov = 45.0f;
};
