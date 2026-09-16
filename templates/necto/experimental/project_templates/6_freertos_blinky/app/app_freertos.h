/**
 * @file app_freertos.h
 * @brief Task declarations for the ${PROJECT_NAME} FreeRTOS application.
 */

#ifndef APP_FREERTOS_H
#define APP_FREERTOS_H

#ifdef __cplusplus
extern "C" {
#endif

/**
 * @brief Creates the application's tasks.
 * @note Call once, before starting the scheduler.
 */
void app_freertos_init(void);

#ifdef __cplusplus
}
#endif

#endif    // APP_FREERTOS_H
