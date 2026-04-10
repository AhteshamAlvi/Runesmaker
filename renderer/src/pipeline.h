#pragma once

#include "vulkan_context.h"
#include <string>
#include <vector>

class RenderPipeline {
public:
    void init(VulkanContext& ctx, const std::string& shaderDir);
    void cleanup(VkDevice device);

    VkRenderPass renderPass = VK_NULL_HANDLE;
    VkPipelineLayout pipelineLayout = VK_NULL_HANDLE;
    VkPipeline pipeline = VK_NULL_HANDLE;
    std::vector<VkFramebuffer> framebuffers;

private:
    VkShaderModule loadShader(VkDevice device, const std::string& path);
    void createRenderPass(VulkanContext& ctx);
    void createFramebuffers(VulkanContext& ctx);
    void createPipeline(VulkanContext& ctx, const std::string& shaderDir);
};
