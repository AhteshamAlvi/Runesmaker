#define STB_IMAGE_WRITE_IMPLEMENTATION
#include "../third_party/stb_image_write.h"
#include "exporter.h"

namespace Exporter {

bool save_png(const std::string& path, const uint8_t* pixels,
              uint32_t width, uint32_t height) {
    // RGBA, 4 bytes per pixel
    return stbi_write_png(path.c_str(), width, height, 4, pixels, width * 4) != 0;
}

} // namespace Exporter
