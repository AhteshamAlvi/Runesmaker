#include "mesh.h"
#include <nlohmann/json.hpp>
#include <fstream>
#include <cmath>
#include <stdexcept>

// ─── Small vector helpers ────────────────────────────────────────────────────

static std::array<float,3> norm3(std::array<float,3> v) {
    float len = std::sqrt(v[0]*v[0] + v[1]*v[1] + v[2]*v[2]) + 1e-8f;
    return {v[0]/len, v[1]/len, v[2]/len};
}

static std::array<float,3> cross3(std::array<float,3> a, std::array<float,3> b) {
    return {
        a[1]*b[2] - a[2]*b[1],
        a[2]*b[0] - a[0]*b[2],
        a[0]*b[1] - a[1]*b[0]
    };
}

static float dot3(std::array<float,3> a, std::array<float,3> b) {
    return a[0]*b[0] + a[1]*b[1] + a[2]*b[2];
}


// ─── JSON loading ────────────────────────────────────────────────────────────

static std::vector<std::array<float, 3>>
read_points(const nlohmann::json& arr) {
    std::vector<std::array<float, 3>> out;
    out.reserve(arr.size());
    for (auto& pt : arr) {
        out.push_back({
            pt[0].get<float>(),
            pt[1].get<float>(),
            pt[2].get<float>()
        });
    }
    return out;
}

bool RuneMesh::load_from_json(const std::string& path) {
    std::ifstream file(path);
    if (!file.is_open()) return false;

    nlohmann::json data;
    file >> data;

    int version = data.value("version", 1);

    // ── v5 render-spec: list of 3D primitives produced by a render method ──
    if (version >= 5 && (data.contains("tubes") || data.contains("spheres"))) {

        if (data.contains("tubes")) {
            for (auto& t : data["tubes"]) {
                if (!t.contains("points")) continue;
                auto cl = read_points(t["points"]);
                if (cl.size() < 2) continue;

                int sides = t.value("sides", 8);

                std::vector<float> radii;
                if (t.contains("radii")) {
                    for (auto& r : t["radii"]) radii.push_back(r.get<float>());
                    // Guard against mismatched radii vs. centreline length.
                    if (radii.size() != cl.size()) continue;
                } else {
                    float r = t.value("radius", 0.02f);
                    radii.assign(cl.size(), r);
                }

                tube_sweep(cl, radii, sides);
            }
        }

        if (data.contains("spheres")) {
            for (auto& s : data["spheres"]) {
                if (!s.contains("center")) continue;
                std::array<float,3> c = {
                    s["center"][0].get<float>(),
                    s["center"][1].get<float>(),
                    s["center"][2].get<float>()
                };
                float r = s.value("radius", 0.02f);
                add_sphere(c, r);
            }
        }

        return true;
    }

    // ── Legacy map formats (v2–v4): raw blended / streamlines ─────────────
    //
    // The app's Generate step writes a RuneMap JSON with these fields. We
    // keep reading them so "View Map" and old rune files still open, but
    // the Render path now always goes through the v5 spec above.
    auto sweep_curve = [this](const nlohmann::json& arr, float radius, int sides) {
        auto cl = read_points(arr);
        if (cl.size() < 2) return;
        std::vector<float> radii(cl.size(), radius);
        tube_sweep(cl, radii, sides);
    };

    if (version >= 2 && data.contains("streamlines") && !data["streamlines"].empty()) {
        // All per-language streamlines as thin uniform tubes.
        for (auto& sl : data["streamlines"]) sweep_curve(sl, 0.015f, 8);
        return true;
    }
    if (version >= 2 && data.contains("blended")) {
        sweep_curve(data["blended"], 0.04f, 10);
        return true;
    }
    if (data.contains("points")) {
        // v1: lift the 2D contour into 3D at z=0 and sweep it.
        auto& arr = data["points"];
        std::vector<std::array<float,3>> cl;
        for (auto& pt : arr)
            cl.push_back({pt[0].get<float>(), pt[1].get<float>(), 0.0f});
        std::vector<float> radii(cl.size(), 0.04f);
        if (cl.size() >= 2) tube_sweep(cl, radii, 10);
        return true;
    }

    throw std::runtime_error("JSON has no recognised geometry (tubes/spheres/streamlines/blended/points).");
}


