cmake_minimum_required(VERSION 3.16)

set(CMAKE_ASC_ARCHITECTURES "dav-2201" CACHE STRING "dav-2201 (910B) or dav-3510 (950)")
set_property(CACHE CMAKE_ASC_ARCHITECTURES PROPERTY STRINGS dav-2201 dav-3510)

if(NOT CMAKE_ASC_ARCHITECTURES MATCHES "^(dav-2201|dav-3510)$")
    message(FATAL_ERROR "CMAKE_ASC_ARCHITECTURES must be dav-2201 or dav-3510")
endif()

option(ASCENDC_SANITIZER "Instrument an NPU build for msSanitizer" OFF)
option(ASCENDC_DEBUG_INFO "Emit source mapping without disabling optimization" ON)
if(ASCENDC_SANITIZER AND NOT CMAKE_ASC_RUN_MODE STREQUAL "npu")
    message(FATAL_ERROR "ASCENDC_SANITIZER requires CMAKE_ASC_RUN_MODE=npu")
endif()
if(ASCENDC_SANITIZER AND CMAKE_BUILD_TYPE STREQUAL "Debug")
    message(FATAL_ERROR "msSanitizer instrumentation must not be combined with Debug/-O0")
endif()

find_package(ASC REQUIRED)
project(ascendc_low_level_lab LANGUAGES ASC CXX)

set(CMAKE_ASC_STANDARD 17)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

foreach(target IN ITEMS vector_add direct_mmad add_mmad_add)
    add_executable(${target} apps/${target}.asc)
    target_include_directories(${target} PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/include)
    target_compile_options(${target} PRIVATE
        $<$<COMPILE_LANGUAGE:ASC>:--npu-arch=${CMAKE_ASC_ARCHITECTURES}>
    )
    if(ASCENDC_DEBUG_INFO)
        target_compile_options(${target} PRIVATE $<$<COMPILE_LANGUAGE:ASC>:-g>)
    endif()
    if(ASCENDC_SANITIZER)
        target_compile_options(${target} PRIVATE
            $<$<COMPILE_LANGUAGE:ASC>:-g>
            $<$<COMPILE_LANGUAGE:ASC>:--sanitizer>
        )
    endif()
endforeach()

# SIMT (CUDA-like) is only available on dav-3510 (Ascend 950) and has no CPU twin-debug mode.
if(CMAKE_ASC_ARCHITECTURES STREQUAL "dav-3510")
    add_executable(simt_add apps/simt_add.asc)
    target_compile_options(simt_add PRIVATE
        $<$<COMPILE_LANGUAGE:ASC>:--npu-arch=${CMAKE_ASC_ARCHITECTURES}>
        $<$<COMPILE_LANGUAGE:ASC>:--enable-simt>
    )
    if(ASCENDC_DEBUG_INFO)
        target_compile_options(simt_add PRIVATE $<$<COMPILE_LANGUAGE:ASC>:-g>)
    endif()
endif()

include(CTest)
if(BUILD_TESTING)
    add_test(NAME vector_add COMMAND vector_add)
    add_test(NAME direct_mmad COMMAND direct_mmad)
    add_test(NAME add_mmad_add COMMAND add_mmad_add)
    if(CMAKE_ASC_ARCHITECTURES STREQUAL "dav-3510")
        add_test(NAME simt_add COMMAND simt_add)
    endif()
endif()
