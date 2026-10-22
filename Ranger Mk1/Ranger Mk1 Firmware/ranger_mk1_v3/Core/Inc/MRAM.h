
#ifndef MRAM_H
#define MRAM_H

#include "stm32g4xx_hal.h"

#define MRAM_SIZE_BYTES 0x20000UL /* 128 KiB: 0x00000..0x1FFFF */

/* Requires initialized SPI1 and PA3/PA4 configured as GPIO outputs.
 * Init deliberately clears nonvolatile block/status write protection.
 * Blocking, single caller only; do not call from interrupts.
 */
HAL_StatusTypeDef MRAM_Init(void);
HAL_StatusTypeDef MRAM_ReadStatus(uint8_t *status);
HAL_StatusTypeDef MRAM_Read(uint32_t address, uint8_t *data, uint16_t length);
HAL_StatusTypeDef MRAM_Write(uint32_t address, const uint8_t *data, uint16_t length);

#endif
