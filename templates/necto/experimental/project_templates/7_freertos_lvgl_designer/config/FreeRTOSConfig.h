/**
 * @file FreeRTOSConfig.h
 * @brief FreeRTOS kernel configuration for the ${PROJECT_NAME} application.
 *
 * Starter configuration for a single-core Cortex-M target running an LVGL GUI.
 * Adjust to match your MCU's clock and memory budget.
 *
 * configTICK_RATE_HZ must stay at 1000 unless you also adjust the tick-to-
 * milliseconds conversion feeding lv_tick_inc() in app/app_freertos.c.
 */

/* Provides FOSC_KHZ_VALUE (the MCU's configured core clock) for
 * configCPU_CLOCK_HZ below. Deliberately outside the include guard's body so
 * it is pulled in before the first use.
 *
 * Not on XC32: there core_header.h also carries the setup's #pragma config
 * words, which must be emitted exactly once per image - including it from
 * every kernel source fails the link with "multiple definition of
 * __config_...". The clock comes from OSC_KHZ instead (see below). */
#if !defined( __XC32__ )
#include "core_header.h"
#endif

#ifndef FREERTOS_CONFIG_H
#define FREERTOS_CONFIG_H

#define configUSE_PREEMPTION                   1
#define configUSE_IDLE_HOOK                    0
/* Drives the run-time-stats counter in app_freertos.c - see the
 * configGENERATE_RUN_TIME_STATS block below. */
#define configUSE_TICK_HOOK                    1
/* Core clock, taken from the setup's core_header.h (included above) so it
 * tracks whatever clock NECTO configured for the selected MCU instead of
 * needing a hand-edit per target. A mismatch here does not stop the
 * scheduler, but every vTaskDelay()/timeout is off by the ratio between this
 * value and the real clock (e.g. 72 MHz here while the MCU runs at 168 MHz
 * stretches every delay by ~2.3x).
 *
 * NECTO does not fill in a real frequency for every MCU - some setups leave
 * FOSC_KHZ_VALUE at its 1000 (1 MHz) placeholder, and the MCU then runs at
 * its reset clock instead (e.g. 16 MHz HSI on STM32G0, ~2.1 MHz MSI on
 * STM32L0). The project still builds, but a warning flags it, since every
 * delay is then off by that ratio: set the real clock in the setup, or
 * replace the whole block with a literal, e.g.
 * #define configCPU_CLOCK_HZ ( 16000000UL ). A missing or zero clock is an
 * error - the tick timer cannot be programmed from it. */
#if defined( __XC32__ )
/* MikroC.Core's OSC_KHZ compile definition, forwarded to the kernel through
 * freertos_config in CMakeLists.txt. Same value as FOSC_KHZ_VALUE. */
#if !defined( OSC_KHZ )
    #error "OSC_KHZ not defined - forward it to freertos_config, or set configCPU_CLOCK_HZ to a literal frequency."
#elif ( OSC_KHZ ) == 0
    #error "OSC_KHZ is 0 - set the MCU clock in the setup, or set configCPU_CLOCK_HZ to a literal frequency."
#elif ( OSC_KHZ ) <= 1000
    #warning "OSC_KHZ looks like NECTO's 1 MHz placeholder, not the real core clock - FreeRTOS delays will be off unless the MCU really runs at 1 MHz. Set the clock in the setup, or set configCPU_CLOCK_HZ to a literal frequency."
#endif
#define configCPU_CLOCK_HZ                     ( ( OSC_KHZ ) * 1000UL )
#else
#if !defined( FOSC_KHZ_VALUE )
    #error "FOSC_KHZ_VALUE not defined - include core_header.h, or set configCPU_CLOCK_HZ to a literal frequency."
#elif FOSC_KHZ_VALUE == 0
    #error "FOSC_KHZ_VALUE is 0 - set the MCU clock in the setup, or set configCPU_CLOCK_HZ to a literal frequency."
#elif FOSC_KHZ_VALUE <= 1000
    #warning "FOSC_KHZ_VALUE looks like NECTO's 1 MHz placeholder, not the real core clock - FreeRTOS delays will be off unless the MCU really runs at 1 MHz. Set the clock in the setup, or set configCPU_CLOCK_HZ to a literal frequency."
