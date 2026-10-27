/*
 *  encoder.c
 *
 *  Created on: Oct 23, 2026
 *      Author: Tor Kaufmann Gjerde
 */
#include "encoder.h"
#include "PCAP02.h"
#include <stdint.h>
#include <math.h>
#include <stddef.h>
#include <float.h>
#include "encoder_sector.h"

const encoder_sector_cal_t encoder_sector_cal_20261025 = { .point = {
    { /* sector 0 */
        {970327.834f, 1557877.812f},
        {972274.652f, 1555152.843f},
        {967102.590f, 1558520.691f},
        {961673.363f, 1562000.906f},
        {956981.762f, 1564911.461f},
        {956496.261f, 1567731.252f},
        {960449.204f, 1564569.273f},
        {962231.858f, 1563689.084f},
        {960538.596f, 1569293.406f},
    },
    { /* sector 1 */
        {960538.596f, 1569293.406f},
        {965295.750f, 1567357.993f},
        {962174.974f, 1570258.873f},
        {957238.397f, 1575773.622f},
        {950667.671f, 1578874.402f},
        {947499.086f, 1580562.634f},
        {950961.515f, 1574545.194f},
        {957402.412f, 1563701.124f},
        {962248.755f, 1556846.175f},
    },
    { /* sector 2 */
        {962248.755f, 1556846.175f},
        {965111.934f, 1556330.485f},
        {963014.845f, 1558454.420f},
        {960004.796f, 1562475.579f},
        {953794.227f, 1566479.831f},
        {949682.261f, 1571350.284f},
        {954530.847f, 1566725.258f},
        {962308.170f, 1563350.600f},
        {970327.834f, 1557877.812f},
    },
} };


/**
  * @brief Initialize the two PCAP02 sensors.
  */
int32_t encoder_init(void){

	 pcap_init(0);
	 int32_t result = pcap_init(1);

	 return result;

	 /* Todo: add proper error handling */
}


/**
  * @brief Get the raw sensor data from the two PCAP02 sensors.
  *
  * Uses sensors A and B as per setuo in the encoder_init function
  *
  *  @param[out] raw sensor data in an 14 entry array.
  *
  *  @note the output rad array holds data on the form:
  *        {sector0, ch0, ch1, ch2, ch3, ch4, ch5, sector1, ch11, ch10, ch9, ch8, ch7, ch6}
  *     where channels physical locations are named in hardware
  */
int32_t encoder_get_raw(uint32_t raw[14])
{
    uint32_t temp[14];

    /* Read both PCAPs into a temporary buffer. */
    for (int device = 0; device < 2; ++device)
    {
        for (int channel = 1; channel <= 7; ++channel)
        {
            int32_t value = pcap_read_channel(device, channel);

            if (value < 0)
            {
                return value;
            }

            temp[device * 7 + (channel - 1)] = (uint32_t)value;
        }
    }

    /* Update the output only after all fourteen reads succeed. */
    for (int i = 0; i < 14; ++i)
    {
        raw[i] = temp[i];
    }

    return 0;
}


/**
  * @brief Get the raw sensor data and process it to form an absolute angle on radian form
  *
  * 1. Normalization of each sensing node/electrode data
  *	2. Combination of the twelve electrodes into two different signals S and C.
  * 3. Calculation of fine phase angle using atan.
  * 4. Use sector channels to select the correct 120 degree region.'
  *
  * @param[in]   encoder_cal_t  structure holding the calibration max/min values for each channel.
  * @param[out]  angle_rad      computed angle in radians.
  *
  * @retval 0
  * @retval -1
  */

