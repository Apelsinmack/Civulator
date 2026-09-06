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

# --- Build provenance (issue #47) -------------------------------------------
# Stamp the pyd with the commit + dirty flag of the tree it was CONFIGURED
# from, so a stale binary after a git catch-up is detectable instead of only
# showing up as a symptom (cf. the breach `breach_physics` stale-pyd GOTCHA).
# Captured at CONFIGURE time only, deliberately -- an incremental build
# without re-running cmake carries a stale stamp; that gap is accepted
# (issue #47) and is exactly what civulator/game/map.py's import-site
# mismatch warning is the detector for. Graceful when git is unavailable:
# commit falls back to "unknown", dirty falls back to unknown (None on the
# Python side, via CIVULATOR_GIT_DIRTY_KNOWN being left undefined).
find_package(Git QUIET)

set(CIVULATOR_GIT_COMMIT "unknown")
set(CIVULATOR_GIT_DIRTY_DEFINED FALSE)
set(CIVULATOR_GIT_DIRTY 0)

if(GIT_FOUND)
    execute_process(
        COMMAND ${GIT_EXECUTABLE} rev-parse HEAD
        WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
        OUTPUT_VARIABLE _civulator_git_commit_out
        RESULT_VARIABLE _civulator_git_commit_result
        OUTPUT_STRIP_TRAILING_WHITESPACE
        ERROR_QUIET
    )
    if(_civulator_git_commit_result EQUAL 0 AND NOT "${_civulator_git_commit_out}" STREQUAL "")
        set(CIVULATOR_GIT_COMMIT "${_civulator_git_commit_out}")

        execute_process(
            COMMAND ${GIT_EXECUTABLE} status --porcelain
            WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
            OUTPUT_VARIABLE _civulator_git_status_out
            RESULT_VARIABLE _civulator_git_status_result
            OUTPUT_STRIP_TRAILING_WHITESPACE
            ERROR_QUIET
        )
        if(_civulator_git_status_result EQUAL 0)
            set(CIVULATOR_GIT_DIRTY_DEFINED TRUE)
            if("${_civulator_git_status_out}" STREQUAL "")
                set(CIVULATOR_GIT_DIRTY 0)
            else()
                set(CIVULATOR_GIT_DIRTY 1)
            endif()
        endif()
    endif()
endif()

string(TIMESTAMP CIVULATOR_BUILD_DATE "%Y-%m-%dT%H:%M:%SZ" UTC)

target_compile_definitions(civulator_core PRIVATE
    CIVULATOR_GIT_COMMIT="${CIVULATOR_GIT_COMMIT}"
    CIVULATOR_BUILD_DATE="${CIVULATOR_BUILD_DATE}"
)
if(CIVULATOR_GIT_DIRTY_DEFINED)
    target_compile_definitions(civulator_core PRIVATE
        CIVULATOR_GIT_DIRTY_KNOWN=1
        CIVULATOR_GIT_DIRTY=${CIVULATOR_GIT_DIRTY}
    )
endif()
