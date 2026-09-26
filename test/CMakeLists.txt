cmake_minimum_required(VERSION 3.16)
project(ApolloMatrix LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()

# Host-side scenario runner: compiles the ported display logic (matrix_logic.h)
# and writes draw-op traces for rasterize.py. No ESP-IDF, no ESPHome.
add_executable(render_scenarios main.cpp)
target_include_directories(render_scenarios PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})

if(MSVC)
  target_compile_options(render_scenarios PRIVATE /W4)
else()
  target_compile_options(render_scenarios PRIVATE -Wall -Wextra)
endif()

# Link the MinGW runtime statically. Without this the exe resolves libstdc++-6.dll
# / libgcc_s_seh-1.dll from whichever toolchain happens to be first on PATH (e.g.
# MSYS2's msvcrt build), which can refuse to start against a UCRT-compiled object
# - the process dies with exit code 127 and no output.
if(MINGW)
  target_link_options(render_scenarios PRIVATE -static)
endif()
