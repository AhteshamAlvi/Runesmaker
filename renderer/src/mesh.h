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
    // Load a rune JSON and build a tube-sweep / sphere mesh.
    //
    // v5 render-spec format: {"version":5, "tubes":[...], "spheres":[...]}
    //   each tube   : {"points":[[x,y,z]...], "radius":r | "radii":[...], "sides":N}
    //   each sphere : {"center":[x,y,z], "radius":r}
    //
    // Older v2–v4 map format (blended / streamlines) is still accepted for
    // backwards-compatible viewing of raw maps.
    bool load_from_json(const std::string& path);

    const std::vector<Vertex>&   vertices() const { return m_vertices; }
    const std::vector<uint32_t>& indices()  const { return m_indices;  }

private:
    std::vector<Vertex>   m_vertices;
    std::vector<uint32_t> m_indices;

    // Sweep a tube along a 3D polyline. `radii` must have one entry per
    // centreline point; for a uniform tube, fill it with a constant.
    void tube_sweep(const std::vector<std::array<float, 3>>& centreline,
                    const std::vector<float>&                radii,
                    int sides);

    // Flat disc cap at the first/last ring of a tube.
    void add_cap(const std::vector<uint32_t>& ring,
                 const std::array<float, 3>& centre,
                 const std::array<float, 3>& normal,
                 bool flip);

    // Add a UV sphere at `centre`. `lat` = horizontal rings (excl. poles),
    // `lon` = vertices per ring.
    void add_sphere(const std::array<float, 3>& centre,
                    float                       radius,
                    int lat = 8, int lon = 12);
};
