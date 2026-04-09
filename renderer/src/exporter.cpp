#include "exporter.h"
#include <fstream>

// TODO: Use stb_image_write for proper PNG export

namespace Exporter {

bool save_png(const std::string& path, const uint8_t* pixels,
              uint32_t width, uint32_t height) {
    // Placeholder — will integrate stb_image_write
    (void)pixels;
    (void)width;
    (void)height;

    std::ofstream f(path);
    return f.is_open();
}

} // namespace Exporter