// ─── Tube sweep ──────────────────────────────────────────────────────────────
//
// Sweeps a ring of `sides` vertices along a 3D polyline using parallel-
// transport frames so normals don't flip at bends. Per-point radii let a
// tube swell and narrow along its length (used by calligraphic, path_follow).

void RuneMesh::tube_sweep(
    const std::vector<std::array<float, 3>>& cl,
    const std::vector<float>&                radii,
    int sides)
{
    size_t n = cl.size();
    if (n < 2 || radii.size() != n) return;

    // ── Per-point tangents ────────────────────────────────────────────────
    std::vector<std::array<float,3>> T(n);
    for (size_t i = 0; i + 1 < n; ++i) {
        T[i] = norm3({cl[i+1][0]-cl[i][0],
                      cl[i+1][1]-cl[i][1],
                      cl[i+1][2]-cl[i][2]});
    }
    T[n-1] = T[n-2];

    // ── Seed normal perpendicular to T[0] ────────────────────────────────
    std::array<float,3> seed = {0.f, 1.f, 0.f};
    if (std::abs(dot3(T[0], seed)) > 0.9f) seed = {1.f, 0.f, 0.f};
    float d = dot3(seed, T[0]);
    std::array<float,3> N = norm3({seed[0]-d*T[0][0],
                                   seed[1]-d*T[0][1],
                                   seed[2]-d*T[0][2]});

    // ── Build rings with parallel-transport ──────────────────────────────
    std::vector<std::vector<uint32_t>> rings(n);

    for (size_t i = 0; i < n; ++i) {
        std::array<float,3> B = norm3(cross3(T[i], N));
        N = norm3(cross3(B, T[i]));   // re-orthogonalise

        float r = radii[i];

        uint32_t base = static_cast<uint32_t>(m_vertices.size());
        for (int j = 0; j < sides; ++j) {
            float angle = 2.f * static_cast<float>(M_PI) * j / sides;
            float ca = std::cos(angle), sa = std::sin(angle);

            std::array<float,3> outward = {ca*N[0]+sa*B[0],
                                           ca*N[1]+sa*B[1],
                                           ca*N[2]+sa*B[2]};
            m_vertices.push_back({
                {cl[i][0] + r*outward[0],
                 cl[i][1] + r*outward[1],
                 cl[i][2] + r*outward[2]},
                outward   // outward IS the surface normal for a tube
            });
            rings[i].push_back(base + static_cast<uint32_t>(j));
        }

        // Parallel-transport N to the next frame (Rodrigues rotation).
        if (i + 1 < n) {
            std::array<float,3> axis = cross3(T[i], T[i+1]);
            float sin_a = std::sqrt(dot3(axis, axis));
            if (sin_a > 1e-8f) {
                axis = norm3(axis);
                float cos_a = dot3(T[i], T[i+1]);
                std::array<float,3> axN = cross3(axis, N);
                float d_an = dot3(axis, N);
                N = {
                    cos_a*N[0] + sin_a*axN[0] + (1.f-cos_a)*d_an*axis[0],
                    cos_a*N[1] + sin_a*axN[1] + (1.f-cos_a)*d_an*axis[1],
                    cos_a*N[2] + sin_a*axN[2] + (1.f-cos_a)*d_an*axis[2]
                };
                N = norm3(N);
            }
        }

        // Connect this ring to the previous one.
        if (i > 0) {
            for (int j = 0; j < sides; ++j) {
                int jn = (j + 1) % sides;
                m_indices.push_back(rings[i-1][j]);
                m_indices.push_back(rings[i  ][j]);
                m_indices.push_back(rings[i  ][jn]);

                m_indices.push_back(rings[i-1][j]);
                m_indices.push_back(rings[i  ][jn]);
                m_indices.push_back(rings[i-1][jn]);
            }
        }
    }

    // End caps.
    std::array<float,3> front_n = {-T[0][0],   -T[0][1],   -T[0][2]};
    std::array<float,3> back_n  = { T[n-1][0],  T[n-1][1],  T[n-1][2]};
    add_cap(rings[0],   cl[0],   front_n, /*flip=*/false);
    add_cap(rings[n-1], cl[n-1], back_n,  /*flip=*/true);
}


