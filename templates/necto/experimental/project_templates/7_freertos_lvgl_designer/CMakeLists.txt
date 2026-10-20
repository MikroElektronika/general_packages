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
# NECTO_FREERTOS_PORT; the fallback below is only used outside NECTO. To use a
# different port, replace this if/else block with your own, e.g.
#     set(FREERTOS_PORT GCC_ARM_CM7)
# Keep it a plain set() (no CACHE): a plain variable takes precedence over any
# cached FREERTOS_PORT, so the edit applies on the next configure.
if (NECTO_FREERTOS_PORT)
    set(FREERTOS_PORT ${NECTO_FREERTOS_PORT})
else()
    if (${TOOLCHAIN_LANGUAGE} MATCHES "MikroC")
        set(FREERTOS_PORT MIKROC_ARM_CM4F)
    else()
        set(FREERTOS_PORT GCC_ARM_CM4F)
    endif()
endif()
if (NOT DEFINED FREERTOS_HEAP)
    set(FREERTOS_HEAP 4 CACHE STRING "FreeRTOS heap implementation")
endif()
# The generic RISC-V port refuses to configure without a chip extension. The
# GD32VF103 (Nuclei Bumblebee) has a memory-mapped mtime/mtimecmp timer and no
# extra registers to save, which is what RISCV_MTIME_CLINT_no_extensions covers.
if (FREERTOS_PORT STREQUAL "GCC_RISC_V_GENERIC" AND NOT DEFINED FREERTOS_RISCV_EXTENSION)
    set(FREERTOS_RISCV_EXTENSION RISCV_MTIME_CLINT_no_extensions CACHE STRING "FreeRTOS RISC-V chip extension")
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
# FreeRTOSConfig.h takes the core clock from MikroC.Core's OSC_KHZ on XC32,
# where it cannot include core_header.h. Only OSC_KHZ is forwarded: the core's
# other definitions include __LANGUAGE_C__, which would make the PIC32 port's
# assembly sources pull in C declarations from <xc.h>.
target_compile_definitions(freertos_config INTERFACE
    $<FILTER:$<TARGET_PROPERTY:MikroC.Core,INTERFACE_COMPILE_DEFINITIONS>,INCLUDE,^OSC_KHZ=>
)

# FreeRTOS heap size for config/FreeRTOSConfig.h: half of the MCU's RAM
# (MCU_RAM, in bytes, set by NECTO), capped at 32 KB. The rest is left for the
# startup stack, .data/.bss and the application. Parts range from 16 KB of RAM
# (e.g. RA2E1) to hundreds of KB, so a fixed size either overflows the small
# ones or wastes the large ones. Set FREERTOS_HEAP_SIZE yourself to override.
#
# Kinetis (MK...) splits its SRAM into a lower and an upper block, and the
# linker scripts put .data/.bss - and with them the heap array - in the lower
# one only: half of the RAM on K60 (32 + 32 KB), a quarter on K64 (64 + 192 KB)
# and on the KL parts. MCU_RAM is the total, so those parts get an eighth of
# it, capped at 16 KB, which leaves the lower block room for the rest of .bss.
set(_freertos_kinetis FALSE)
if (MCU_NAME MATCHES "^MK")
    set(_freertos_kinetis TRUE)
endif()
if (NOT DEFINED FREERTOS_HEAP_SIZE)
    if (_freertos_kinetis)
        set(FREERTOS_HEAP_SIZE 16384)
        set(_freertos_ram_divisor 8)
    else()
        set(FREERTOS_HEAP_SIZE 32768)
        set(_freertos_ram_divisor 2)
    endif()
    if (MCU_RAM)
        math(EXPR _freertos_ram_share "${MCU_RAM} / ${_freertos_ram_divisor}")
        if (_freertos_ram_share LESS FREERTOS_HEAP_SIZE)
            set(FREERTOS_HEAP_SIZE ${_freertos_ram_share})
        endif()
    endif()
endif()
target_compile_definitions(freertos_config INTERFACE FREERTOS_HEAP_SIZE=${FREERTOS_HEAP_SIZE})
# Parts with less than 16 KB of RAM (NECTO only offers FreeRTOS from 8 KB up)
# get a slimmed-down kernel configuration - smaller task stacks, no timer task,
# no queue registry - see FREERTOS_SMALL_RAM in config/FreeRTOSConfig.h. On
# Kinetis that includes 16 KB parts, whose smaller heap share would not hold
# the full configuration's task stacks.
if (MCU_RAM AND (MCU_RAM LESS 16384 OR (_freertos_kinetis AND MCU_RAM LESS_EQUAL 16384)))
    target_compile_definitions(freertos_config INTERFACE FREERTOS_SMALL_RAM=1)
endif()

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
