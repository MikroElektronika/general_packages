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
 * it is pulled in before the first use. */
#include "core_header.h"

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
 * FOSC_KHZ_VALUE at its 1000 (1 MHz) placeholder. That is never a plausible
 * core clock for a FreeRTOS target, so it is rejected here rather than
 * silently scaling every delay by ~200x: replace the whole block with a
 * literal, e.g. #define configCPU_CLOCK_HZ ( 216000000UL ), if your MCU is
 * one of them. */
#if !defined( FOSC_KHZ_VALUE )
    #error "FOSC_KHZ_VALUE not defined - include core_header.h, or set configCPU_CLOCK_HZ to a literal frequency."
#elif FOSC_KHZ_VALUE <= 1000
    #error "FOSC_KHZ_VALUE looks like NECTO's 1 MHz placeholder, not a real core clock - set configCPU_CLOCK_HZ to a literal frequency for this MCU."
#endif
#define configCPU_CLOCK_HZ                     ( FOSC_KHZ_VALUE * 1000UL )
#define configTICK_RATE_HZ                     ( ( TickType_t ) 1000 )
#define configMAX_PRIORITIES                   ( 5 )
#define configMINIMAL_STACK_SIZE                ( ( unsigned short ) 256 )
/* The LVGL task's stack comes out of this heap. LVGL's own draw buffers and
 * object allocations do NOT - those use LVGL's allocator (LV_MEM_SIZE in the
 * LVGL package's lv_conf.h), so budget both. Raise this if xTaskCreate() for
 * the LVGL task returns pdFAIL. */
#define configTOTAL_HEAP_SIZE                  ( ( size_t ) ( 32 * 1024 ) )
#define configMAX_TASK_NAME_LEN                 16
#define configUSE_TRACE_FACILITY                1
#define configUSE_16_BIT_TICKS                  0
#define configIDLE_SHOULD_YIELD                 1
#define configUSE_MUTEXES                       1
#define configQUEUE_REGISTRY_SIZE               8
#define configCHECK_FOR_STACK_OVERFLOW          2
#define configUSE_RECURSIVE_MUTEXES             1
#define configUSE_MALLOC_FAILED_HOOK            0
#define configUSE_COUNTING_SEMAPHORES           1

/* Co-routine definitions. */
#define configUSE_CO_ROUTINES                   0
#define configMAX_CO_ROUTINE_PRIORITIES         ( 2 )

/* Software timer definitions. */
#define configUSE_TIMERS                        1
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

/* Cortex-M specific definitions. */
#define configPRIO_BITS                         4
#define configLIBRARY_LOWEST_INTERRUPT_PRIORITY  15
#define configLIBRARY_MAX_SYSCALL_INTERRUPT_PRIORITY  5
#define configKERNEL_INTERRUPT_PRIORITY \
    ( configLIBRARY_LOWEST_INTERRUPT_PRIORITY << ( 8 - configPRIO_BITS ) )
#define configMAX_SYSCALL_INTERRUPT_PRIORITY \
    ( configLIBRARY_MAX_SYSCALL_INTERRUPT_PRIORITY << ( 8 - configPRIO_BITS ) )

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
