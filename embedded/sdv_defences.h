/*
 * sdv_defences.h - the perception-side defences of the emulated brake chain, as portable C99.
 *
 * What it implements (the same logic as sdv/system/brake_chain.py, in integers):
 *   - trigger on a reported time-to-collision at or below a threshold, from the primary sensor and, with
 *     a failover policy, from the redundant radar (OR voting)
 *   - an optional precautionary trigger when the two channels disagree
 *   - message authentication hook: a frame whose MAC check failed is rejected (the MAC itself is NOT computed here;
 *     in the design it is delegated to a hardware security module and the caller passes the verdict)
 *   - a fail-safe watchdog: no accepted frame on any channel for watchdog_us -> trigger
 *
 * Constraints kept on purpose, so the footprint figures mean something on a small MCU:
 *   fixed-width integers only, no floating point, no malloc, no recursion, no loops, no global state, no libc calls.
 * Timestamps are 32-bit microseconds and compared with wrap-safe signed differences (valid for gaps below ~35 minutes).
 *
 * This is a feasibility artefact. It has NOT been run on a microcontroller, and it is not a certified implementation.
 */
#ifndef SDV_DEFENCES_H
#define SDV_DEFENCES_H

#include <stdint.h>

typedef enum {
    SDV_NO_TRIGGER = 0,
    SDV_TRIGGER_SENSOR = 1,
    SDV_TRIGGER_RADAR = 2,
    SDV_TRIGGER_DISAGREEMENT = 3,
    SDV_TRIGGER_WATCHDOG = 4
} sdv_trigger_t;

typedef enum {
    SDV_POLICY_NONE = 0,        /* primary sensor only; radar frames are ignored */
    SDV_POLICY_RADAR_OR = 1,    /* either channel can trigger */
    SDV_POLICY_DISAGREE = 2     /* radar_or plus a precautionary trigger on disagreement */
} sdv_policy_t;

#define SDV_CHANNEL_SENSOR 0u
#define SDV_CHANNEL_RADAR 1u

typedef struct {
    uint8_t policy;                 /* sdv_policy_t */
    uint8_t auth_enabled;           /* reject frames whose MAC check failed; arm the watchdog */
    int32_t ttc_trigger_ms;         /* trigger when distance / speed <= this (default 2000) */
    int32_t disagree_tol_mm;        /* default 3000 */
    uint32_t disagree_fresh_us;     /* both observations must be this recent (default 30000) */
    uint32_t watchdog_us;           /* silence limit (default 30000) */
    uint32_t watchdog_check_us;     /* the caller calls sdv_on_tick at this period (default 5000) */
} sdv_config_t;

typedef struct {
    sdv_config_t cfg;
    uint32_t last_us[2];            /* per channel: arrival time of the last observation of an obstacle */
    int32_t last_mm[2];             /* per channel: its distance */
    uint8_t have[2];
    uint8_t detected;               /* a trigger already fired */
    uint8_t watchdog_armed;
    uint32_t last_valid_us;         /* last accepted frame of either channel */
    uint32_t rejected;              /* frames rejected by the authentication check */
} sdv_state_t;

void sdv_config_default(sdv_config_t *cfg);
void sdv_init(sdv_state_t *s, const sdv_config_t *cfg);

/*
 * One received sensor or radar frame. dist_mm and speed_mms are the reported values (valid when obstacle != 0).
 * mac_ok is the authentication verdict (1 = genuine). Returns the trigger source if this frame starts the braking chain.
 */
sdv_trigger_t sdv_on_frame(sdv_state_t *s, uint8_t channel, uint32_t now_us, int32_t dist_mm, int32_t speed_mms,
                           uint8_t obstacle, uint8_t mac_ok);

/* Watchdog check, called every cfg.watchdog_check_us once armed. Returns SDV_TRIGGER_WATCHDOG on silence. */
sdv_trigger_t sdv_on_tick(sdv_state_t *s, uint32_t now_us);

/* 1 once the watchdog needs ticks (the first accepted frame arrived with authentication on). */
uint8_t sdv_watchdog_armed(const sdv_state_t *s);

#endif /* SDV_DEFENCES_H */
