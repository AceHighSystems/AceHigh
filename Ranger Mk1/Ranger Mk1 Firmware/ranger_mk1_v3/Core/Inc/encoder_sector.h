

#ifndef ENCODER_SECTOR_H
#define ENCODER_SECTOR_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define ENCODER_SECTOR_BINS 8U
#define ENCODER_SECTOR_PI 3.14159265358979323846f
#define ENCODER_SECTOR_TWO_PI 6.28318530717958647692f

#define ENCODER_SECTOR_MIN_MARGIN_SQ 3000000.0f
#define ENCODER_SECTOR_MAX_ERROR_SQ  6250000.0f

typedef struct {
    /* Rows: sector 0..2. Knots: fine phase -pi..+pi, including both ends.
     * Last knot of each row equals first knot of the following sector. */
    float point[3][ENCODER_SECTOR_BINS + 1U][2];
} encoder_sector_cal_t;

enum {
    ENCODER_SECTOR_OK = 0,
    ENCODER_SECTOR_INVALID = -10,
    ENCODER_SECTOR_AMBIGUOUS = -11,
    ENCODER_SECTOR_OUT_OF_CALIBRATION = -12
};

extern const encoder_sector_cal_t encoder_sector_cal_20261024;

/**
 * @brief Decode the absolute branch from one current measurement vector.
 * @param cal 				Assembly-specific calibration (216 bytes).
 * @param raw ch0..ch13,	from the same encoder scan used for fine_angle_rad.
 * @param fine_angle_rad 	Existing fine phase, approximately -pi..+pi radians.
 * @param sector 			Written with 0, 1 or 2 only on ENCODER_SECTOR_OK.
 * @return					OK, INVALID, AMBIGUOUS, or OUT_OF_CALIBRATION.
 *
 * No history, commanded motion, direction, homing, allocation or delay.
 * Callers must not publish a new absolute angle when this returns an error.
 */
int32_t encoder_sector_get(const encoder_sector_cal_t *cal,
                          const uint32_t raw[14],
                          float fine_angle_rad,
                          uint8_t *sector);

#ifdef __cplusplus
}
#endif
#endif
