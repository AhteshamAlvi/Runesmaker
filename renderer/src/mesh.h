#pragma once

#include <string>
#include <vector>
#include <array>

struct Vertex {
    std::array<float, 3> position;
    std::array<float, 3> normal;
};

// TODO: Load a rune JSON contour and extrude it into a 3D mesh

class RuneMesh {
public:
    bool load_from_json(const std::string& path);

    const std::vector<Vertex>& vertices() const { return m_vertices; }
    const std::vector<uint32_t>& indices() const { return m_indices; }

private:
    std::vector<Vertex> m_vertices;
    std::vector<uint32_t> m_indices;

    void extrude(const std::vector<std::array<float, 2>>& contour, float depth);
};
