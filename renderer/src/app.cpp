#include "app.h"
#include "exporter.h"
#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>
#include <iostream>
#include <cstring>
#include <filesystem>
#ifdef __APPLE__
#include <mach-o/dyld.h>  // _NSGetExecutablePath
#endif

struct PushConstants {
    glm::mat4 mvp;
    glm::mat4 model;
};

App::App(const std::string& rune_path, const std::string& export_path)
    : m_rune_path(rune_path), m_export_path(export_path) {}

App::~App() {
    cleanup();
}

void App::run() {
    init();
    main_loop();
}

void App::init() {
    // Load mesh first (no GPU needed)
    if (!m_mesh.load_from_json(m_rune_path))
        throw std::runtime_error("Failed to load rune JSON: " + m_rune_path);

    std::cout << "Loaded " << m_mesh.vertices().size() << " vertices, "
              << m_mesh.indices().size() << " indices\n";

    // Init GLFW
    glfwInit();
    glfwWindowHint(GLFW_CLIENT_API, GLFW_NO_API);
    glfwWindowHint(GLFW_RESIZABLE, GLFW_FALSE);
    m_window = glfwCreateWindow(800, 600, "Runesmaker", nullptr, nullptr);

    glfwSetWindowUserPointer(m_window, this);
    glfwSetMouseButtonCallback(m_window, mouseButtonCallback);
    glfwSetCursorPosCallback(m_window, cursorPosCallback);
    glfwSetScrollCallback(m_window, scrollCallback);

    // Init Vulkan
    m_ctx.init(m_window);

    // Find shader directory — try several locations
    std::string shaderDir;
    std::vector<std::string> candidates = {
        "shaders",                      // cwd = renderer/build
        "build/shaders",                // cwd = renderer
        "renderer/build/shaders",       // cwd = project root
    };

    // Resolve path relative to the executable itself (most reliable)
    {
        // On macOS, _NSGetExecutablePath gives the binary location
        char exePath[4096];
        uint32_t exeSize = sizeof(exePath);
        if (_NSGetExecutablePath(exePath, &exeSize) == 0) {
            auto exeDir = std::filesystem::path(exePath).parent_path();
            candidates.insert(candidates.begin(), (exeDir / "shaders").string());
        }
    }

    for (auto& dir : candidates) {
        if (std::filesystem::exists(dir + "/rune.vert.spv")) {
            shaderDir = dir;
            break;
        }
    }
    if (shaderDir.empty())
        throw std::runtime_error("Cannot find compiled shaders (rune.vert.spv). "
                                 "Run: cd renderer/build && cmake .. && make");

    m_pipeline.init(m_ctx, shaderDir);
    createBuffers();
    createSyncObjects();
    allocateCommandBuffers();

    std::cout << "Renderer initialized. Drag to orbit, scroll to zoom.\n";
}

// --- GPU Buffer Creation ---

VkBuffer App::createBuffer(VkDeviceSize size, VkBufferUsageFlags usage,
                           VkMemoryPropertyFlags properties, VkDeviceMemory& memory) {
    VkBufferCreateInfo bci{};
    bci.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO;
    bci.size = size;
    bci.usage = usage;
    bci.sharingMode = VK_SHARING_MODE_EXCLUSIVE;

    VkBuffer buffer;
    vkCreateBuffer(m_ctx.device, &bci, nullptr, &buffer);

    VkMemoryRequirements memReqs;
    vkGetBufferMemoryRequirements(m_ctx.device, buffer, &memReqs);

    VkMemoryAllocateInfo alloc{};
    alloc.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO;
    alloc.allocationSize = memReqs.size;
    alloc.memoryTypeIndex = m_ctx.findMemoryType(memReqs.memoryTypeBits, properties);

    vkAllocateMemory(m_ctx.device, &alloc, nullptr, &memory);
    vkBindBufferMemory(m_ctx.device, buffer, memory, 0);
    return buffer;
}