#endif
#if defined( __riscv )
/* The RISC-V port only uses configCPU_CLOCK_HZ as the rate of the mtime
 * counter it programs mtimecmp from, not the core clock. On the GD32VF103 that
 * counter runs at a quarter of the core clock. */
#define configCPU_CLOCK_HZ                     ( FOSC_KHZ_VALUE * 1000UL / 4UL )
#else
#define configCPU_CLOCK_HZ                     ( FOSC_KHZ_VALUE * 1000UL )
#endif
#endif
#define configTICK_RATE_HZ                     ( ( TickType_t ) 1000 )
#define configMAX_PRIORITIES                   ( 5 )
/* Stack depth in words of the idle task and of tasks created with it. Parts
 * with less than 16 KB of RAM (FREERTOS_SMALL_RAM, set by CMakeLists.txt) get
 * half, so a few tasks still fit their heap. */
#if defined( FREERTOS_SMALL_RAM )
#define configMINIMAL_STACK_SIZE                ( ( unsigned short ) 128 )
#else
#define configMINIMAL_STACK_SIZE                ( ( unsigned short ) 256 )
#endif
/* The LVGL task's stack comes out of this heap. LVGL's own draw buffers and
 * object allocations do NOT - those use LVGL's allocator (LV_MEM_SIZE in the
 * LVGL package's lv_conf.h), so budget both. Raise this if xTaskCreate() for
 * the LVGL task returns pdFAIL. */
/* CMakeLists.txt sizes it to half of the MCU's RAM, capped at 32 KB
 * (FREERTOS_HEAP_SIZE); set FREERTOS_HEAP_SIZE there to change it. */
#if defined( FREERTOS_HEAP_SIZE )
#define configTOTAL_HEAP_SIZE                  ( ( size_t ) ( FREERTOS_HEAP_SIZE ) )
#else
#define configTOTAL_HEAP_SIZE                  ( ( size_t ) ( 32 * 1024 ) )
#endif
#define configMAX_TASK_NAME_LEN                 16
#define configUSE_TRACE_FACILITY                1
#define configUSE_16_BIT_TICKS                  0
#define configIDLE_SHOULD_YIELD                 1
#define configUSE_MUTEXES                       1
#if defined( FREERTOS_SMALL_RAM )
#define configQUEUE_REGISTRY_SIZE               0
#else
#define configQUEUE_REGISTRY_SIZE               8
#endif
#define configCHECK_FOR_STACK_OVERFLOW          2
#define configUSE_RECURSIVE_MUTEXES             1
#define configUSE_MALLOC_FAILED_HOOK            0
#define configUSE_COUNTING_SEMAPHORES           1

/* Co-routine definitions. */
#define configUSE_CO_ROUTINES                   0
#define configMAX_CO_ROUTINE_PRIORITIES         ( 2 )

/* Software timer definitions. */
/* No timer service task on small-RAM parts: it costs a task stack and a
 * command queue the application may never use. */
#if defined( FREERTOS_SMALL_RAM )
#define configUSE_TIMERS                        0
#else
#define configUSE_TIMERS                        1
#endif
#define configTIMER_TASK_PRIORITY               ( configMAX_PRIORITIES - 1 )
#define configTIMER_QUEUE_LENGTH                 10
#define configTIMER_TASK_STACK_DEPTH             configMINIMAL_STACK_SIZE

/* Optional functions. */
#define INCLUDE_vTaskPrioritySet                1
#define INCLUDE_uxTaskPriorityGet               1
#define INCLUDE_vTaskDelete                     1
#define INCLUDE_vTaskSuspend                    1
#define INCLUDE_vTaskDelayUntil                 1
#define INCLUDE_vTaskDelay                      1
#define INCLUDE_uxTaskGetStackHighWaterMark      1
#define INCLUDE_xTaskGetSchedulerState           1

