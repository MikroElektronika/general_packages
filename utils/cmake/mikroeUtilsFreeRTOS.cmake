#############################################################################
## Function to resolve the FreeRTOS port name for the given core and toolchain.
## Sets outVar in the caller's scope to the port name, or to an empty string
## if the core is not supported.
#############################################################################
function(freeRtos_get_port_name coreName toolchainUuid outVar)
    set(portName "")

    # Cortex-M0+ is ARMv6-M like the M0; FreeRTOS has no separate M0+ port.
    if(coreName STREQUAL "M0" OR coreName STREQUAL "M0+")
        set(portName "GCC_ARM_CM0")
    # FreeRTOS has no Cortex-M4 port without an FPU; the CM3 port is the one to use.
    elseif(coreName STREQUAL "M3" OR coreName STREQUAL "M4" OR coreName STREQUAL "M4DSP")
        set(portName "GCC_ARM_CM3")
    elseif(coreName STREQUAL "M4EF")
        string(FIND "${toolchainUuid}" "mikroc" mikrocIndex)
        if(mikrocIndex GREATER -1)
            set(portName "MIKROC_ARM_CM4F")
        else()
            set(portName "GCC_ARM_CM4F")
        endif()
    elseif(coreName STREQUAL "M7")
        set(portName "GCC_ARM_CM7")
    # ARMv8-M cores (e.g. Renesas RA4M3, RA8). NECTO projects do not partition TrustZone,
    # so the no-TrustZone variants are the ones to use.
    elseif(coreName STREQUAL "M23")
        set(portName "GCC_ARM_CM23_NTZ_NONSECURE")
    elseif(coreName STREQUAL "M33EF")
        set(portName "GCC_ARM_CM33_NTZ_NONSECURE")
    elseif(coreName STREQUAL "M85")
        set(portName "GCC_ARM_CM85_NTZ_NONSECURE")
    elseif(coreName STREQUAL "MIPS32")
        set(portName "MPLAB_PIC32MX")
    elseif(coreName STREQUAL "MICROAPTIV" OR coreName STREQUAL "MICROAPTIV_FP")
        set(portName "MPLAB_PIC32MZ")
    elseif(coreName STREQUAL "RISCV")
        set(portName "GCC_RISC_V_GENERIC")
    endif()

    set(${outVar} "${portName}" PARENT_SCOPE)
endfunction()

#############################################################################
## Function to set the FreeRTOS kernel options that depend on the port.
## Must be called before the kernel is added (add_subdirectory), which reads
## them. Options the user already defined are left untouched.
#############################################################################
function(freeRtos_set_kernel_options port)
    if (NOT DEFINED FREERTOS_HEAP)
        set(FREERTOS_HEAP 4 CACHE STRING "FreeRTOS heap implementation")
    endif()
    # The generic RISC-V port refuses to configure without a chip extension. The
    # GD32VF103 (Nuclei Bumblebee) has a memory-mapped mtime/mtimecmp timer and no
    # extra registers to save, which is what RISCV_MTIME_CLINT_no_extensions covers.
    if (port STREQUAL "GCC_RISC_V_GENERIC" AND NOT DEFINED FREERTOS_RISCV_EXTENSION)
        set(FREERTOS_RISCV_EXTENSION RISCV_MTIME_CLINT_no_extensions CACHE STRING "FreeRTOS RISC-V chip extension")
    endif()
endfunction()

#############################################################################
## Function to create the freertos_config interface library the FreeRTOS
## kernel compiles against. configDir is the directory holding
## FreeRTOSConfig.h. The MikroC.Core target must already exist (find_package),
## since its include directories and definitions are read from it.
## Sets FREERTOS_HEAP_SIZE in the caller's scope to the heap size used.
#############################################################################
function(freeRtos_add_config_library configDir)
    if (NOT TARGET MikroC.Core)
        message(FATAL_ERROR "freeRtos_add_config_library: MikroC.Core not found, call find_package(MikroC.Core REQUIRED) first.")
    endif()

    add_library(freertos_config INTERFACE)
    # Anything FreeRTOSConfig.h includes from the MikroSDK core (e.g.
    # core_header.h for FOSC_KHZ_VALUE) has to resolve for every target that
    # compiles against it - the FreeRTOS kernel, not just the app - so the core's
    # headers belong here alongside configDir. Only the include directories are
    # taken; linking MikroC.Core itself would also put its static library on the
    # kernel's link line, which it has no need of.
    target_include_directories(freertos_config SYSTEM INTERFACE
        ${configDir}
        $<TARGET_PROPERTY:MikroC.Core,INTERFACE_INCLUDE_DIRECTORIES>
    )
    # FreeRTOSConfig.h takes the core clock from MikroC.Core's OSC_KHZ on XC32,
    # where it cannot include core_header.h. Only OSC_KHZ is forwarded: the core's
    # other definitions include __LANGUAGE_C__, which would make the PIC32 port's
    # assembly sources pull in C declarations from <xc.h>.
    target_compile_definitions(freertos_config INTERFACE
        $<FILTER:$<TARGET_PROPERTY:MikroC.Core,INTERFACE_COMPILE_DEFINITIONS>,INCLUDE,^OSC_KHZ=>
    )

    # FreeRTOS heap size for FreeRTOSConfig.h: half of the MCU's RAM
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
    set(kinetis FALSE)
    if (MCU_NAME MATCHES "^MK")
        set(kinetis TRUE)
    endif()
    if (NOT DEFINED FREERTOS_HEAP_SIZE)
        if (kinetis)
            set(FREERTOS_HEAP_SIZE 16384)
            set(ramDivisor 8)
        else()
            set(FREERTOS_HEAP_SIZE 32768)
            set(ramDivisor 2)
        endif()
        if (MCU_RAM)
            math(EXPR ramShare "${MCU_RAM} / ${ramDivisor}")
            if (ramShare LESS FREERTOS_HEAP_SIZE)
                set(FREERTOS_HEAP_SIZE ${ramShare})
            endif()
        endif()
    endif()
    target_compile_definitions(freertos_config INTERFACE FREERTOS_HEAP_SIZE=${FREERTOS_HEAP_SIZE})
    # Parts with less than 16 KB of RAM (NECTO only offers FreeRTOS from 8 KB up)
    # get a slimmed-down kernel configuration - smaller task stacks, no timer task,
    # no queue registry - see FREERTOS_SMALL_RAM in FreeRTOSConfig.h. On
    # Kinetis that includes 16 KB parts, whose smaller heap share would not hold
    # the full configuration's task stacks.
    if (MCU_RAM AND (MCU_RAM LESS 16384 OR (kinetis AND MCU_RAM LESS_EQUAL 16384)))
        target_compile_definitions(freertos_config INTERFACE FREERTOS_SMALL_RAM=1)
    endif()

    set(FREERTOS_HEAP_SIZE ${FREERTOS_HEAP_SIZE} PARENT_SCOPE)
endfunction()
