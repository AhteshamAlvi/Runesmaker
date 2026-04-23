#include "mesh.h"
#include <nlohmann/json.hpp>
#include <fstream>
#include <cmath>
#include <stdexcept>

// ─── JSON loading ────────────────────────────────────────────────────────────

bool RuneMesh::load_from_json(const std::string& path) {
    std::ifstream file(path);
    if (!file.is_open()) return false;

    nlohmann::json data;
    file >> data;

    int version = data.value("version", 1);

    if (version >= 2) {
        // ── New format: read the pre-built 3D blended centreline ──────────
        if (!data.contains("blended"))
            throw std::runtime_error("JSON v2 missing 'blended' field");

        std::vector<std::array<float, 3>> centreline;
        for (auto& pt : data["blended"]) {
            centreline.push_back({
                pt[0].get<float>(),
                pt[1].get<float>(),
                pt[2].get<float>()
            });
        }

        if (centreline.size() < 2)
            throw std::runtime_error("Centreline has fewer than 2 points");

        tube_sweep(centreline, /*radius=*/0.04f, /*sides=*/10);

    } else {
        // ── Legacy format (v1): 2D contour extrusion (kept for compatibility)
        if (!data.contains("points"))
            throw std::runtime_error("JSON v1 missing 'points' field");

        std::vector<std::array<float, 3>> centreline;
        for (auto& pt : data["points"]) {
            // Lift the 2D contour into 3D at z=0 so the legacy tube_sweep works
            centreline.push_back({pt[0].get<float>(), pt[1].get<float>(), 0.0f});
        }
        tube_sweep(centreline, 0.04f, 10);
    }

    return true;
}


// ─── Tube sweep ──────────────────────────────────────────────────────────────
//
// Builds a smooth tube around a 3D polyline using parallel-transport frames
// to avoid sudden normal flips.  At each point we place a ring of `sides`
// vertices in the plane perpendicular to the local tangent, then connect
// successive rings with quads (two triangles each).  End caps are added.

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

void RuneMesh::tube_sweep(
    const std::vector<std::array<float, 3>>& cl,
    float radius, int sides)
{
    size_t n = cl.size();
    if (n < 2) return;

    // ── Compute per-point tangents ────────────────────────────────────────
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
    // Project seed onto plane perpendicular to T[0]
    float d = dot3(seed, T[0]);
    std::array<float,3> N = norm3({seed[0]-d*T[0][0],
                                   seed[1]-d*T[0][1],
                                   seed[2]-d*T[0][2]});

    // ── Build rings with parallel-transport ──────────────────────────────
    std::vector<std::vector<uint32_t>> rings(n);

    for (size_t i = 0; i < n; ++i) {
        // B = T × N (binormal)
        std::array<float,3> B = norm3(cross3(T[i], N));
        // Re-orthogonalise N = B × T
        N = norm3(cross3(B, T[i]));

        uint32_t base = static_cast<uint32_t>(m_vertices.size());
        for (int j = 0; j < sides; ++j) {
            float angle = 2.f * static_cast<float>(M_PI) * j / sides;
            float ca = std::cos(angle), sa = std::sin(angle);

            std::array<float,3> outward = {ca*N[0]+sa*B[0],
                                           ca*N[1]+sa*B[1],
                                           ca*N[2]+sa*B[2]};
            m_vertices.push_back({
                {cl[i][0] + radius*outward[0],
                 cl[i][1] + radius*outward[1],
                 cl[i][2] + radius*outward[2]},
                outward   // outward IS the surface normal for a tube
            });
            rings[i].push_back(base + static_cast<uint32_t>(j));
        }

        // ── Parallel-transport N to next frame (Rodrigues rotation) ──────
        if (i + 1 < n) {
            std::array<float,3> axis = cross3(T[i], T[i+1]);
            float sin_a = std::sqrt(dot3(axis, axis));
            if (sin_a > 1e-8f) {
                axis = norm3(axis);
                float cos_a = dot3(T[i], T[i+1]);
                // Rodrigues: N_new = cos·N + sin·(axis×N) + (1-cos)·(axis·N)·axis
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

        // ── Connect this ring to the previous one ─────────────────────────
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

    // ── End caps ─────────────────────────────────────────────────────────
    // Compute reversed tangent for back cap normal
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
    // Centre vertex
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
