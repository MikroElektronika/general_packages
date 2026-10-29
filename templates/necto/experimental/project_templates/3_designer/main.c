/**
 * @file main.c
 * @brief Main source file for the ${PROJECT_NAME} TFT Designer application.
 *
 * This example demonstrates usage of the Visual TFT (VTFT) and
 * Graphic Library (GL) for creating and running GUI applications
 * on TFT displays with touch support.
 */

#ifdef PREINIT_SUPPORTED
#include "preinit.h"
#endif

#include "vtft.h"
#include "gl.h"
#include "main_screen.h"
#include "touch_controller.h"

static gl_driver_t display_driver; /**< Graphic library display driver. */

/* For displays with a height greater than the width (e.g. IPS Display Click, 135x240),
 * the visible area is centered within the 240x320 ST7789 frame memory.
 * Column offset = (240 - width) / 2, row offset = (320 - height) / 2. */
#define DISP_GRAM_WIDTH  240
#define DISP_GRAM_HEIGHT 320

#ifndef DISP_COL_OFFSET
#if _TFT_HEIGHT_ > _TFT_WIDTH_
#define DISP_COL_OFFSET  ((DISP_GRAM_WIDTH  - _TFT_WIDTH_)  / 2)
#else
#define DISP_COL_OFFSET  0
#endif
#endif

#ifndef DISP_ROW_OFFSET
#if _TFT_HEIGHT_ > _TFT_WIDTH_
#define DISP_ROW_OFFSET  ((DISP_GRAM_HEIGHT - _TFT_HEIGHT_) / 2)
#else
#define DISP_ROW_OFFSET  0
#endif
#endif

#if (DISP_COL_OFFSET != 0) || (DISP_ROW_OFFSET != 0)
static gl_fill_t        display_fill;        /**< Original driver fill function. */
static gl_begin_frame_t display_begin_frame; /**< Original driver begin frame function. */

/**
 * @brief Shifts the drawing window onto the visible area of the panel.
 */
static void display_offset_rect(gl_rectangle_t *dst, gl_rectangle_t *src)
{
    dst->top_left.x = src->top_left.x + DISP_COL_OFFSET;
    dst->top_left.y = src->top_left.y + DISP_ROW_OFFSET;
    dst->width = src->width;
    dst->height = src->height;
}

static void display_fill_offset(gl_rectangle_t *rect, gl_color_t color)
{
    gl_rectangle_t shifted;

    display_offset_rect(&shifted, rect);
    display_fill(&shifted, color);
}

static void display_begin_frame_offset(gl_rectangle_t *rect)
{
    gl_rectangle_t shifted;

    display_offset_rect(&shifted, rect);
    display_begin_frame(&shifted);
}
#endif

static tp_t tp;                    /**< Touch panel driver instance. */
static vtft_t vtft;                /**< VTFT (Visual TFT) application context. */
static tp_drv_t tp_interface;      /**< Touch controller interface. */

/**
 * @brief Initializes board peripherals required for display and touch.
 */
void board_init()
{
    touch_controller_init(&display_driver, TFT_MAX_BACKLIGHT);

    #if (DISP_COL_OFFSET != 0) || (DISP_ROW_OFFSET != 0)
    // Panels taller than wide sit centered inside the controller's GRAM,
    // so wrap the driver's drawing functions to apply the offset.
    display_fill = display_driver.fill_f;
    display_begin_frame = display_driver.begin_frame_f;
    if (display_fill)
        display_driver.fill_f = display_fill_offset;
    if (display_begin_frame)
        display_driver.begin_frame_f = display_begin_frame_offset;
    #endif

    // Initialize the Graphic Library and register the display driver.
    gl_set_driver(&display_driver);

    // Initialize the touch controller and interface.
    touch_controller_tp_init(&tp, &tp_interface);
}

/**
 * @brief Initializes the Visual TFT (VTFT) environment.
 *
 * Configures and initializes the GUI environment using the
 * Visual TFT library and displays the main screen.
 */
void application_init()
{
    board_init();

    // Initialize VTFT and show the default screen.
    vtft_init(&vtft, &tp);
    main_screen_show(&vtft);
}

/**
 * @brief Main application loop.
 *
 * Handles continuous GUI updates and touch input processing.
 */
void application_task()
{
    vtft_process(&vtft);
}

/**
 * @brief Application entry point.
 *
 * Initializes the MCU, peripherals, and starts the VTFT application loop.
 * Do not remove the preinit() call — it ensures proper clock configuration.
 */
void main()
{
    /* Do not remove this line — it ensures correct MCU initialization. */
#ifdef PREINIT_SUPPORTED
    preinit();
#endif

    application_init();

    while (1)
    {
        application_task();
    }
}
