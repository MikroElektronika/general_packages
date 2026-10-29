/**
 * @file main.c
 * @brief Main source file for the ${PROJECT_NAME} application.
 *
 * Starts the FreeRTOS scheduler after creating the application's tasks.
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

    /* Execution should never reach this point. */
    while (1)
    {
    }

    return 0;
}
