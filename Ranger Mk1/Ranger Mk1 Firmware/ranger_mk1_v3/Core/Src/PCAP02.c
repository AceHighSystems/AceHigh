

/*
 *  PCAP02.c
 *
 *  Created on: Oct 16, 2026
 *      Author: Tor Kaufmann Gjerde
 */

#include "PCAP02.h"
#include "main.h"
#include "stm32g4xx_hal.h"
#include "pcap02_standard_fw.h"


extern SPI_HandleTypeDef hspi3;


/* =========================
   PCAP02 Prototyping
   ========================= */
static int32_t pcap_load_firmware(int8_t pcap_nbr)
{

    uint8_t tx[3];
    uint8_t rx[3];
    HAL_StatusTypeDef status;

    /* Deselect PCAP_A and PCAP_B. */
    HAL_GPIO_WritePin(GPIOB,
                     GPIO_PIN_6 | GPIO_PIN_7,
                     GPIO_PIN_SET);

    uint16_t cs_pcap = GPIO_PIN_6;

    if (pcap_nbr == 1){
		cs_pcap = GPIO_PIN_7;
    }


    /* Stop PCAP: configuration register 77, RunBit = 0. */
    tx[0] = 0xC0;
    tx[1] = 0x4D;
    tx[2] = 0x00;

    HAL_GPIO_WritePin(GPIOB, cs_pcap, GPIO_PIN_RESET);
    status = HAL_SPI_TransmitReceive(&hspi3, tx, rx, 3, 100);
    HAL_GPIO_WritePin(GPIOB, cs_pcap, GPIO_PIN_SET);

    if (status != HAL_OK)
        return -1;

    HAL_Delay(2);

    /* Upload all 4096 bytes to SRAM addresses 0x000..0xFFF. */
    for (uint32_t address = 0; address < sizeof(pcap02_standard_fw); ++address)
    {
        tx[0] = (uint8_t)(0x90U | (address >> 8));
        tx[1] = (uint8_t)address;
        tx[2] = pcap02_standard_fw[address];

        HAL_GPIO_WritePin(GPIOB, cs_pcap, GPIO_PIN_RESET);
        status = HAL_SPI_TransmitReceive(&hspi3, tx, rx, 3, 100);
        HAL_GPIO_WritePin(GPIOB, cs_pcap, GPIO_PIN_SET);

        if (status != HAL_OK)
            return -2;
    }

    /* Read the entire image back and compare every byte. */
    for (uint32_t address = 0;
         address < sizeof(pcap02_standard_fw);
         ++address)
    {
        tx[0] = (uint8_t)(0x10U | (address >> 8));
        tx[1] = (uint8_t)address;
        tx[2] = 0x00;

        HAL_GPIO_WritePin(GPIOB, cs_pcap, GPIO_PIN_RESET);
        status = HAL_SPI_TransmitReceive(&hspi3, tx, rx, 3, 100);
        HAL_GPIO_WritePin(GPIOB, cs_pcap, GPIO_PIN_SET);

        if (status != HAL_OK)
            return -3;

        if (rx[2] != pcap02_standard_fw[address])
            return -(int32_t)(1000U + address);
    }

    /* Entire image verified. Leave converter/DSP stopped. */
    return (int32_t)sizeof(pcap02_standard_fw);
}



/* ============================================================
 * PCAP initialization pcap_nbr sets the correct IC chip select on the SPI bus
 * 0 = PCAP02_0 Ch0 to ch6
 * 1 = PCAP02_1 Ch7 to ch13
 *
 * ============================================================
 */

