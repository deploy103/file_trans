#include <cstdint>
#include <filesystem>
#include <iostream>
#include <string>

namespace fs = std::filesystem;

std::string json_escape(const std::string& value) {
    std::string escaped;
    for (char ch : value) {
        switch (ch) {
            case '\\':
                escaped += "\\\\";
                break;
            case '"':
                escaped += "\\\"";
                break;
            case '\n':
                escaped += "\\n";
                break;
            case '\r':
                escaped += "\\r";
                break;
            case '\t':
                escaped += "\\t";
                break;
            default:
                escaped += ch;
        }
    }
    return escaped;
}

int main(int argc, char** argv) {
    if (argc != 2) {
        std::cerr << "usage: fileprobe-cpp <file>\n";
        return 2;
    }

    fs::path path(argv[1]);
    std::error_code error;
    auto size = fs::file_size(path, error);
    if (error) {
        std::cerr << error.message() << "\n";
        return 1;
    }

    std::cout << "{\"language\":\"cpp\",\"name\":\""
              << json_escape(path.filename().string()) << "\",\"size\":" << size << "}\n";
    return 0;
}