#if defined( __XC32__ )
/* PIC32 (MIPS) specific definitions, used by the MPLAB_PIC32MX/MZ ports.
 *
 * Priorities are plain IPL levels, not the shifted NVIC values Cortex-M uses:
 * the kernel's tick and yield interrupts run at IPL1, and only interrupts at
 * or below configMAX_SYSCALL_INTERRUPT_PRIORITY may call "FromISR" APIs. */
#define configKERNEL_INTERRUPT_PRIORITY         0x01
#define configMAX_SYSCALL_INTERRUPT_PRIORITY    0x03
/* MIPS has a single stack pointer, so the port moves interrupts onto a stack
 * of its own (xISRStack in port.c) instead of the startup file's main stack
 * that Cortex-M uses. Size in words. */
#define configISR_STACK_SIZE                    ( 400 )
/* The kernel tick comes from Timer1, the port's default (it then also clears
 * the Timer1 flag itself - defining configTICK_INTERRUPT_VECTOR here would
 * require configCLEAR_TICK_TIMER_INTERRUPT() as well).
 *
 * Timer1's input clock is read from the bus divider at scheduler start rather
 * than assumed: it is only expanded inside the port's
 * vApplicationSetupTickTimerInterrupt(), so it follows whatever divider the
 * application or HAL set before vTaskStartScheduler(). Do not use it in #if or
 * from assembly - it is a run-time expression. */
#if defined( __PIC32MZ__ )
    /* Timer1 runs on PBCLK3. */
    #define configPERIPHERAL_CLOCK_HZ           ( configCPU_CLOCK_HZ / ( PB3DIVbits.PBDIV + 1UL ) )
#else
    /* PIC32MX: one peripheral bus, divided by 1, 2, 4 or 8. */
    #define configPERIPHERAL_CLOCK_HZ           ( configCPU_CLOCK_HZ >> OSCCONbits.PBDIV )
#endif
/* Parts with a hardware FPU (e.g. PIC32MZ EF) save its registers per task;
 * without this, tasks that use floating point corrupt each other's FPU state.
 *
 * Note: the MPLAB (MDB) simulator mis-runs the port's yield handler with this
 * enabled (it skips the "addiu sp" in the delay slot of a taken branch), so a
 * simulator run trips the stack-overflow hook on the first context switch.
 * Real hardware executes the delay slot and is unaffected. */
#if defined( __mips_hard_float ) && ( __mips_hard_float == 1 )
    #define configUSE_TASK_FPU_SUPPORT          1
#endif
#elif defined( __riscv )
/* RISC-V specific definitions, used by the GCC_RISC_V_GENERIC port with the
 * RISCV_MTIME_CLINT_no_extensions chip extension (see CMakeLists.txt).
 *
 * GD32VF103 (Nuclei Bumblebee): the core timer's mtime sits at 0xD1000000 and
 * mtimecmp right after it. The kernel's trap handler is installed on mtvec by
 * app_freertos.c. */
#define configMTIME_BASE_ADDRESS                ( 0xD1000000UL )
#define configMTIMECMP_BASE_ADDRESS             ( 0xD1000008UL )
/* Interrupts run on a stack of their own instead of the interrupted task's.
 * Size in words. */
#define configISR_STACK_SIZE_WORDS              ( 256 )
#else
/* Cortex-M specific definitions. */
#define configPRIO_BITS                         4
#define configLIBRARY_LOWEST_INTERRUPT_PRIORITY  15
#define configLIBRARY_MAX_SYSCALL_INTERRUPT_PRIORITY  5
#define configKERNEL_INTERRUPT_PRIORITY \
    ( configLIBRARY_LOWEST_INTERRUPT_PRIORITY << ( 8 - configPRIO_BITS ) )
#define configMAX_SYSCALL_INTERRUPT_PRIORITY \
    ( configLIBRARY_MAX_SYSCALL_INTERRUPT_PRIORITY << ( 8 - configPRIO_BITS ) )

/* The ARMv6-M port (GCC_ARM_CM0, Cortex-M0/M0+) refuses to build unless the
 * MPU setting is given. The template does not use the MPU. */
#if defined( __ARM_ARCH_6M__ )
#define configENABLE_MPU                        0
#endif