int32_t pcap_init(int8_t pcap_nbr)
{
	uint16_t cs_pcap = GPIO_PIN_6;

    if (pcap_nbr == 1){
		cs_pcap = GPIO_PIN_7;
    }


	int32_t result = pcap_load_firmware(pcap_nbr);
	if (result < 0)
	    return result;
    /*
     * Registers 0..76.
     * Unspecified entries are zero.
     */
    static const uint8_t cfg[77] = {
        [0]  = 0xFF,  // Disable OTP autoboot; allow SRAM readback
        [1]  = 0x00,  // OTP ECC disabled
        [2]  = 0x41,  // SPI collision avoidance; SRAM/OTP compare off

        [3]  = 0x94,  // Internal low-frequency oscillator
        [4]  = 0x80,  // External oscillator disabled
        [5]  = 0x05,
        [6]  = 0x01,  // Internal high-frequency clock
        [7]  = 0x14,  // Ordinary capacitors; sense inversion enabled
        [8]  = 0xA8,  // Internal 30 kohm discharge resistors
        [9]  = 0x00,
        [10] = 0x10,  // Grounded, external reference, internal compensation
        [11] = 0x00,  // CDC cycle clock = internal low-frequency clock

		[12] = 0xFF,  // Enable PC0 reference + PC1 + PC2
		[13] = 0x40,  // Average 64 measurements
        [14] = 0x00,

        [17] = 0xC4,  // Conversion timer = 2500 = 0x0009C4
        [18] = 0x09,  // Approximately 100 ms with 50 kHz OLF
        [19] = 0x00,

        [23] = 0x02,  // Discharge interval
        [24] = 0x08,  // CDC triggered by conversion timer
        [25] = 0x01,  // Precharge interval
        [26] = 0x00,
        [27] = 0x02,  // Full-charge interval
        [28] = 0x20,  // EEPROM disabled; writes disabled

        [29] = 0x00,  // Temperature conversion trigger disabled
        [30] = 0x01,
        [34] = 0x00,  // Temperature ports disabled
        [35] = 0x05,

        [38] = 0x50,  // Vendor standard TDC setting
        [40] = 0x00,  // DSP uses internal ring oscillator
        [41] = 0x00,  // Watchdog disabled for bring-up
        [43] = 0x41,  // Execute SRAM; trigger DSP at end of CDC
        [45] = 0x00,  // PWM/PDM outputs disabled
        [46] = 0xFF,  // Vendor standard GPIO setting
        [48] = 0x27,  // Vendor standard TDC/bandgap settings
        [49] = 0x30,

        [73] = 0x28,  // PARA7: vendor standard gain compensation
        [74] = 0x01   // PARA8: vendor standard bandgap trigger flag
    };

    uint8_t tx[79] = {0};
    uint8_t rx[79] = {0};
    HAL_StatusTypeDef status;

    HAL_GPIO_WritePin(GPIOB, GPIO_PIN_6 | GPIO_PIN_7, GPIO_PIN_SET);

    /* Stop converter/DSP before configuring. */
    tx[0] = 0xC0;
    tx[1] = 77;
    tx[2] = 0;

    HAL_GPIO_WritePin(GPIOB, cs_pcap, GPIO_PIN_RESET);
    status = HAL_SPI_TransmitReceive(&hspi3, tx, rx, 3, 100);
    HAL_GPIO_WritePin(GPIOB, cs_pcap, GPIO_PIN_SET);

    if (status != HAL_OK)
        return -1;

    HAL_Delay(2);

    /* Write registers 0..76 in one transaction. */
    tx[0] = 0xC0;
    tx[1] = 0x00;

    for (uint32_t i = 0; i < sizeof(cfg); ++i)
        tx[i + 2] = cfg[i];

    HAL_GPIO_WritePin(GPIOB, cs_pcap, GPIO_PIN_RESET);
    status = HAL_SPI_TransmitReceive(&hspi3, tx, rx,
                                    sizeof(tx), 100);
    HAL_GPIO_WritePin(GPIOB, cs_pcap, GPIO_PIN_SET);

    if (status != HAL_OK)
        return -2;

    /* Enable converter/DSP. */
    tx[0] = 0xC0;
    tx[1] = 77;
    tx[2] = 1;

    HAL_GPIO_WritePin(GPIOB, cs_pcap, GPIO_PIN_RESET);
    status = HAL_SPI_TransmitReceive(&hspi3, tx, rx, 3, 100);
    HAL_GPIO_WritePin(GPIOB, cs_pcap, GPIO_PIN_SET);

    if (status != HAL_OK)
        return -3;

    /* Initialize, then start CDC. These are separate transactions.
     * 0x8A is Initialize, NOT the 0x88 power-on reset.
     */
    const uint8_t commands[2] = {0x8A, 0x8C};

    for (uint32_t i = 0; i < 2; ++i) {
        tx[0] = commands[i];

        HAL_GPIO_WritePin(GPIOB, cs_pcap, GPIO_PIN_RESET);
        status = HAL_SPI_TransmitReceive(&hspi3, tx, rx, 1, 100);
        HAL_GPIO_WritePin(GPIOB, cs_pcap, GPIO_PIN_SET);

        if (status != HAL_OK)
            return -(int32_t)(4U + i);

        HAL_Delay(2);
    }

    return 0;
}

/* ============================================================
 * PCAP channel read out
 * ============================================================
 */
int32_t pcap_read_channel(int8_t pcap_nbr, int channel)
{
	uint16_t cs_pcap = GPIO_PIN_6;


    if (pcap_nbr == 1){
		cs_pcap = GPIO_PIN_7;
    }

    if (channel < 1 || channel > 7)
        return -13;

    uint8_t tx[5] = {0x40, 0x18, 0, 0, 0};
    uint8_t rx[5] = {0};
    HAL_StatusTypeDef status;

    HAL_GPIO_WritePin(GPIOB, GPIO_PIN_6 | GPIO_PIN_7, GPIO_PIN_SET);

    /* Read hardware status bytes at addresses 24..26. */
    HAL_GPIO_WritePin(GPIOB, cs_pcap, GPIO_PIN_RESET);
    status = HAL_SPI_TransmitReceive(&hspi3, tx, rx, 5, 100);
    HAL_GPIO_WritePin(GPIOB, cs_pcap, GPIO_PIN_SET);

    if (status != HAL_OK)
        return -10;

    if ((rx[2] & 0x01U) == 0)
        return -11;  // Converter is stopped

    uint32_t errors =
        ((uint32_t)(rx[3] & 0x0FU) << 8) | rx[4];

    if (errors != 0)
        return -(int32_t)(1000U + errors);

    /*
     * Res1..Res7 = C1/C0..C7/C0.
     * Each result occupies three bytes:
     * PC1: 3..5, PC2: 6..8, ... PC7: 21..23.
     */
    tx[1] = (uint8_t)(3 * channel);

    HAL_GPIO_WritePin(GPIOB, cs_pcap, GPIO_PIN_RESET);
    status = HAL_SPI_TransmitReceive(&hspi3, tx, rx, 5, 100);
    HAL_GPIO_WritePin(GPIOB, cs_pcap, GPIO_PIN_SET);

    if (status != HAL_OK)
        return -12;

    return (int32_t)(
        ((uint32_t)rx[2])       |
        ((uint32_t)rx[3] << 8)  |
        ((uint32_t)rx[4] << 16)
    );
}
