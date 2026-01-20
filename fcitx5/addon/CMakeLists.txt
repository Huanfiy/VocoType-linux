cmake_minimum_required(VERSION 3.10)
project(fcitx5-vocotype VERSION 2.1.1)

# C++20 标准（Fcitx5 的日志宏需要）
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# 查找依赖
find_package(Fcitx5Core REQUIRED)
# 尝试查找 nlohmann_json，如果失败则尝试其他方法
find_package(nlohmann_json 3.2.0 QUIET)
if(NOT nlohmann_json_FOUND)
    # 尝试不指定版本
    find_package(nlohmann_json QUIET)
endif()

# 源文件
set(SOURCES
    vocotype.cpp
    ipc_client.cpp
)

# 创建共享库（Fcitx5 插件）
add_library(vocotype MODULE ${SOURCES})

# 链接库
target_link_libraries(vocotype
    Fcitx5::Core
)

# 如果找到 nlohmann_json，链接它
if(nlohmann_json_FOUND)
    target_link_libraries(vocotype nlohmann_json::nlohmann_json)
else()
    # 否则只添加头文件搜索路径（header-only 库）
    target_include_directories(vocotype PRIVATE /usr/include)
endif()

# 设置输出名称
set_target_properties(vocotype PROPERTIES
    PREFIX ""  # 不添加 lib 前缀
)

# 安装
install(TARGETS vocotype
    LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}/fcitx5
)

# 显示配置信息
message(STATUS "=== VoCoType Fcitx5 Addon Configuration ===")
message(STATUS "Build type: ${CMAKE_BUILD_TYPE}")
message(STATUS "Install prefix: ${CMAKE_INSTALL_PREFIX}")
message(STATUS "Library dir: ${CMAKE_INSTALL_LIBDIR}")
message(STATUS "Fcitx5 Core: ${Fcitx5Core_VERSION}")
message(STATUS "nlohmann_json: Found")
