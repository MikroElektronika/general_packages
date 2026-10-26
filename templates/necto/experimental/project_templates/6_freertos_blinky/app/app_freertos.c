/**
 * @file app_freertos.c
 * @brief Blinky task implementation for the ${PROJECT_NAME} FreeRTOS application.
 */

#include "app_freertos.h"

#include "FreeRTOS.h"
#include "task.h"

#ifdef NECTO_BARE_METAL

/* Bare-metal setups have no mikroSDK GPIO driver, so the blinky task toggles a
 * variable instead of LEDs. Watch it in the debugger, or replace the toggle
 * with a write to your MCU's GPIO registers. */
static volatile uint8_t blinky_state = 0;

static void blinky_task(void *pvParameters)
{
    (void) pvParameters;

    for (;;)
    {
        blinky_state ^= 1U;

        vTaskDelay(pdMS_TO_TICKS(500));
    }
}

#else

#include "drv_digital_out.h"

/* Demo LED bank driven by the blinky task. Update the pin list below to match
 * your board's LED wiring (see your board's schematic for the actual pins). */
/* Board LEDs when mikroSDK's board.h names them (e.g. EK-RA8M1: LED1-LED3 on
 * P600/P414/P107; Clicker 4 boards: LED_1-LED_6, e.g. P307/P305/P303/P112/
 * P114/P608 on Clicker 4 for RA4M2). Otherwise pins 0-7 of one port of the
 * Fusion/UNI-DS LED bank, which has an LED behind every port pin: port C, or
 * port D, or port B when the selected MCU has none of the earlier one's pins
 * 0-7 (e.g. STM32F031C6 only has PC13-PC15). Only the pins the MCU has are listed, since mikroSDK only
 * defines a pin name when the pin exists (e.g. PIC32MZ2048EFH144 has PC1-PC4
 * but no PC0 or PC5-PC7). The same template then builds for any MCU. */
#if defined( __has_include )
    #if __has_include( "board.h" )
        #include "board.h"
    #endif
#endif

static const pin_name_t blinky_led_pin_names[] =
{
#if defined( LED1 )
    LED1,
    #ifdef LED2
    LED2,
    #endif
    #ifdef LED3
    LED3,
    #endif
    #ifdef LED4
    LED4,
    #endif
#elif defined( LED_1 )
    LED_1,
    #ifdef LED_2
    LED_2,
    #endif
    #ifdef LED_3
    LED_3,
    #endif
    #ifdef LED_4
    LED_4,
    #endif
    #ifdef LED_5
    LED_5,
    #endif
    #ifdef LED_6
    LED_6,
    #endif
#else
    #if defined( PC0 ) || defined( PC1 ) || defined( PC2 ) || defined( PC3 ) || \
        defined( PC4 ) || defined( PC5 ) || defined( PC6 ) || defined( PC7 )
    #ifdef PC0
    PC0,
    #endif
    #ifdef PC1
    PC1,
    #endif
    #ifdef PC2
    PC2,
    #endif
    #ifdef PC3
    PC3,
    #endif
    #ifdef PC4
    PC4,
    #endif
    #ifdef PC5
    PC5,
    #endif
    #ifdef PC6
    PC6,
    #endif
    #ifdef PC7
    PC7,
    #endif
    #elif defined( PD0 ) || defined( PD1 ) || defined( PD2 ) || defined( PD3 ) || \
        defined( PD4 ) || defined( PD5 ) || defined( PD6 ) || defined( PD7 )
    #ifdef PD0
    PD0,
    #endif
    #ifdef PD1
    PD1,
    #endif
    #ifdef PD2
    PD2,
    #endif
    #ifdef PD3
    PD3,
    #endif
    #ifdef PD4
    PD4,
    #endif
    #ifdef PD5
    PD5,
    #endif
    #ifdef PD6
    PD6,
    #endif
    #ifdef PD7
    PD7,
    #endif
    #elif defined( PB0 ) || defined( PB1 ) || defined( PB2 ) || defined( PB3 ) || \
        defined( PB4 ) || defined( PB5 ) || defined( PB6 ) || defined( PB7 )
    #ifdef PB0
    PB0,
    #endif
    #ifdef PB1
    PB1,
    #endif
    #ifdef PB2
    PB2,
    #endif
    #ifdef PB3
    PB3,
    #endif
    #ifdef PB4
    PB4,
    #endif
    #ifdef PB5
    PB5,
    #endif
    #ifdef PB6
    PB6,
    #endif
    #ifdef PB7
    PB7,
    #endif
    #else
        #error "No board LEDs and none of pins 0-7 of port C, D or B on this MCU - list your board's LED pins in blinky_led_pin_names."
    #endif
#endif
};

#define BLINKY_LED_PIN_COUNT ( sizeof( blinky_led_pin_names ) / sizeof( blinky_led_pin_names[0] ) )

static digital_out_t blinky_led_pins[BLINKY_LED_PIN_COUNT];

