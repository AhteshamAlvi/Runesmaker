#include "app.h"
#include <iostream>

// TODO: Integrate vulkan_context, pipeline, mesh, camera, exporter

App::App(const std::string& rune_path, const std::string& export_path)
    : m_rune_path(rune_path), m_export_path(export_path) {}

App::~App() {
    cleanup();
}

void App::run() {
    init();
    main_loop();
    cleanup();
}

void App::init() {
    std::cout << "Loading rune from: " << m_rune_path << "\n";
    // TODO: Initialize GLFW window, Vulkan context, load rune mesh
}

void App::main_loop() {
    // TODO: Render loop with orbit camera
    std::cout << "Render loop placeholder\n";
}

void App::cleanup() {
    // TODO: Vulkan cleanup
}
