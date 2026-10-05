#include "lv_port_indev.h"
#include "lvgl_common.h"

/* LVGL v9: read_cb signature changed, and lv_indev_drv_t is removed */
static void touchpad_init(void);
static void touchpad_read(lv_indev_t * indev, lv_indev_data_t * data);
static bool touchpad_is_pressed(void);
static void touchpad_get_xy(lv_coord_t * x, lv_coord_t * y);

lv_indev_t * indev_touchpad;

/* --- Debugger touch simulation (driven from NECTO) ---
 * volatile = compiler won't optimize away; debugger writes take effect.
 *
 * Coords are packed into single words so each event is ONE debugger write
 * (one DAP round-trip): bit24 = trigger, [11:0] = x, [23:12] = y.
 *
 * Tap:  sim_tap   = trigger|x|y
 * Drag: sim_drag_a = x0|y0  then  sim_drag_b = trigger|x1|y1
 */
#define SIM_CLICK_POLLS 3          /* read cycles to hold the press */
#define SIM_DRAG_STEPS  12         /* polls along the drag path     */
#define SIM_TRIGGER     0x01000000u /* bit24: tap/drag trigger AND per-sample pressed flag */
#define SIM_MASK        0x00000FFFu

volatile uint32_t sim_tap = 0;
volatile uint32_t sim_drag_a = 0;
volatile uint32_t sim_drag_b = 0;

static int16_t  sim_x = 0, sim_y = 0;             /* latched tap coords            */
static uint8_t  sim_click_hold = 0;               /* pressed-poll counter          */
static int16_t  sim_dx0 = 0, sim_dy0 = 0, sim_dx1 = 0, sim_dy1 = 0;
static uint16_t sim_drag_i = 0;
static uint8_t  sim_drag_active = 0;

/* --- Generic gesture path player (driven from NECTO) ---
 * Supersedes tap/drag for arbitrary gestures: NECTO fills sim_path[] with a
 * timeline of pointer samples (each: bit24 = pressed, [23:12] = y, [11:0] = x),
 * sets sim_path_len, then writes sim_path_go = 1 LAST (one DAP round-trip) to
 * start replay. The player emits exactly ONE sample per read cycle, so the host
 * controls velocity (sample spacing), holds (repeated coords -> long press) and
 * multi-tap (pressed/released segments) purely by how it lays out the samples.
 * One read cycle ~= the LVGL indev read period (~30 ms here); the host must
 * resample its captured cursor path at that period to reproduce real velocity.
 */
#define SIM_PATH_MAX 32
volatile uint32_t sim_path[SIM_PATH_MAX];   /* per-sample packed pointer state */
volatile uint32_t sim_path_len = 0;         /* valid samples (clamped to MAX)  */
volatile uint32_t sim_path_go  = 0;         /* nonzero -> replaying; cleared at end */

static uint16_t sim_path_i = 0;             /* next sample index to emit */

void process_tp(void)
{
    tp_process(&tp);
}

void lv_port_indev_init(void)
{
    touchpad_init();

    /* LVGL v9+: create indev and configure it (no lv_indev_drv_t anymore) */
    indev_touchpad = lv_indev_create();
    lv_indev_set_type(indev_touchpad, LV_INDEV_TYPE_POINTER);
    lv_indev_set_read_cb(indev_touchpad, touchpad_read);

    /*
     * If you have multiple displays, ensure the correct display is default
     * before creating the indev, or explicitly bind it:
     * lv_indev_set_display(indev_touchpad, your_display);
     */
}

/* Initialize your touchpad. */
static void touchpad_init(void)
{
    touch_controller_tp_init(&tp, &tp_interface);
}

/* Will be called by LVGL to read the touchpad. */
static void touchpad_read(lv_indev_t * indev, lv_indev_data_t * data)
{
    LV_UNUSED(indev);

    static lv_coord_t last_x = 0;
    static lv_coord_t last_y = 0;

    /* Gesture path player takes priority while active: emit one sample/read. */
    if(sim_path_go) {
        uint16_t len = (sim_path_len > SIM_PATH_MAX) ? SIM_PATH_MAX : (uint16_t)sim_path_len;
        if(sim_path_i < len) {
            uint32_t s = sim_path[sim_path_i];
            last_x = (int16_t)(s & SIM_MASK);
            last_y = (int16_t)((s >> 12) & SIM_MASK);
            data->state = (s & SIM_TRIGGER) ? LV_INDEV_STATE_PRESSED
                                            : LV_INDEV_STATE_RELEASED;
            sim_path_i++;
        }
        else {
            /* Past the end: force a clean release at the last point and stop. */
            data->state = LV_INDEV_STATE_RELEASED;
            sim_path_go = 0;
            sim_path_i  = 0;
        }
        data->point.x = last_x;
        data->point.y = last_y;
        return;
    }

    /* Decode one-shot requests (single packed debugger write each). */
    if(sim_tap & SIM_TRIGGER) {
        sim_x = (int16_t)(sim_tap & SIM_MASK);
        sim_y = (int16_t)((sim_tap >> 12) & SIM_MASK);
        sim_tap = 0;
        sim_click_hold = SIM_CLICK_POLLS;
    }
    if(sim_drag_b & SIM_TRIGGER) {
        sim_dx0 = (int16_t)(sim_drag_a & SIM_MASK);
        sim_dy0 = (int16_t)((sim_drag_a >> 12) & SIM_MASK);
        sim_dx1 = (int16_t)(sim_drag_b & SIM_MASK);
        sim_dy1 = (int16_t)((sim_drag_b >> 12) & SIM_MASK);
        sim_drag_b = 0;
        sim_drag_active = 1;
        sim_drag_i = 0;
    }

    if(sim_drag_active) {
        /* Interpolate start->end while pressed; release one poll past the end. */
        if(sim_drag_i <= SIM_DRAG_STEPS) {
            last_x = sim_dx0 +
                     (int16_t)((int32_t)(sim_dx1 - sim_dx0) * sim_drag_i / SIM_DRAG_STEPS);
            last_y = sim_dy0 +
                     (int16_t)((int32_t)(sim_dy1 - sim_dy0) * sim_drag_i / SIM_DRAG_STEPS);
            data->state = LV_INDEV_STATE_PRESSED;
            sim_drag_i++;
        }
        else {
            last_x = sim_dx1;
            last_y = sim_dy1;
            data->state = LV_INDEV_STATE_RELEASED;
            sim_drag_active = 0;
        }
    }
    else if(sim_click_hold > 0) {
        sim_click_hold--;
        last_x = sim_x;
        last_y = sim_y;
        data->state = LV_INDEV_STATE_PRESSED;
    }
    else if(touchpad_is_pressed()) {
        touchpad_get_xy(&last_x, &last_y);
        data->state = LV_INDEV_STATE_PRESSED;
    }
    else {
        data->state = LV_INDEV_STATE_RELEASED;
    }

    data->point.x = last_x;
    data->point.y = last_y;
}

/* Return true if the touchpad is pressed. */
static bool touchpad_is_pressed(void)
{
    /* Your original code missed the return statement. */
    check_touchpad();
}

/* Get the x and y coordinates if the touchpad is pressed. */
static void touchpad_get_xy(lv_coord_t * x, lv_coord_t * y)
{
    get_touch_coordinates(x, y);
}