// ─── Flat disc cap ───────────────────────────────────────────────────────────

void RuneMesh::add_cap(
    const std::vector<uint32_t>& ring,
    const std::array<float, 3>& centre,
    const std::array<float, 3>& normal,
    bool flip)
{
    uint32_t c_idx = static_cast<uint32_t>(m_vertices.size());
    m_vertices.push_back({centre, normal});

    int sides = static_cast<int>(ring.size());
    for (int j = 0; j < sides; ++j) {
        int jn = (j + 1) % sides;
        if (flip) {
            m_indices.push_back(c_idx);
            m_indices.push_back(ring[jn]);
            m_indices.push_back(ring[j]);
        } else {
            m_indices.push_back(c_idx);
            m_indices.push_back(ring[j]);
            m_indices.push_back(ring[jn]);
        }
    }
}


// ─── UV sphere ───────────────────────────────────────────────────────────────
//
// Builds a sphere from stacked rings of vertices (longitude × latitude).
// North and south poles are single vertices fanning to their neighbouring
// rings. Normals are the outward unit vectors from the sphere centre.

void RuneMesh::add_sphere(
    const std::array<float, 3>& centre,
    float                       radius,
    int lat, int lon)
{
    if (lat < 2)  lat = 2;
    if (lon < 3)  lon = 3;

    uint32_t base = static_cast<uint32_t>(m_vertices.size());

    // Ring vertices (excluding poles). lat rings, lon verts per ring.
    for (int i = 0; i < lat; ++i) {
        float phi = static_cast<float>(M_PI) * (i + 1) / (lat + 1);  // (0, π)
        float cy  = std::cos(phi);
        float sy  = std::sin(phi);
        for (int j = 0; j < lon; ++j) {
            float theta = 2.f * static_cast<float>(M_PI) * j / lon;
            std::array<float,3> n = {sy * std::cos(theta), cy, sy * std::sin(theta)};
            m_vertices.push_back({
                {centre[0] + radius*n[0],
                 centre[1] + radius*n[1],
                 centre[2] + radius*n[2]},
                n
            });
        }
    }

    // Poles.
    uint32_t north = static_cast<uint32_t>(m_vertices.size());
    m_vertices.push_back({
        {centre[0], centre[1] + radius, centre[2]}, {0.f, 1.f, 0.f}
    });
    uint32_t south = static_cast<uint32_t>(m_vertices.size());
    m_vertices.push_back({
        {centre[0], centre[1] - radius, centre[2]}, {0.f, -1.f, 0.f}
    });

    auto ring_idx = [base, lon](int i, int j) {
        return base + static_cast<uint32_t>(i * lon + (j % lon));
    };

    // Quads between adjacent rings.
    for (int i = 0; i + 1 < lat; ++i) {
        for (int j = 0; j < lon; ++j) {
            uint32_t a = ring_idx(i,     j);
            uint32_t b = ring_idx(i,     j + 1);
            uint32_t c = ring_idx(i + 1, j);
            uint32_t dI = ring_idx(i + 1, j + 1);

            m_indices.push_back(a);
            m_indices.push_back(c);
            m_indices.push_back(b);

            m_indices.push_back(b);
            m_indices.push_back(c);
            m_indices.push_back(dI);
        }
    }

    // North fan (top ring i=0 ↔ north pole).
    for (int j = 0; j < lon; ++j) {
        m_indices.push_back(north);
        m_indices.push_back(ring_idx(0, j + 1));
        m_indices.push_back(ring_idx(0, j));
    }
    // South fan (bottom ring i=lat-1 ↔ south pole).
    for (int j = 0; j < lon; ++j) {
        m_indices.push_back(south);
        m_indices.push_back(ring_idx(lat - 1, j));
        m_indices.push_back(ring_idx(lat - 1, j + 1));
    }
}
