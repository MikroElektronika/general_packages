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

# NECTO copies the FreeRTOS kernel into the project's freertos/ directory when
# the project is created, so the project builds against its own copy. Projects
# created before that fall back to the shared package (NECTO_FREERTOS_PATH, set
# by NECTO).
#
# FREERTOS_HEAP selects the kernel's heap implementation.
#
# FREERTOS_PORT selects the kernel's port (see freertos/portable/CMakeLists.txt
# for the full list). NECTO picks it from the MCU core and passes it in as
# NECTO_FREERTOS_PORT. Without it, the port is resolved from CORE_NAME and
# TOOLCHAIN_ID by freeRtos_get_port_name() (mikroeUtils), falling back to
# GCC_ARM_CM4F for unknown cores. To use a different port, replace this
# if/else block with your own, e.g.
#     set(FREERTOS_PORT GCC_ARM_CM7)
# Keep it a plain set() (no CACHE): a plain variable takes precedence over any
# cached FREERTOS_PORT, so the edit applies on the next configure.
if (NECTO_FREERTOS_PORT)
    set(FREERTOS_PORT ${NECTO_FREERTOS_PORT})
else()
    freeRtos_get_port_name("${CORE_NAME}" "${TOOLCHAIN_ID}" FREERTOS_PORT)
    if (NOT FREERTOS_PORT)
        set(FREERTOS_PORT GCC_ARM_CM4F)
    endif()
endif()

# Heap implementation and port-specific kernel options (see mikroeUtils).
freeRtos_set_kernel_options("${FREERTOS_PORT}")

# Found before freertos_config below, which reads this target's include
# directories out of it - so it has to exist before that point.
find_package(MikroC.Core REQUIRED)

# freertos_config: config/ plus MikroC.Core's headers, the heap size (from
# MCU_RAM; set FREERTOS_HEAP_SIZE yourself to override) and the small-RAM
# kernel configuration where needed (see mikroeUtils).
freeRtos_add_config_library(${CMAKE_CURRENT_SOURCE_DIR}/config)

if (EXISTS ${CMAKE_CURRENT_SOURCE_DIR}/freertos/CMakeLists.txt)
    add_subdirectory(freertos freertos_build)
else()
    add_subdirectory(${NECTO_FREERTOS_PATH} freertos_build)
endif()

# Provides drv_digital_out.h / digital_out_init() / digital_out_toggle(), used
# by the blinky task.
find_package(MikroSDK.Driver.GPIO.Out REQUIRED)

target_link_libraries(${PROJECT_NAME}
    PUBLIC
        MikroC.Core
        MikroSDK.Driver.GPIO.Out
        freertos_kernel
)

# Board LED names (LED1...) for the blinky task, from mikroSDK's board.h. Not
# every setup ships the board library, so it is optional: without it the task
# falls back to the PC0-PC7 LED bank.
find_package(MikroSDK.Board QUIET)
if (TARGET MikroSDK.Board)
    target_link_libraries(${PROJECT_NAME} PUBLIC MikroSDK.Board)
endif()

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
