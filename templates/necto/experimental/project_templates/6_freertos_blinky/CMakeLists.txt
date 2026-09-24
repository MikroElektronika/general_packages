cmake_minimum_required(VERSION 3.19)

if (${TOOLCHAIN_LANGUAGE} MATCHES "MikroC")
    project(${PROJECT_NAME} LANGUAGES MikroC)
else()
    project(${PROJECT_NAME} LANGUAGES C ASM)
endif()

include(mikroeUtils)

if (${MIKROSDK_TYPE} STREQUAL "legacy")
    legacy_cmake_path()
endif()

set(PROJECT_TYPE "${PROJECT_TYPE_VALUE}" CACHE STRING "" FORCE)

add_executable(${PROJECT_NAME} main.c app/app_freertos.c app/app_freertos.h config/FreeRTOSConfig.h)
target_include_directories(${PROJECT_NAME} PRIVATE app config)
############################ ${PROJECT_NAME} GENERATED CODE START ###########################
############################ ${PROJECT_NAME} GENERATED CODE END ###########################

# FreeRTOS is installed once and shared across projects (see NECTO_FREERTOS_PATH,
# set by NECTO); it is not vendored into the project directory.
#
# FREERTOS_PORT/FREERTOS_HEAP select the kernel's port and heap implementation
# (see NECTO_FREERTOS_PATH/CMakeLists.txt for the full port list). Override
# from the command line, e.g. -DFREERTOS_PORT=GCC_RISC_V, for non-Cortex-M
# targets; the default below only covers the common GCC ARM Cortex-M4F case.
if (NOT DEFINED FREERTOS_PORT)
    set(FREERTOS_PORT GCC_ARM_CM4F CACHE STRING "FreeRTOS port name")
endif()
if (NOT DEFINED FREERTOS_HEAP)
    set(FREERTOS_HEAP 4 CACHE STRING "FreeRTOS heap implementation")
endif()

# Found before freertos_config below, which reads this target's include
# directories out of it - so it has to exist before that point.
find_package(MikroC.Core REQUIRED)

add_library(freertos_config INTERFACE)
# Anything config/FreeRTOSConfig.h includes from the MikroSDK core (e.g.
# core_header.h for FOSC_KHZ_VALUE) has to resolve for every target that
# compiles against it - the FreeRTOS kernel, not just the app - so the core's
# headers belong here alongside config/. Only the include directories are
# taken; linking MikroC.Core itself would also put its static library on the
# kernel's link line, which it has no need of.
target_include_directories(freertos_config SYSTEM INTERFACE
    config
    $<TARGET_PROPERTY:MikroC.Core,INTERFACE_INCLUDE_DIRECTORIES>
)

add_subdirectory(${NECTO_FREERTOS_PATH} freertos_build)

# Provides drv_digital_out.h / digital_out_init() / digital_out_toggle(), used
# by the blinky task.
find_package(MikroSDK.Driver.GPIO.Out REQUIRED)

target_link_libraries(${PROJECT_NAME}
    PUBLIC
        MikroC.Core
        MikroSDK.Driver.GPIO.Out
        freertos_kernel
)

if (${MIKROSDK_TYPE} STREQUAL "legacy")
    find_package(MikroC.System REQUIRED)
    target_link_libraries(${PROJECT_NAME}
        PUBLIC
            MikroC.System
    )
endif()

if(COMPILER_REVISION)
    if(${COMPILER_REVISION} VERSION_GREATER_EQUAL "1.0")
        if(${TOOLCHAIN_LANGUAGE} STREQUAL "GNU")
            if(EXISTS ${CMAKE_CURRENT_SOURCE_DIR}/.meproject)
                fetch_startup_name(${CMAKE_CURRENT_SOURCE_DIR}/.meproject startupName)
                if(startupName)
                    add_startup_all_targets(. ${CMAKE_CURRENT_SOURCE_DIR} ${startupName})
                endif()
                fetch_linker_name(${CMAKE_CURRENT_SOURCE_DIR}/.meproject linkerName)
                if(linkerName)
                    add_ld_all_targets(. ${CMAKE_CURRENT_SOURCE_DIR} ${linkerName})
                endif()
            endif()
        endif()
    endif()
endif()
