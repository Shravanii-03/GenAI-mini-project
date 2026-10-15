/* sdv_defences.c - see sdv_defences.h for scope and constraints. Mirrors sdv/system/brake_chain.py (_on_frame). */
#include "sdv_defences.h"

void sdv_config_default(sdv_config_t *cfg)
{
    cfg->policy = SDV_POLICY_NONE;
    cfg->auth_enabled = 0u;
    cfg->ttc_trigger_ms = 2000;
    cfg->disagree_tol_mm = 3000;
    cfg->disagree_fresh_us = 30000u;
    cfg->watchdog_us = 30000u;
    cfg->watchdog_check_us = 5000u;
}

void sdv_init(sdv_state_t *s, const sdv_config_t *cfg)
{
    s->cfg = *cfg;
    s->last_us[0] = 0u;
    s->last_us[1] = 0u;
    s->last_mm[0] = 0;
    s->last_mm[1] = 0;
    s->have[0] = 0u;
    s->have[1] = 0u;
    s->detected = 0u;
    s->watchdog_armed = 0u;
    s->last_valid_us = 0u;
    s->rejected = 0u;
}

static int32_t abs32(int32_t x)
{
    return (x < 0) ? -x : x;
}

/* wrap-safe "a is newer than or equal to b by at most limit microseconds" */
static uint8_t within_us(uint32_t now_us, uint32_t then_us, uint32_t limit_us)
{
    return (uint32_t)(now_us - then_us) <= limit_us;
}

static uint8_t channels_disagree(const sdv_state_t *s, uint32_t now_us)
{
    if (!s->have[0] || !s->have[1]) {
        return 0u;
    }
    if (!within_us(now_us, s->last_us[0], s->cfg.disagree_fresh_us) ||
        !within_us(now_us, s->last_us[1], s->cfg.disagree_fresh_us)) {
        return 0u;
    }
    return (uint8_t)(abs32(s->last_mm[0] - s->last_mm[1]) > s->cfg.disagree_tol_mm);
}

/* reported time-to-collision at or below the trigger: dist / speed <= T  <=>  dist * 1000 <= T_ms * speed (64-bit) */
static uint8_t ttc_at_or_below(int32_t dist_mm, int32_t speed_mms, int32_t trigger_ms)
{
    if (speed_mms <= 0) {
        return 0u;
    }
    return (uint8_t)(((int64_t)dist_mm * 1000) <= ((int64_t)trigger_ms * (int64_t)speed_mms));
}

sdv_trigger_t sdv_on_frame(sdv_state_t *s, uint8_t channel, uint32_t now_us, int32_t dist_mm, int32_t speed_mms,
                           uint8_t obstacle, uint8_t mac_ok)
{
    if (channel > SDV_CHANNEL_RADAR) {
        return SDV_NO_TRIGGER;
    }
    if (channel == SDV_CHANNEL_RADAR && s->cfg.policy == SDV_POLICY_NONE) {
        return SDV_NO_TRIGGER;                      /* the radar is ignored under the baseline policy */
    }
    if (s->cfg.auth_enabled) {
        if (!mac_ok) {
            s->rejected++;                          /* the frame is discarded; it does not feed the watchdog */
            return SDV_NO_TRIGGER;
        }
        s->last_valid_us = now_us;
        s->watchdog_armed = 1u;
    }
    if (!obstacle || s->detected) {
        return SDV_NO_TRIGGER;
    }
    s->last_us[channel] = now_us;
    s->last_mm[channel] = dist_mm;
    s->have[channel] = 1u;
    if (ttc_at_or_below(dist_mm, speed_mms, s->cfg.ttc_trigger_ms)) {
        s->detected = 1u;
        return (channel == SDV_CHANNEL_SENSOR) ? SDV_TRIGGER_SENSOR : SDV_TRIGGER_RADAR;
    }
    if (s->cfg.policy == SDV_POLICY_DISAGREE && channels_disagree(s, now_us)) {
        s->detected = 1u;
        return SDV_TRIGGER_DISAGREEMENT;
    }
    return SDV_NO_TRIGGER;
}

sdv_trigger_t sdv_on_tick(sdv_state_t *s, uint32_t now_us)
{
    if (s->detected || !s->watchdog_armed) {
        return SDV_NO_TRIGGER;
    }
    if ((uint32_t)(now_us - s->last_valid_us) > s->cfg.watchdog_us) {
        s->detected = 1u;
        return SDV_TRIGGER_WATCHDOG;
    }
    return SDV_NO_TRIGGER;
}

uint8_t sdv_watchdog_armed(const sdv_state_t *s)
{
    return (uint8_t)(s->watchdog_armed && !s->detected);
}
