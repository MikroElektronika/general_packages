/**
 * @file main.c
 * @brief Main source file for the ${PROJECT_NAME} FreeRTOS LVGL Designer application.
 *
 * Starts the FreeRTOS scheduler after creating the application's tasks. LVGL
 * setup, timing and rendering live in the LVGL task - see app/app_freertos.c.
 *
 * Add the FreeRTOS package via the Library Manager before building.
 */

#ifdef PREINIT_SUPPORTED
#include "preinit.h"
#endif

#include "FreeRTOS.h"
#include "task.h"
#include "app_freertos.h"

int main(void)
{
    /* Do not remove this line — it ensures correct MCU initialization. */
#ifdef PREINIT_SUPPORTED
    preinit();
#endif

    app_freertos_init();

    vTaskStartScheduler();

    /* Execution should never reach this point. Getting here means the kernel
     * ran out of heap while starting the idle/timer task - raise
     * configTOTAL_HEAP_SIZE in config/FreeRTOSConfig.h. */
    while (1)
    {
    }

    return 0;
}
