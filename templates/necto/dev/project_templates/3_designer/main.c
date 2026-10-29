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

#if defined(tp_st7789) && (_TFT_HEIGHT_ > _TFT_WIDTH_)
/* Panels taller than wide (e.g. IPS Display Click, 135x240) sit centered in the
 * ST7789's 240x320 GRAM, so the frame window is shifted onto the visible area.
 * The driver's functions aren't wrapped, as mikroC for PIC18 reports that as recursion. */
#include "st7789_cmd.h"

#define DISP_COL_OFFSET ((240 - _TFT_WIDTH_) / 2)
#define DISP_ROW_OFFSET ((320 - _TFT_HEIGHT_) / 2)

static digital_out_t disp_pin_cs; /**< Same CS pin the driver uses. */
static digital_out_t disp_pin_dc; /**< Same D/C pin the driver uses. */

static void display_begin_frame_offset(gl_rectangle_t *rect)
{
    uint16_t x1 = rect->top_left.x + DISP_COL_OFFSET, x2 = x1 + rect->width - 1;
    uint16_t y1 = rect->top_left.y + DISP_ROW_OFFSET, y2 = y1 + rect->height - 1;

    st7789_write_command(ST7789_CMD_CASET);
    st7789_write_param(x1 >> 8); st7789_write_param(x1);
    st7789_write_param(x2 >> 8); st7789_write_param(x2);

    st7789_write_command(ST7789_CMD_RASET);
    st7789_write_param(y1 >> 8); st7789_write_param(y1);
    st7789_write_param(y2 >> 8); st7789_write_param(y2);

    st7789_write_command(ST7789_CMD_RAMWR);
    digital_out_low(&disp_pin_cs);
    digital_out_high(&disp_pin_dc);
}

static void display_fill_offset(gl_rectangle_t *rect, gl_color_t color)
{
    uint32_t length = (uint32_t)rect->width * rect->height;

    if (!length)
        return;

    display_begin_frame_offset(rect);
    while (length--)
        display_driver.frame_data_f(color);
    display_driver.end_frame_f();
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

    #if defined(tp_st7789) && (_TFT_HEIGHT_ > _TFT_WIDTH_)
    digital_out_init(&disp_pin_cs, MIKROBUS(DISPLAY_SPI_MIKROBUS, MIKROBUS_CS));
    digital_out_init(&disp_pin_dc, MIKROBUS(DISPLAY_SPI_MIKROBUS, MIKROBUS_INT));
    display_driver.fill_f = display_fill_offset;
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