static void blinky_task(void *pvParameters)
{
    uint8_t i;

    (void) pvParameters;

    for (i = 0; i < BLINKY_LED_PIN_COUNT; i++)
    {
        digital_out_init(&blinky_led_pins[i], blinky_led_pin_names[i]);
    }

    for (;;)
    {
        for (i = 0; i < BLINKY_LED_PIN_COUNT; i++)
        {
            digital_out_toggle(&blinky_led_pins[i]);
        }

        vTaskDelay(pdMS_TO_TICKS(500));
    }
}

#endif

void app_freertos_init(void)
{
#if defined( __XC32__ )
    /* The PIC32 ports' tick (Timer1) and yield (core software interrupt 0)
     * handlers sit in their own vectors, which the CPU only uses in
     * multi-vector mode. Neither the XC32 startup code nor mikroSDK (outside
     * its interrupt API) sets INTCON.MVEC - on PIC32MZ as well as PIC32MX - so
     * a project that never calls that API would leave the MCU in single-vector
     * mode and send the first yield to the default handler. */
    INTCONSET = _INTCON_MVEC_MASK;
#endif

#if defined( __riscv )
    /* The RISC-V port does not install its own trap handler: the startup file
     * points mtvec at a default handler that just spins, so the first yield
     * (ecall) or tick would never reach the kernel. Install the port's handler
     * in direct (CLINT) mode - the low mtvec bits are 0, which on the
     * GD32VF103 also takes the core out of ECLIC mode, so the machine timer
     * interrupt is delivered through mie.MTIE as the port expects. The handler
     * is 256-byte aligned (.align 8 in portASM.S), which mtvec needs. */
    {
        extern void freertos_risc_v_trap_handler(void);

        __asm volatile ( "csrw mtvec, %0" :: "r" ( freertos_risc_v_trap_handler ) );
    }
#endif

    xTaskCreate(blinky_task, "Blinky", configMINIMAL_STACK_SIZE, NULL, tskIDLE_PRIORITY + 1, NULL);
}

/* ARMv7-M GCC ports only (Cortex-M3/M4/M7: GCC_ARM_CM3, GCC_ARM_CM4F,
 * GCC_ARM_CM7). The ARMv6-M port (Cortex-M0/M0+) and the ARMv8-M ports
 * (Cortex-M23/M33/M55/M85) name their handlers SVC_Handler, PendSV_Handler
 * and SysTick_Handler themselves, so the startup file's weak entries already
 * reach them and defining them here too would clash at link time. Other ports
 * (e.g. the PIC32 MPLAB ports) install their own vectored handlers, and the ARM
 * branches below would not even assemble there. */
#if defined( __GNUC__ ) && ( defined( __ARM_ARCH_7M__ ) || defined( __ARM_ARCH_7EM__ ) )

/* Provided by the FreeRTOS port (portable/GCC/ARM_CMx/port.c); not exposed via
 * a shared header, so it is forward-declared here. */
extern void xPortSysTickHandler(void);

/* Routes the Cortex-M SysTick interrupt into the FreeRTOS kernel tick. Without
 * this, the startup file's weak SysTick_Handler stub takes over the vector and
 * the kernel tick never advances, so tasks blocked on vTaskDelay never wake. */
void SysTick_Handler(void)
{
    xPortSysTickHandler();
}

/* xPortStartScheduler() asserts that the vector table's SVC/PendSV entries
 * resolve to the port's vPortSVCHandler/xPortPendSVHandler before the first
 * task switch. The startup file's vector table calls SVC_Handler/PendSV_Handler
 * by name (weak-aliased to Default_Handler), and those handlers are naked
 * (they rely on being the exception entry itself, so they cannot be called
 * from a wrapper) — branch to them directly instead. */
void SVC_Handler(void) __attribute__((naked));
void SVC_Handler(void)
{
    __asm volatile ( "b vPortSVCHandler" );
}

void PendSV_Handler(void) __attribute__((naked));
void PendSV_Handler(void)
{
    __asm volatile ( "b xPortPendSVHandler" );
}

#endif

/* Run-time-stats time base, read by portGET_RUN_TIME_COUNTER_VALUE() in
 * FreeRTOSConfig.h - see the comment there for why this is a tick-driven
 * software counter rather than the Cortex-M DWT cycle counter.
 *
 * The kernel calls vApplicationTickHook() from its own tick ISR (which is why
 * configUSE_TICK_HOOK is enabled), including on ports that supply their own
 * vectored tick handler and never reach the SysTick_Handler above. */
unsigned long ulAppRunTimeCounter = 0UL;

void vApplicationTickHook(void)
{
    ulAppRunTimeCounter++;
}

/* Required because FreeRTOSConfig.h sets configCHECK_FOR_STACK_OVERFLOW to 2. */
void vApplicationStackOverflowHook(TaskHandle_t xTask, char *pcTaskName)
{
    (void) xTask;
    (void) pcTaskName;

    taskDISABLE_INTERRUPTS();
    for (;;)
    {
    }
}
