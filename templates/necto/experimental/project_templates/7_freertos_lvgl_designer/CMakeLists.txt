cmake_minimum_required(VERSION 3.19)

if (${TOOLCHAIN_LANGUAGE} MATCHES "MikroC")
    project(${PROJECT_NAME} LANGUAGES MikroC)
else()
    project(${PROJECT_NAME} LANGUAGES C ASM)
endif()

include(mikroeUtils)

# NOTE: 1ms_timer/TimerHeaderConfig.cmake is deliberately NOT included here.
# It defines INTERRUPT_ROUTINE as SysTick_Handler on ARM, which the FreeRTOS
# port already owns as the kernel tick source. LVGL's tick and touch polling
# are driven from the LVGL task instead - see app/app_freertos.c.

set(PROJECT_TYPE "${PROJECT_TYPE_VALUE}" CACHE STRING "" FORCE)

# Read back out of the CMake cache by ProjectManager::ensureLvglAssets() to decide which
# LVGL package folder (lvgl_940 / lvgl_835) to copy into the project and add_subdirectory().
# Without it the version falls back to 8.3.5.
set(LVGL_VERSION "9.4.0" CACHE STRING "" FORCE)

add_executable(${PROJECT_NAME}
    driver/display_lvgl.h
    driver/lv_port_indev.h
    driver/display_lvgl.c
    driver/lv_port_indev.c
    app/app_freertos.c
    app/app_freertos.h
    config/FreeRTOSConfig.h
    resource.mres
    main_screen.mscr
    main_screen.c
    main_screen.h
    main.c
)

set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS resource.mres)
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
# MIKROC_ARM_CM4F / GCC_ARM_CM4F for unknown cores. To use a different port,
# replace this if/else block with your own, e.g.
#     set(FREERTOS_PORT GCC_ARM_CM7)
# Keep it a plain set() (no CACHE): a plain variable takes precedence over any
# cached FREERTOS_PORT, so the edit applies on the next configure.
if (NECTO_FREERTOS_PORT)
    set(FREERTOS_PORT ${NECTO_FREERTOS_PORT})
else()
    freeRtos_get_port_name("${CORE_NAME}" "${TOOLCHAIN_ID}" FREERTOS_PORT)
    if (NOT FREERTOS_PORT)
        if (${TOOLCHAIN_LANGUAGE} MATCHES "MikroC")
            set(FREERTOS_PORT MIKROC_ARM_CM4F)
        else()
            set(FREERTOS_PORT GCC_ARM_CM4F)
        endif()
    endif()
endif()

# Heap implementation and port-specific kernel options (see mikroeUtils).
freeRtos_set_kernel_options("${FREERTOS_PORT}")

# Found before freertos_config below, which reads this target's include
# directories out of it - so it has to exist before that point.
find_package(MikroC.Core REQUIRED)

# freertos_config: config/ plus MikroC.Core's headers - used by the FreeRTOS
# kernel and LVGL's OS backend, not just the app - the heap size (from MCU_RAM;
# set FREERTOS_HEAP_SIZE yourself to override) and the small-RAM kernel
# configuration where needed (see mikroeUtils).
freeRtos_add_config_library(${CMAKE_CURRENT_SOURCE_DIR}/config)

if (EXISTS ${CMAKE_CURRENT_SOURCE_DIR}/freertos/CMakeLists.txt)
    add_subdirectory(freertos freertos_build)
else()
    add_subdirectory(${NECTO_FREERTOS_PATH} freertos_build)
endif()

find_package_me(MikroSDK.LVGL.Common REQUIRED)
find_package_me(MikroSDK.GraphicLibrary REQUIRED)
find_package_me(MikroSDK.LVGL)

lvgl_designer_generator(${PROJECT_NAME} resource.mres main_screen.mscr)

target_link_libraries(${PROJECT_NAME}
    PUBLIC
        MikroC.Core
        MikroSDK.LVGL
        MikroSDK.LVGL.Common
        MikroSDK.GraphicLibrary
        freertos_kernel
)

target_include_directories(${PROJECT_NAME}
    PUBLIC
        driver
        app
        config
        .
)

## 180KB Flash / 24KB RAM for LVGL, plus headroom for the FreeRTOS kernel and
## the LVGL task's stack (configTOTAL_HEAP_SIZE in config/FreeRTOSConfig.h).
if((${MCU_FLASH} LESS 204800) OR (${MCU_RAM} LESS 49152)) ## 200KB Flash / 48KB RAM recommended.
    message(FATAL_ERROR ": ${MCU_NAME} does not have recommended memory for this example.")
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

# LVGL's FreeRTOS OS backend (lv_conf.h sets LV_USE_OS to LV_OS_FREERTOS, which
# compiles src/osal/lv_freertos.c in) needs FreeRTOS.h, atomic.h and this
# project's FreeRTOSConfig.h on the lvgl target's include path. The LVGL package
# knows nothing about FreeRTOS, so wire it up from here instead of patching the
# package - which is shared with bare-metal LVGL projects.
#
# freertos_kernel links freertos_kernel_include and freertos_kernel_port_headers
# PUBLIC, and freertos_kernel_include in turn links the freertos_config target
# declared above, so this single link propagates every needed include directory.
#
# Deferred to the end of the configure step because add_subdirectory(lvgl_940) -
# and therefore the lvgl target - is appended to the bottom of this file by NECTO
# when the project is first parsed, i.e. after this point is reached.
cmake_language(DEFER CALL freertos_link_lvgl)
function(freertos_link_lvgl)
    if(TARGET lvgl)
        target_link_libraries(lvgl PUBLIC freertos_kernel)
    endif()
endfunction()