void App::createBuffers() {
    // Vertex buffer
    VkDeviceSize vSize = sizeof(Vertex) * m_mesh.vertices().size();
    m_vertexBuffer = createBuffer(vSize,
        VK_BUFFER_USAGE_VERTEX_BUFFER_BIT,
        VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT,
        m_vertexMemory);

    void* data;
    vkMapMemory(m_ctx.device, m_vertexMemory, 0, vSize, 0, &data);
    memcpy(data, m_mesh.vertices().data(), vSize);
    vkUnmapMemory(m_ctx.device, m_vertexMemory);

    // Index buffer
    VkDeviceSize iSize = sizeof(uint32_t) * m_mesh.indices().size();
    m_indexBuffer = createBuffer(iSize,
        VK_BUFFER_USAGE_INDEX_BUFFER_BIT,
        VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT,
        m_indexMemory);

    vkMapMemory(m_ctx.device, m_indexMemory, 0, iSize, 0, &data);
    memcpy(data, m_mesh.indices().data(), iSize);
    vkUnmapMemory(m_ctx.device, m_indexMemory);
}

void App::createSyncObjects() {
    VkSemaphoreCreateInfo sci{};
    sci.sType = VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO;
    VkFenceCreateInfo fci{};
    fci.sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO;
    fci.flags = VK_FENCE_CREATE_SIGNALED_BIT;

    vkCreateSemaphore(m_ctx.device, &sci, nullptr, &m_imageAvailableSem);
    vkCreateSemaphore(m_ctx.device, &sci, nullptr, &m_renderFinishedSem);
    vkCreateFence(m_ctx.device, &fci, nullptr, &m_inFlightFence);
}

void App::allocateCommandBuffers() {
    m_commandBuffers.resize(m_pipeline.framebuffers.size());
    VkCommandBufferAllocateInfo ai{};
    ai.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO;
    ai.commandPool = m_ctx.commandPool;
    ai.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY;
    ai.commandBufferCount = static_cast<uint32_t>(m_commandBuffers.size());
    vkAllocateCommandBuffers(m_ctx.device, &ai, m_commandBuffers.data());
}

// --- Command Buffer Recording ---

void App::recordCommandBuffer(VkCommandBuffer cmd, uint32_t imageIndex) {
    VkCommandBufferBeginInfo beginInfo{};
    beginInfo.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO;
    vkBeginCommandBuffer(cmd, &beginInfo);

    VkClearValue clearValues[2]{};
    clearValues[0].color = {{0.02f, 0.02f, 0.05f, 1.0f}}; // dark background
    clearValues[1].depthStencil = {1.0f, 0};

    VkRenderPassBeginInfo rpBegin{};
    rpBegin.sType = VK_STRUCTURE_TYPE_RENDER_PASS_BEGIN_INFO;
    rpBegin.renderPass = m_pipeline.renderPass;
    rpBegin.framebuffer = m_pipeline.framebuffers[imageIndex];
    rpBegin.renderArea.extent = m_ctx.swapchainExtent;
    rpBegin.clearValueCount = 2;
    rpBegin.pClearValues = clearValues;

    vkCmdBeginRenderPass(cmd, &rpBegin, VK_SUBPASS_CONTENTS_INLINE);
    vkCmdBindPipeline(cmd, VK_PIPELINE_BIND_POINT_GRAPHICS, m_pipeline.pipeline);

    VkBuffer buffers[] = { m_vertexBuffer };
    VkDeviceSize offsets[] = { 0 };
    vkCmdBindVertexBuffers(cmd, 0, 1, buffers, offsets);
    vkCmdBindIndexBuffer(cmd, m_indexBuffer, 0, VK_INDEX_TYPE_UINT32);

    // Compute MVP
    float aspect = static_cast<float>(m_ctx.swapchainExtent.width) /
                   static_cast<float>(m_ctx.swapchainExtent.height);
    glm::mat4 view = m_camera.view_matrix();
    glm::mat4 proj = m_camera.projection_matrix(aspect);
    glm::mat4 model = glm::mat4(1.0f);
    glm::mat4 mvp = proj * view * model;

    PushConstants pc;
    pc.mvp = mvp;
    pc.model = model;
    vkCmdPushConstants(cmd, m_pipeline.pipelineLayout,
                       VK_SHADER_STAGE_VERTEX_BIT, 0, sizeof(PushConstants), &pc);

    vkCmdDrawIndexed(cmd, static_cast<uint32_t>(m_mesh.indices().size()), 1, 0, 0, 0);

    vkCmdEndRenderPass(cmd);
    vkEndCommandBuffer(cmd);
}

