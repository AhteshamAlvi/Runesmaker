#include "camera.h"
#include <glm/gtc/matrix_transform.hpp>
#include <cmath>

Camera::Camera() {}

void Camera::rotate(float dx, float dy) {
    m_yaw += dx * 0.5f;
    m_pitch = glm::clamp(m_pitch + dy * 0.5f, -89.0f, 89.0f);
}

void Camera::zoom(float delta) {
    m_distance = glm::clamp(m_distance - delta * 0.3f, 0.5f, 20.0f);
}

glm::mat4 Camera::view_matrix() const {
    float yaw_rad = glm::radians(m_yaw);
    float pitch_rad = glm::radians(m_pitch);

    glm::vec3 eye(
        m_distance * cos(pitch_rad) * sin(yaw_rad),
        m_distance * sin(pitch_rad),
        m_distance * cos(pitch_rad) * cos(yaw_rad)
    );

    return glm::lookAt(eye, glm::vec3(0.0f), glm::vec3(0.0f, 1.0f, 0.0f));
}

glm::mat4 Camera::projection_matrix(float aspect) const {
    return glm::perspective(glm::radians(m_fov), aspect, 0.1f, 100.0f);
}
