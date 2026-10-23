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

int32_t encoder_get_angle(const encoder_cal_t *cal, float *angle_rad){

	uint32_t raw_data[14];

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

	    *angle_rad =  fine_rad_angle; /* returns angle on the form -pi to + pi */
	}
	return status;
}
