/* SPDX-License-Identifier: Apache-2.0 */
#define DT_DRV_COMPAT crush80_behavior_os

#include <zephyr/device.h>
#include <drivers/behavior.h>
#include <zmk/behavior.h>

#include "engine.h"

#if DT_HAS_COMPAT_STATUS_OKAY(DT_DRV_COMPAT)

struct c80_beh_cfg {
    int action;
};

static int on_pressed(struct zmk_behavior_binding *binding, struct zmk_behavior_binding_event event) {
    const struct device *dev = zmk_behavior_get_binding(binding->behavior_dev);
    const struct c80_beh_cfg *cfg = dev->config;

    c80_os_action(cfg->action);
    return ZMK_BEHAVIOR_OPAQUE;
}

static int on_released(struct zmk_behavior_binding *binding, struct zmk_behavior_binding_event event) {
    return ZMK_BEHAVIOR_OPAQUE;
}

static const struct behavior_driver_api c80_beh_os_api = {
    .binding_pressed = on_pressed,
    .binding_released = on_released,
    .locality = BEHAVIOR_LOCALITY_EVENT_SOURCE,
#if IS_ENABLED(CONFIG_ZMK_BEHAVIOR_METADATA)
    .get_parameter_metadata = zmk_behavior_get_empty_param_metadata,
#endif
};

#define C80_OS_INST(n)                                                                            \
    static const struct c80_beh_cfg c80_beh_os_cfg_##n = {.action = DT_INST_PROP(n, action)};     \
    BEHAVIOR_DT_INST_DEFINE(n, NULL, NULL, NULL, &c80_beh_os_cfg_##n, POST_KERNEL,                \
                            CONFIG_KERNEL_INIT_PRIORITY_DEFAULT, &c80_beh_os_api);

DT_INST_FOREACH_STATUS_OKAY(C80_OS_INST)

#endif
