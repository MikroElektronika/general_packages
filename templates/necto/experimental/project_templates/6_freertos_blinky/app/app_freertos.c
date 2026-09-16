/**
 * @file app_freertos.c
 * @brief Blinky task implementation for the ${PROJECT_NAME} FreeRTOS application.
 */

#include "app_freertos.h"

#include "FreeRTOS.h"
#include "task.h"

#include "drv_digital_out.h"

/* Demo LED bank driven by the blinky task. Update the pin list below to match
 * your board's LED wiring (see your board's schematic for the actual pins). */
#define BLINKY_LED_PIN_COUNT 8

static digital_out_t blinky_led_pins[BLINKY_LED_PIN_COUNT];

static const pin_name_t blinky_led_pin_names[BLINKY_LED_PIN_COUNT] =
{
    PC0, PC1, PC2, PC3, PC4, PC5, PC6, PC7
};

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

void app_freertos_init(void)
{
    xTaskCreate(blinky_task, "Blinky", configMINIMAL_STACK_SIZE, NULL, tskIDLE_PRIORITY + 1, NULL);
}

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
