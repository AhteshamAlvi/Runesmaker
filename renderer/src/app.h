#pragma once

#include <string>

class App {
public:
    App(const std::string& rune_path, const std::string& export_path = "");
    ~App();

    void run();

private:
    std::string m_rune_path;
    std::string m_export_path;

    void init();
    void main_loop();
    void cleanup();
};
