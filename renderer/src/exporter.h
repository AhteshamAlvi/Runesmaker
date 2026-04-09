#pragma once

#include <string>
#include <cstdint>

// TODO: Read Vulkan framebuffer pixels and write to PNG

namespace Exporter {
    bool save_png(const std::string& path, const uint8_t* pixels,
                  uint32_t width, uint32_t height);
}
