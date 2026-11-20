/* SPDX-License-Identifier: Apache-2.0 */
/*
 * macOS / Windows selection.
 *
 * The keymap has one marker layer ("Win"). While it is active, conditional layers turn Nav, ExtNav,
 * Desk and DeskMove into their Windows copies. This file turns the marker layer on or off from the
 * &os_mac / &os_win / &os_tog keys and remembers the choice across power cycles.
 * Which layer is the marker comes from the keymap (&c80os_cfg { win-layer = <N>; }); 255 disables it.
 */
#include <zephyr/kernel.h>
#include <zephyr/devicetree.h>
#include <zephyr/logging/log.h>
#include <zephyr/settings/settings.h>

#include <zmk/keymap.h>

#include "rgb/engine.h"

LOG_MODULE_REGISTER(c80os, LOG_LEVEL_INF);

#define CFG_NODE DT_COMPAT_GET_ANY_STATUS_OKAY(crush80_os_config)
#define WIN_LAYER DT_PROP(CFG_NODE, win_layer)

static uint8_t win_on;

static void apply_handler(struct k_work *work) {
    if (WIN_LAYER >= ZMK_KEYMAP_LAYERS_LEN) {
        return;
    }
    zmk_keymap_layer_id_t id = zmk_keymap_layer_index_to_id(WIN_LAYER);
    int rc = win_on ? zmk_keymap_layer_activate(id, false) : zmk_keymap_layer_deactivate(id, false);
    if (rc) {
        LOG_WRN("OS layer change failed: %d", rc);
    }
}
static K_WORK_DELAYABLE_DEFINE(apply_work, apply_handler);

#if IS_ENABLED(CONFIG_SETTINGS)
static void save_handler(struct k_work *work) {
    settings_save_one("c80os/win", &win_on, sizeof(win_on));
}
static K_WORK_DELAYABLE_DEFINE(save_work, save_handler);

static int set_cb(const char *name, size_t len, settings_read_cb read_cb, void *cb_arg) {
    const char *next;

    if (settings_name_steq(name, "win", &next) && !next) {
        if (len != sizeof(win_on)) {
            return -EINVAL;
        }
        return read_cb(cb_arg, &win_on, sizeof(win_on)) >= 0 ? 0 : -EIO;
    }
    return -ENOENT;
}
SETTINGS_STATIC_HANDLER_DEFINE(c80os, "c80os", NULL, set_cb, NULL, NULL);
#endif

int c80_os_action(int action) {
    uint8_t want = (action == 2) ? !win_on : (action == 1);

    if (want == win_on) {
        return 0;
    }
    win_on = want;
    k_work_reschedule(&apply_work, K_NO_WAIT);
#if IS_ENABLED(CONFIG_SETTINGS)
    k_work_reschedule(&save_work, K_SECONDS(3));
#endif
    return 0;
}

static int c80_os_init(void) {
    /* Settings have loaded by now; apply the remembered choice once the keymap is up. */
    k_work_schedule(&apply_work, K_SECONDS(2));
    return 0;
}
SYS_INIT(c80_os_init, APPLICATION, 99);
