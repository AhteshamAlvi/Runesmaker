#pragma once

#include <string>
#include <vector>
#include <array>

struct Vertex {
    std::array<float, 3> position;
    std::array<float, 3> normal;
};

class RuneMesh {
public:
    // Load a version-2 rune JSON and build a tube-sweep mesh.
    bool load_from_json(const std::string& path);

    const std::vector<Vertex>&   vertices() const { return m_vertices; }
    const std::vector<uint32_t>& indices()  const { return m_indices;  }

private:
    std::vector<Vertex>   m_vertices;
    std::vector<uint32_t> m_indices;

    // Sweep a circle of `sides` vertices along a 3D polyline.
    // radius  — tube cross-section radius
    // sides   — number of vertices around the circle (8 is fine)
    void tube_sweep(const std::vector<std::array<float, 3>>& centreline,
                    float radius, int sides = 8);

    // Add a flat disc cap at the first/last ring to close the tube ends.
    void add_cap(const std::vector<uint32_t>& ring,
                 const std::array<float, 3>& centre,
                 const std::array<float, 3>& normal,
                 bool flip);
};