// --- Draw Frame ---

void App::drawFrame() {
    vkWaitForFences(m_ctx.device, 1, &m_inFlightFence, VK_TRUE, UINT64_MAX);
    vkResetFences(m_ctx.device, 1, &m_inFlightFence);

    uint32_t imageIndex;
    vkAcquireNextImageKHR(m_ctx.device, m_ctx.swapchain, UINT64_MAX,
                          m_imageAvailableSem, VK_NULL_HANDLE, &imageIndex);

    vkResetCommandBuffer(m_commandBuffers[imageIndex], 0);
    recordCommandBuffer(m_commandBuffers[imageIndex], imageIndex);

    VkPipelineStageFlags waitStage = VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT;
    VkSubmitInfo submit{};
    submit.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
    submit.waitSemaphoreCount = 1;
    submit.pWaitSemaphores = &m_imageAvailableSem;
    submit.pWaitDstStageMask = &waitStage;
    submit.commandBufferCount = 1;
    submit.pCommandBuffers = &m_commandBuffers[imageIndex];
    submit.signalSemaphoreCount = 1;
    submit.pSignalSemaphores = &m_renderFinishedSem;

    vkQueueSubmit(m_ctx.graphicsQueue, 1, &submit, m_inFlightFence);

    VkPresentInfoKHR presentInfo{};
    presentInfo.sType = VK_STRUCTURE_TYPE_PRESENT_INFO_KHR;
    presentInfo.waitSemaphoreCount = 1;
    presentInfo.pWaitSemaphores = &m_renderFinishedSem;
    presentInfo.swapchainCount = 1;
    presentInfo.pSwapchains = &m_ctx.swapchain;
    presentInfo.pImageIndices = &imageIndex;

    vkQueuePresentKHR(m_ctx.presentQueue, &presentInfo);
}

// --- Main Loop ---

void App::main_loop() {
    while (!glfwWindowShouldClose(m_window)) {
        glfwPollEvents();
        drawFrame();
    }
    vkDeviceWaitIdle(m_ctx.device);
}

// --- Cleanup ---

void App::cleanup() {
    if (m_ctx.device == VK_NULL_HANDLE) return;

    vkDeviceWaitIdle(m_ctx.device);

    vkDestroySemaphore(m_ctx.device, m_imageAvailableSem, nullptr);
    vkDestroySemaphore(m_ctx.device, m_renderFinishedSem, nullptr);
    vkDestroyFence(m_ctx.device, m_inFlightFence, nullptr);

    vkDestroyBuffer(m_ctx.device, m_vertexBuffer, nullptr);
    vkFreeMemory(m_ctx.device, m_vertexMemory, nullptr);
    vkDestroyBuffer(m_ctx.device, m_indexBuffer, nullptr);
    vkFreeMemory(m_ctx.device, m_indexMemory, nullptr);

    m_pipeline.cleanup(m_ctx.device);
    m_ctx.cleanup();
    m_ctx.device = VK_NULL_HANDLE; // prevent double cleanup

    if (m_window) {
        glfwDestroyWindow(m_window);
        glfwTerminate();
        m_window = nullptr;
    }
}

// --- Mouse Callbacks ---

void App::mouseButtonCallback(GLFWwindow* w, int button, int action, int /*mods*/) {
    auto* app = static_cast<App*>(glfwGetWindowUserPointer(w));
    if (button == GLFW_MOUSE_BUTTON_LEFT) {
        app->m_mouseDown = (action == GLFW_PRESS);
        glfwGetCursorPos(w, &app->m_lastX, &app->m_lastY);
    }
}

void App::cursorPosCallback(GLFWwindow* w, double x, double y) {
    auto* app = static_cast<App*>(glfwGetWindowUserPointer(w));
    if (app->m_mouseDown) {
        float dx = static_cast<float>(x - app->m_lastX);
        float dy = static_cast<float>(y - app->m_lastY);
        app->m_camera.rotate(dx, dy);
    }
    app->m_lastX = x;
    app->m_lastY = y;
}

void App::scrollCallback(GLFWwindow* w, double /*xoff*/, double yoff) {
    auto* app = static_cast<App*>(glfwGetWindowUserPointer(w));
    app->m_camera.zoom(static_cast<float>(yoff));
}
