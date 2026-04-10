#pragma once

#define GLFW_INCLUDE_VULKAN
#include <GLFW/glfw3.h>
#include <string>

#include "vulkan_context.h"
#include "pipeline.h"
#include "mesh.h"
#include "camera.h"

class App {
public:
    App(const std::string& rune_path, const std::string& export_path = "");
    ~App();

    void run();

private:
    std::string m_rune_path;
    std::string m_export_path;

    GLFWwindow* m_window = nullptr;
    VulkanContext m_ctx;
    RenderPipeline m_pipeline;
    RuneMesh m_mesh;
    Camera m_camera;

    // GPU buffers
    VkBuffer m_vertexBuffer = VK_NULL_HANDLE;
    VkDeviceMemory m_vertexMemory = VK_NULL_HANDLE;
    VkBuffer m_indexBuffer = VK_NULL_HANDLE;
    VkDeviceMemory m_indexMemory = VK_NULL_HANDLE;

    // Command buffers & sync
    std::vector<VkCommandBuffer> m_commandBuffers;
    VkSemaphore m_imageAvailableSem = VK_NULL_HANDLE;
    VkSemaphore m_renderFinishedSem = VK_NULL_HANDLE;
    VkFence m_inFlightFence = VK_NULL_HANDLE;

    // Mouse state for orbit camera
    bool m_mouseDown = false;
    double m_lastX = 0, m_lastY = 0;

    void init();
    void createBuffers();
    void createSyncObjects();
    void allocateCommandBuffers();
    void recordCommandBuffer(VkCommandBuffer cmd, uint32_t imageIndex);
    void drawFrame();
    void main_loop();
    void cleanup();

    VkBuffer createBuffer(VkDeviceSize size, VkBufferUsageFlags usage,
                          VkMemoryPropertyFlags properties, VkDeviceMemory& memory);

    // GLFW callbacks
    static void mouseButtonCallback(GLFWwindow* w, int button, int action, int mods);
    static void cursorPosCallback(GLFWwindow* w, double x, double y);
    static void scrollCallback(GLFWwindow* w, double xoff, double yoff);
};
