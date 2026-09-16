/**
 * @file app_freertos.c
 * @brief LVGL task implementation for the ${PROJECT_NAME} FreeRTOS LVGL application.
 *
 * Differs from the bare-metal LVGL designer template in where LVGL's time
 * comes from. That template configures SysTick via 1ms_timer/ and drives
 * lv_tick_inc() plus process_tp() from the SysTick ISR. The FreeRTOS port owns
 * SysTick (it is the kernel tick source), so a second SysTick_Handler here
 * would collide with the port's and the scheduler would never tick.
 *
 * Instead this template drops 1ms_timer/ entirely and drives LVGL from a task:
 * the kernel tick advances the FreeRTOS tick count, and the LVGL task converts
 * elapsed kernel ticks into lv_tick_inc() before each lv_task_handler() pass.
 *
 * LVGL itself is not thread-safe and is built with LV_USE_OS == LV_OS_NONE, so
 * every LVGL call - including the screen-show functions - stays inside this one
 * task. Call lv_* from another task only after adding a mutex around all LVGL
 * access.
 */

#include "app_freertos.h"

#include "FreeRTOS.h"
#include "task.h"

#include "display_lvgl.h"
#include "lv_port_indev.h"
#include "screens.h"

/* LVGL task tuning. LVGL's rendering needs a considerably deeper stack than
 * configMINIMAL_STACK_SIZE; lower this only after checking the task's high
 * water mark (uxTaskGetStackHighWaterMark). */
#define LVGL_TASK_STACK_SIZE  ( configMINIMAL_STACK_SIZE * 4 )
#define LVGL_TASK_PRIORITY    ( tskIDLE_PRIORITY + 2 )

/* How often the LVGL task wakes to render and poll touch. Matches the 5 ms
 * cadence the bare-metal template used. */
#define LVGL_TASK_PERIOD_MS   ( 5 )

/* Starter banner shown on top of the designer's main screen, so a freshly
 * generated project draws something recognisable before any screen is edited.
 * Delete demo_banner_create() and its call below once the screen carries your
 * own widgets. */
#define DEMO_BANNER_TEXT        "LVGL on FreeRTOS running..."
#define DEMO_BANNER_FADE_MS     ( 1000 )

/* Animates the banner's opacity. LVGL calls this from lv_task_handler(), i.e.
 * on this task, so it needs no locking of its own. */
static void demo_banner_opa_cb(void *obj, int32_t value)
{
    lv_obj_set_style_opa((lv_obj_t *)obj, (lv_opa_t)value, LV_PART_MAIN);
}

static void demo_banner_create(void)
{
    lv_anim_t anim;
    lv_obj_t *label = lv_label_create(lv_screen_active());

    lv_label_set_text(label, DEMO_BANNER_TEXT);
    lv_obj_align(label, LV_ALIGN_CENTER, 0, 0);

    /* Fade out and back in forever. The animation is driven by LVGL's own
     * timer off lv_tick_inc(), which the loop below feeds from the kernel
     * tick - so the pulse is also a live indicator that the scheduler is
     * ticking and the LVGL task is being run. */
    lv_anim_init(&anim);
    lv_anim_set_var(&anim, label);
    lv_anim_set_exec_cb(&anim, demo_banner_opa_cb);
    lv_anim_set_values(&anim, LV_OPA_COVER, LV_OPA_30);
    lv_anim_set_duration(&anim, DEMO_BANNER_FADE_MS);
    lv_anim_set_reverse_duration(&anim, DEMO_BANNER_FADE_MS);
    lv_anim_set_repeat_count(&anim, LV_ANIM_REPEAT_INFINITE);
    lv_anim_start(&anim);
}

static void lvgl_task(void *pvParameters)
{
    TickType_t lastWake;
    TickType_t lastTick;

    (void) pvParameters;

    // Initialize LVGL, the display driver and the touch input device.
    lv_init();
    lv_port_disp_init();
    lv_port_indev_init();

    // Initialize all available screens.
    init_screens();

    // Show the main screen.
    // To display another screen, call its respective show function.
    show_main_screen();

    // Starter banner on top of the loaded screen - remove when not needed.
    demo_banner_create();

    lastWake = xTaskGetTickCount();
    lastTick = lastWake;

    ////////////////////////// LVGL timing routine (DO NOT REMOVE) //////////////////////////
    for (;;)
    {
        TickType_t now = xTaskGetTickCount();

        /* Hand LVGL the real elapsed time rather than a fixed constant, so its
         * animations stay correct even when a render pass overruns the period.
         * Tick subtraction is wrap-safe; the conversion assumes
         * configTICK_RATE_HZ is 1000 (1 tick == 1 ms). */
        if (now != lastTick)
        {
            lv_tick_inc((uint32_t)(now - lastTick) * (1000U / configTICK_RATE_HZ));
            lastTick = now;
        }

        process_tp();

        lv_task_handler();

        vTaskDelayUntil(&lastWake, pdMS_TO_TICKS(LVGL_TASK_PERIOD_MS));
    }
    ////////////////////////////////////////////////////////////////////////////////////////
}

void app_freertos_init(void)
{
    xTaskCreate(lvgl_task, "LVGL", LVGL_TASK_STACK_SIZE, NULL, LVGL_TASK_PRIORITY, NULL);
}

/* The MikroC port (portable/MikroC/ARM_CM4F/port.c) declares its own vectored
 * handlers (iv IVT_INT_SysTick / IVT_INT_PendSV / IVT_INT_SVCall), so nothing
 * is needed there. The GCC port does not: its handlers are plain functions the
 * vector table never reaches by name, so route the three exceptions into the
 * kernel here. */
#if defined( __GNUC__ ) && defined( __arm__ )

/* Provided by the FreeRTOS port (portable/GCC/ARM_CMx/port.c); not exposed via
 * a shared header, so it is forward-declared here. */
extern void xPortSysTickHandler(void);

void SysTick_Handler(void)
{
    xPortSysTickHandler();
}

/* vPortSVCHandler/xPortPendSVHandler are naked - they rely on being the
 * exception entry itself, so they cannot be called from a wrapper. Branch to
 * them directly. */
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
 * Not guarded on __arm__ (unlike the handlers above): the counter is plain C
 * with no architecture-specific registers, and the config wires it up for
 * every port, so the symbol has to exist on any toolchain.
 *
 * The kernel calls vApplicationTickHook() from its own tick ISR (which is why
 * configUSE_TICK_HOOK is enabled), including on ports that supply their own
 * vectored tick handler and never reach the SysTick_Handler above. */
unsigned long ulAppRunTimeCounter = 0UL;

void vApplicationTickHook(void)
{
    ulAppRunTimeCounter++;
}

/* Required because FreeRTOSConfig.h sets configCHECK_FOR_STACK_OVERFLOW to 2.
 * The LVGL task is the most likely one to trip this - see
 * LVGL_TASK_STACK_SIZE. */
void vApplicationStackOverflowHook(TaskHandle_t xTask, char *pcTaskName)
{
    (void) xTask;
    (void) pcTaskName;

    taskDISABLE_INTERRUPTS();
    for (;;)
    {
    }
}
