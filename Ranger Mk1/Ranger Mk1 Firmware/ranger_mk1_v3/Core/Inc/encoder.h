/*
 *  encoder.h
 *
 *  Created on: Oct 23, 2026
 *      Author: Tor Kaufmann Gjerde
 */


#ifndef INC_ENCODER_H_
#define INC_ENCODER_H_

#include <stdint.h>

/**
 * @brief Per-channel calibration limits used for encoder normalization.
 * @note Each ch_max[i] must be greater than ch_min[i].
 */
typedef struct
{
    float ch_max[14];
    float ch_min[14];

} encoder_cal_t;


int32_t encoder_init(void);

int32_t encoder_get_angle(const encoder_cal_t *cal, float *angle, uint8_t *sector, uint32_t *raw_data);


#endif