int32_t encoder_get_angle(const encoder_cal_t *cal, float *angle, uint8_t *sector, uint32_t *raw_data){

	float ch_norm[14];

	int32_t status = encoder_get_raw(raw_data);

	if(status == 0){

		/* All 14 channels are available in the raw_data array for processing
		 *
		 * Start with normalizing all the raw data values with offset and gain */

	    for (uint8_t i = 0; i < 14; ++i)
	    {
	        float minimum = cal->ch_min[i];
	        float maximum = cal->ch_max[i];

	        float ch_offset = (maximum + minimum) * 0.5f;
	        float ch_gain   = (maximum - minimum) * 0.5f;

	        ch_norm[i] = ((float)raw_data[i] - ch_offset) / ch_gain;
	    }

	    /* Next form the differential signals from the 12 sinusoidal channels
	     * Specific channels need to be mapped as implemented in hardware.
	     * From PCAP sensor raw_data[14] = {sector0, ch0, ch1, ch2, ch3, ch4, ch5, sector1, ch11, ch10, ch9, ch8, ch7, ch6}
	     *
	     * sector0 to ch5 comes from sensor A, sector1 to ch11 comes from sensor B
		 *
	     *  sin1 = ch0 + ch6
	     *	sin2 = ch2 + ch8
	     *	sin3 = ch4 + ch10
		 *
	     *	cos1 = ch1 + ch7
	     *	cos2 = ch3 + ch9
	     *	cos3 = ch5 + ch11 */

	    float sin1 = (ch_norm[1] - ch_norm[13]) * 0.5f;
	    float sin2 = (ch_norm[3] - ch_norm[11]) * 0.5f;
	    float sin3 = (ch_norm[5] - ch_norm[9])  * 0.5f;

	    float cos1 = (ch_norm[2] - ch_norm[12]) * 0.5f;
	    float cos2 = (ch_norm[4] - ch_norm[10]) * 0.5f;
	    float cos3 = (ch_norm[6] - ch_norm[8])  * 0.5f;

	    float sin_norm = (sin1 + sin2 + sin3) / 3.0f; /* do we need to change sign on some entries here? - lets test thr waveform! */
	    float cos_norm = (cos1 + cos2 + cos3) / 3.0f;

	    float fine_rad_angle = atan2f(sin_norm, cos_norm);

	    *angle  = fine_rad_angle;
	    *sector = UINT8_MAX;  /* 255 means sector unavailable. */

	    int32_t status = encoder_sector_get(
	        &encoder_sector_cal_20261025,
	        raw_data,
			fine_rad_angle,              /* Existing fine angle: -pi to +pi */
	        sector
	    );


	}
}



int32_t encoder_sector_get(const encoder_sector_cal_t *cal,
                          const uint32_t raw[14],
                          float fine_angle_rad,
                          uint8_t *sector)
{
    if (cal == NULL || raw == NULL || sector == NULL ||
        !isfinite(fine_angle_rad) ||
        fine_angle_rad < -ENCODER_SECTOR_PI - 0.00001f ||
        fine_angle_rad > ENCODER_SECTOR_PI + 0.00001f) {
        return ENCODER_SECTOR_INVALID;
    }

    for (uint32_t i = 0U; i < 14U; ++i) {
        if (raw[i] == 0U || raw[i] > 0x00FFFFFFU) {
            return ENCODER_SECTOR_INVALID;
        }
    }

    /* Per-chip reference correction, using existing fine electrodes.
     * 0.5 * mean(six channels) = sum(six channels) / 12.
     * With valid 24-bit inputs the uint32_t sums cannot overflow. */
    uint32_t sum_a = 0U;
    uint32_t sum_b = 0U;
    for (uint32_t i = 1U; i <= 6U; ++i) {
        sum_a += raw[i];
        sum_b += raw[i + 7U];
    }
    float a = (float)raw[0] - (float)sum_a * (1.0f / 12.0f);
    float b = (float)raw[7] - (float)sum_b * (1.0f / 12.0f);

    /* Permit only the tiny endpoint excess from integer urad conversion. */
    if (fine_angle_rad < -ENCODER_SECTOR_PI) {
        fine_angle_rad = -ENCODER_SECTOR_PI;
    }
    if (fine_angle_rad > ENCODER_SECTOR_PI) {
        fine_angle_rad = ENCODER_SECTOR_PI;
    }
    float position = (fine_angle_rad + ENCODER_SECTOR_PI) *
                     ((float)ENCODER_SECTOR_BINS / ENCODER_SECTOR_TWO_PI);
    uint32_t bin = (uint32_t)position;
    if (bin >= ENCODER_SECTOR_BINS) {
        bin = ENCODER_SECTOR_BINS - 1U;
    }
    float fraction = position - (float)bin;

    float best = FLT_MAX;
    float second = FLT_MAX;
    uint8_t selected = 0U;
    for (uint8_t k = 0U; k < 3U; ++k) {
        float expected_a = cal->point[k][bin][0] + fraction *
            (cal->point[k][bin + 1U][0] - cal->point[k][bin][0]);
        float expected_b = cal->point[k][bin][1] + fraction *
            (cal->point[k][bin + 1U][1] - cal->point[k][bin][1]);
        float ea = a - expected_a;
        float eb = b - expected_b;
        float error = ea * ea + eb * eb;
        if (error < best) {
            second = best;
            best = error;
            selected = k;
        } else if (error < second) {
            second = error;
        }
    }
    if (!isfinite(best) || !isfinite(second)) {
        return ENCODER_SECTOR_INVALID;
    }
    if (best > ENCODER_SECTOR_MAX_ERROR_SQ) {
        return ENCODER_SECTOR_OUT_OF_CALIBRATION;
    }
    if (second - best < ENCODER_SECTOR_MIN_MARGIN_SQ) {
        return ENCODER_SECTOR_AMBIGUOUS;
    }
    *sector = selected;
    return ENCODER_SECTOR_OK;
}