/* ARMv8-M ports (GCC_ARM_CM23/CM33/CM55/CM85_NTZ_NONSECURE, e.g. Renesas RA4M3
 * and RA8) refuse to build unless these are set. NECTO projects do not
 * partition TrustZone, so the whole application - FreeRTOS included - runs in
 * the Secure state the core resets into: TrustZone support stays off and
 * configRUN_FREERTOS_SECURE_ONLY makes the port return to Secure-state task
 * stacks. Without it the first task switch faults. */
#if defined( __ARM_ARCH_8M_MAIN__ ) || defined( __ARM_ARCH_8_1M_MAIN__ ) || \
    defined( __ARM_ARCH_8M_BASE__ )
#if defined( __ARM_FP )
#define configENABLE_FPU                        1
#else
#define configENABLE_FPU                        0
#endif
/* Helium (M-profile vector extension) context, only when the compiler is
 * allowed to emit MVE instructions (-mcpu=cortex-m55/m85 without a plain FPv4
 * -mfpu override). */
#if defined( __ARM_FEATURE_MVE )
#define configENABLE_MVE                        1
#else
#define configENABLE_MVE                        0
#endif
#define configENABLE_MPU                        0
#define configENABLE_TRUSTZONE                  0
#define configRUN_FREERTOS_SECURE_ONLY          1
#endif
#endif

/* Run-time stats (per-task CPU usage), surfaced in NECTO's FreeRTOS debug tab.
 * The time base is a plain software counter incremented from
 * vApplicationTickHook() (app_freertos.c).
 *
 * It deliberately does NOT use the Cortex-M DWT cycle counter (0xE0001004):
 * CYCCNT is an OPTIONAL feature, and where it is not implemented
 * DWT_CTRL.NOCYCCNT (bit 25) reads 1 and DWT_CTRL.CYCCNTENA is write-ignored,
 * so enabling it silently does nothing and the register reads back a permanent
 * 0 - every task then reports 0% run time (observed on Cortex-M7, e.g.
 * STM32F767BI). Enabling DWT also depends on DEMCR.TRCENA, i.e. on the
 * debug/trace power domain being up, which the application can neither detect
 * nor rely on.
 *
 * A tick-driven counter is architecture-neutral and needs no debug hardware,
 * so it behaves the same on M0/M0+, M4, M7 and RISC-V, and over any probe -
 * local or Planet Debug.
 *
 * Resolution caveat: at configTICK_RATE_HZ a task that only ever runs for less
 * than one tick between switches can accumulate 0 and read as 0%. FreeRTOS
 * recommends a stats clock roughly 10x the tick rate for fine-grained
 * profiling; if that matters for a given application, replace the hook with a
 * spare hardware timer for the MCU in use. */
#define configGENERATE_RUN_TIME_STATS           1
/* Some ports preprocess this header from assembly (e.g. the PIC32MZ port's
 * port_asm.S includes it), where a C declaration would be a syntax error - so
 * hide the declaration and the value macro from the assembler. FreeRTOS only
 * expands portGET_RUN_TIME_COUNTER_VALUE() from C. */
#ifndef __ASSEMBLER__
extern unsigned long ulAppRunTimeCounter;
/* The counter needs no hardware setup, so the configure hook is a no-op. */
#define portCONFIGURE_TIMER_FOR_RUN_TIME_STATS()  do { } while( 0 )
#define portGET_RUN_TIME_COUNTER_VALUE()          ( ulAppRunTimeCounter )
#endif

/* Records each task's stack end address in its TCB, which is what lets the
 * debugger report a real stack usage figure per task. */
#define configRECORD_STACK_HIGH_ADDRESS         1

/* The startup file's vector table calls SVC_Handler/PendSV_Handler by name, so
 * app_freertos.c routes those to the port's handlers indirectly (naked branch)
 * rather than naming the port's handlers directly in the vector table. Per
 * the port's own xPortStartScheduler() comment, indirect routing requires
 * this to be 0 — otherwise it asserts on the (expected) address mismatch. */
#define configCHECK_HANDLER_INSTALLATION        0

#define configASSERT( x ) if( ( x ) == 0 ) { taskDISABLE_INTERRUPTS(); for( ;; ); }

#endif    // FREERTOS_CONFIG_H
