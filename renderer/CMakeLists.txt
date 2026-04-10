cmake_minimum_required(VERSION 3.20)
project(RuneRenderer LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(Vulkan REQUIRED)

# GLFW
add_subdirectory(third_party/glfw)

# GLM (header-only)
add_subdirectory(third_party/glm)

# nlohmann/json (header-only, for loading rune JSON)
add_subdirectory(third_party/json)

add_executable(rune_renderer
    src/main.cpp
    src/app.cpp
    src/vulkan_context.cpp
    src/pipeline.cpp
    src/mesh.cpp
    src/camera.cpp
    src/exporter.cpp
)

target_include_directories(rune_renderer PRIVATE src third_party)
target_link_libraries(rune_renderer PRIVATE
    Vulkan::Vulkan
    glfw
    glm::glm
    nlohmann_json::nlohmann_json
)

# macOS: ensure GLFW's dlopen("libvulkan.1.dylib") can find the Vulkan loader
# by adding its directory to the runtime search path
if(APPLE)
    get_target_property(VULKAN_LIB Vulkan::Vulkan IMPORTED_LOCATION)
    if(VULKAN_LIB)
        get_filename_component(VULKAN_LIB_DIR "${VULKAN_LIB}" DIRECTORY)
        set_target_properties(rune_renderer PROPERTIES
            BUILD_RPATH "${VULKAN_LIB_DIR}"
            INSTALL_RPATH "${VULKAN_LIB_DIR}"
        )
    endif()
endif()

# Compile shaders — find glslc from PATH or VULKAN_SDK
find_program(GLSLC glslc HINTS $ENV{VULKAN_SDK}/bin /opt/homebrew/bin /usr/local/bin)
if(GLSLC)
    message(STATUS "Found glslc: ${GLSLC}")
    set(SHADER_DIR ${CMAKE_CURRENT_SOURCE_DIR}/shaders)
    set(SPIRV_DIR ${CMAKE_CURRENT_BINARY_DIR}/shaders)
    file(MAKE_DIRECTORY ${SPIRV_DIR})

    add_custom_command(
        OUTPUT ${SPIRV_DIR}/rune.vert.spv
        COMMAND ${GLSLC} ${SHADER_DIR}/rune.vert -o ${SPIRV_DIR}/rune.vert.spv
        DEPENDS ${SHADER_DIR}/rune.vert
    )
    add_custom_command(
        OUTPUT ${SPIRV_DIR}/rune.frag.spv
        COMMAND ${GLSLC} ${SHADER_DIR}/rune.frag -o ${SPIRV_DIR}/rune.frag.spv
        DEPENDS ${SHADER_DIR}/rune.frag
    )
    add_custom_target(shaders DEPENDS
        ${SPIRV_DIR}/rune.vert.spv
        ${SPIRV_DIR}/rune.frag.spv
    )
    add_dependencies(rune_renderer shaders)
else()
    message(WARNING "glslc not found — shaders will not be compiled")
endif()
