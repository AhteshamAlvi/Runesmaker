#include "mesh.h"
#include <nlohmann/json.hpp>
#include <fstream>

bool RuneMesh::load_from_json(const std::string& path) {
    std::ifstream file(path);
    if (!file.is_open()) return false;

    nlohmann::json data;
    file >> data;

    std::vector<std::array<float, 2>> contour;
    for (auto& pt : data["points"]) {
        contour.push_back({pt[0].get<float>(), pt[1].get<float>()});
    }

    extrude(contour, 0.3f);
    return true;
}

void RuneMesh::extrude(const std::vector<std::array<float, 2>>& contour, float depth) {
    // TODO: Generate front face, back face, and side walls from 2D contour
    // For now, create simple line-strip extruded quads

    float half = depth / 2.0f;
    size_t n = contour.size();

    for (size_t i = 0; i < n; ++i) {
        size_t next = (i + 1) % n;

        float x0 = contour[i][0], y0 = contour[i][1];
        float x1 = contour[next][0], y1 = contour[next][1];

        // Compute side normal
        float dx = x1 - x0, dy = y1 - y0;
        float len = std::sqrt(dx * dx + dy * dy);
        float nx = -dy / (len + 1e-8f), ny = dx / (len + 1e-8f);

        uint32_t base = static_cast<uint32_t>(m_vertices.size());

        m_vertices.push_back({{x0, y0, -half}, {nx, ny, 0}});
        m_vertices.push_back({{x1, y1, -half}, {nx, ny, 0}});
        m_vertices.push_back({{x1, y1,  half}, {nx, ny, 0}});
        m_vertices.push_back({{x0, y0,  half}, {nx, ny, 0}});

        m_indices.insert(m_indices.end(), {
            base, base + 1, base + 2,
            base, base + 2, base + 3
        });
    }
}
