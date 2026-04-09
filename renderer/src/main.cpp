#include "app.h"
#include <iostream>

int main(int argc, char* argv[]) {
    if (argc < 2) {
        std::cerr << "Usage: rune_renderer <rune.json> [--export output.png]\n";
        return 1;
    }

    std::string rune_path = argv[1];
    std::string export_path;

    for (int i = 2; i < argc; ++i) {
        if (std::string(argv[i]) == "--export" && i + 1 < argc) {
            export_path = argv[++i];
        }
    }

    try {
        App app(rune_path, export_path);
        app.run();
    } catch (const std::exception& e) {
        std::cerr << "Error: " << e.what() << "\n";
        return 1;
    }

    return 0;
}
