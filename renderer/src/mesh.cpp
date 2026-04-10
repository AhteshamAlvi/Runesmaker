#include "mesh.h"
#include <nlohmann/json.hpp>
#include <fstream>
#include <cmath>
#include <numeric>

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

// --- Ear-clipping triangulation helpers ---

static float cross2D(float ax, float ay, float bx, float by) {
    return ax * by - ay * bx;
}

// Signed area of polygon — positive = CCW, negative = CW
static float polygonArea(const std::vector<std::array<float, 2>>& poly,
                         const std::vector<int>& idx) {
    float area = 0;
    int n = static_cast<int>(idx.size());
    for (int i = 0; i < n; i++) {
        int j = (i + 1) % n;
        area += poly[idx[i]][0] * poly[idx[j]][1];
        area -= poly[idx[j]][0] * poly[idx[i]][1];
    }
    return area * 0.5f;
}

// Check if point P is inside triangle ABC (using barycentric coordinates)
static bool pointInTriangle(float px, float py,
                            float ax, float ay,
                            float bx, float by,
                            float cx, float cy) {
    float d1 = cross2D(bx - ax, by - ay, px - ax, py - ay);
    float d2 = cross2D(cx - bx, cy - by, px - bx, py - by);
    float d3 = cross2D(ax - cx, ay - cy, px - cx, py - cy);

    bool hasNeg = (d1 < 0) || (d2 < 0) || (d3 < 0);
    bool hasPos = (d1 > 0) || (d2 > 0) || (d3 > 0);

    return !(hasNeg && hasPos);
}

// Ear-clipping triangulation: returns list of triangle index triples
static std::vector<std::array<int, 3>> earClip(
    const std::vector<std::array<float, 2>>& poly)
{
    std::vector<std::array<int, 3>> triangles;
    int n = static_cast<int>(poly.size());
    if (n < 3) return triangles;

    // Build index list
    std::vector<int> idx(n);
    std::iota(idx.begin(), idx.end(), 0);

    // Ensure CCW winding
    if (polygonArea(poly, idx) < 0) {
        std::reverse(idx.begin(), idx.end());
    }

    int remaining = n;
    int failCount = 0;

    while (remaining > 2 && failCount < remaining) {
        for (int i = 0; i < remaining; i++) {
            int prev = (i + remaining - 1) % remaining;
            int next = (i + 1) % remaining;

            float ax = poly[idx[prev]][0], ay = poly[idx[prev]][1];
            float bx = poly[idx[i]][0],    by = poly[idx[i]][1];
            float cx = poly[idx[next]][0], cy = poly[idx[next]][1];

            // Check if this is a convex (ear) vertex
            float cross = cross2D(bx - ax, by - ay, cx - bx, cy - by);
            if (cross <= 1e-8f) {
                // Reflex or degenerate — not an ear
                failCount++;
                continue;
            }

            // Check no other vertex is inside this triangle
            bool earOk = true;
            for (int j = 0; j < remaining; j++) {
                if (j == prev || j == i || j == next) continue;
                if (pointInTriangle(poly[idx[j]][0], poly[idx[j]][1],
                                    ax, ay, bx, by, cx, cy)) {
                    earOk = false;
                    break;
                }
            }

            if (earOk) {
                triangles.push_back({idx[prev], idx[i], idx[next]});
                idx.erase(idx.begin() + i);
                remaining--;
                failCount = 0;
                break;
            } else {
                failCount++;
            }
        }
    }

    return triangles;
}

// --- Cap face generation ---

void RuneMesh::triangulateCap(const std::vector<std::array<float, 2>>& contour,
                              float z, const std::array<float, 3>& normal, bool flip) {
    auto triangles = earClip(contour);

    uint32_t base = static_cast<uint32_t>(m_vertices.size());

    // Add all contour vertices at the given Z depth
    for (auto& pt : contour) {
        m_vertices.push_back({{pt[0], pt[1], z}, normal});
    }

    // Add triangle indices
    for (auto& tri : triangles) {
        if (flip) {
            m_indices.push_back(base + tri[0]);
            m_indices.push_back(base + tri[2]);
            m_indices.push_back(base + tri[1]);
        } else {
            m_indices.push_back(base + tri[0]);
            m_indices.push_back(base + tri[1]);
            m_indices.push_back(base + tri[2]);
        }
    }
}

// --- Extrusion ---

void RuneMesh::extrude(const std::vector<std::array<float, 2>>& contour, float depth) {
    float half = depth / 2.0f;
    size_t n = contour.size();

    // Front cap (facing +Z)
    triangulateCap(contour, half, {0, 0, 1}, false);

    // Back cap (facing -Z)
    triangulateCap(contour, -half, {0, 0, -1}, true);

    // Side walls
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
