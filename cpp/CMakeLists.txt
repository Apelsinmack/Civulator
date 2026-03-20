cmake_minimum_required(VERSION 3.18)
project(civulator_core LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Release by default
if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
    set(CMAKE_BUILD_TYPE Release CACHE STRING "" FORCE)
endif()

# Compiler flags (same as Breach)
if(MSVC)
    add_compile_options(/O2 /fp:fast /arch:AVX2 /W3)
else()
    add_compile_options(-O3 -ffast-math -mavx2 -Wall)
endif()

find_package(pybind11 REQUIRED)

pybind11_add_module(civulator_core
    src/hex_astar.cpp
    src/bindings.cpp
)

target_include_directories(civulator_core PRIVATE src)
