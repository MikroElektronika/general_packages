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

# FreeRTOS is installed once and shared across projects (see NECTO_FREERTOS_PATH,
# set by NECTO); it is not vendored into the project directory.
#
# FREERTOS_PORT/FREERTOS_HEAP select the kernel's port and heap implementation
# (see NECTO_FREERTOS_PATH/CMakeLists.txt for the full port list). Override
# from the command line, e.g. -DFREERTOS_PORT=GCC_ARM_CM7, when the default
# below does not match your target.
if (NOT DEFINED FREERTOS_PORT)
    if (${TOOLCHAIN_LANGUAGE} MATCHES "MikroC")
        set(FREERTOS_PORT MIKROC_ARM_CM4F CACHE STRING "FreeRTOS port name")
    else()
        set(FREERTOS_PORT GCC_ARM_CM4F CACHE STRING "FreeRTOS port name")
    endif()
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
# compiles against it - the FreeRTOS kernel and LVGL's OS backend, not just
# the app - so the core's headers belong here alongside config/. Only the
# include directories are taken; linking MikroC.Core itself would also put
# its static library on the kernel's link line, which it has no need of.
target_include_directories(freertos_config SYSTEM INTERFACE
    config
    $<TARGET_PROPERTY:MikroC.Core,INTERFACE_INCLUDE_DIRECTORIES>
)

add_subdirectory(${NECTO_FREERTOS_PATH} freertos_build)

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
