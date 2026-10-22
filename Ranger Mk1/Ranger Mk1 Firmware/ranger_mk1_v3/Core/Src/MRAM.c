

#include "MRAM.h"

extern SPI_HandleTypeDef hspi1;

#define MRAM_TIMEOUT_MS 1000U
#define CMD_WREN  0x06U
#define CMD_WRDI  0x04U
#define CMD_RDSR  0x05U
#define CMD_WRSR  0x01U
#define CMD_READ  0x03U
#define CMD_WRITE 0x02U
#define CMD_WAKE  0xABU
#define SR_WEL    0x02U
#define SR_BP     0x0CU
#define SR_SRWD   0x80U

static void cs_high(void)
{
    HAL_GPIO_WritePin(GPIOA, GPIO_PIN_4, GPIO_PIN_SET);
    /* Conservative CS-high spacing, including at 170 MHz. */
    for (volatile uint32_t i = 0; i < 16U; ++i) { __NOP(); }
}

static void cs_low(void)
{
    HAL_GPIO_WritePin(GPIOA, GPIO_PIN_4, GPIO_PIN_RESET);
    for (volatile uint32_t i = 0; i < 16U; ++i) { __NOP(); }
}

static HAL_StatusTypeDef command(uint8_t opcode)
{
    cs_low();
    HAL_StatusTypeDef rc = HAL_SPI_Transmit(&hspi1, &opcode, 1U, MRAM_TIMEOUT_MS);
    cs_high();
    return rc;
}

HAL_StatusTypeDef MRAM_ReadStatus(uint8_t *status)
{
    uint8_t tx[2] = {CMD_RDSR, 0x00U};
    uint8_t rx[2] = {0};
    if (status == NULL) return HAL_ERROR;

    cs_low();
    HAL_StatusTypeDef rc = HAL_SPI_TransmitReceive(&hspi1, tx, rx, 2U, MRAM_TIMEOUT_MS);
    cs_high();
    if (rc == HAL_OK) *status = rx[1];
    return rc;
}

static HAL_StatusTypeDef write_enable(void)
{
    uint8_t status;
    HAL_StatusTypeDef rc = command(CMD_WREN);
    if (rc != HAL_OK) return rc;
    rc = MRAM_ReadStatus(&status);
    if (rc != HAL_OK) return rc;
    return (status & SR_WEL) ? HAL_OK : HAL_ERROR;
}

HAL_StatusTypeDef MRAM_Init(void)
{
    uint8_t status;
    uint8_t tx[2] = {CMD_WRSR, 0x00U};
    cs_high();
    HAL_GPIO_WritePin(GPIOA, GPIO_PIN_3, GPIO_PIN_SET); /* /WP inactive */
    HAL_Delay(1U); /* At least 400 us after VDD is valid. */

    HAL_StatusTypeDef rc = command(CMD_WAKE);
    if (rc != HAL_OK) return rc;
    HAL_Delay(1U); /* At least 400 us after WAKE. */

    rc = command(CMD_WRDI);
    if (rc != HAL_OK) return rc;
    rc = MRAM_ReadStatus(&status);
    if (rc != HAL_OK) return rc;
    if (status & SR_WEL) return HAL_ERROR;

    rc = write_enable(); /* WEL must change: catches stuck-high/low MISO. */
    if (rc != HAL_OK) return rc;

    /* Bring-up policy: unprotect all memory, clear SRWD. */
    cs_low();
    rc = HAL_SPI_Transmit(&hspi1, tx, 2U, MRAM_TIMEOUT_MS);
    cs_high();
    HAL_StatusTypeDef disable_rc = command(CMD_WRDI);
    if (rc != HAL_OK) return rc;
    if (disable_rc != HAL_OK) return disable_rc;

    rc = MRAM_ReadStatus(&status);
    if (rc != HAL_OK) return rc;
    return (status & (SR_SRWD | SR_BP | SR_WEL)) ? HAL_ERROR : HAL_OK;
}

HAL_StatusTypeDef MRAM_Read(uint32_t address, uint8_t *data, uint16_t length)
{
    if (data == NULL || length == 0U || address >= MRAM_SIZE_BYTES ||
        (uint32_t)length > MRAM_SIZE_BYTES - address) return HAL_ERROR;

    uint8_t header[4] = {CMD_READ, (uint8_t)(address >> 16),
                        (uint8_t)(address >> 8), (uint8_t)address};
    cs_low();
    HAL_StatusTypeDef rc = HAL_SPI_Transmit(&hspi1, header, 4U, MRAM_TIMEOUT_MS);
    if (rc == HAL_OK) {
        /* Explicit dummy clocks; avoid HAL master-receive buffer semantics. */
        uint8_t dummy[32] = {0};
        uint16_t done = 0U;
        while (done < length && rc == HAL_OK) {
            uint16_t n = (uint16_t)(length - done);
            if (n > sizeof(dummy)) n = (uint16_t)sizeof(dummy);
            rc = HAL_SPI_TransmitReceive(&hspi1, dummy, data + done, n, MRAM_TIMEOUT_MS);
            done = (uint16_t)(done + n);
        }
    }
    cs_high();
    return rc;
}

HAL_StatusTypeDef MRAM_Write(uint32_t address, const uint8_t *data, uint16_t length)
{
    if (data == NULL || length == 0U || address >= MRAM_SIZE_BYTES ||
        (uint32_t)length > MRAM_SIZE_BYTES - address) return HAL_ERROR;

    HAL_StatusTypeDef rc = write_enable();
    if (rc != HAL_OK) return rc;
    uint8_t header[4] = {CMD_WRITE, (uint8_t)(address >> 16),
                        (uint8_t)(address >> 8), (uint8_t)address};
    cs_low();
    rc = HAL_SPI_Transmit(&hspi1, header, 4U, MRAM_TIMEOUT_MS);
    if (rc == HAL_OK) {
        /* G4 HAL takes a mutable pointer but does not modify transmit data. */
        rc = HAL_SPI_Transmit(&hspi1, (uint8_t *)data, length, MRAM_TIMEOUT_MS);
    }
    cs_high();
    /* No erase, page splitting, WIP polling, or write delay required. */
    HAL_StatusTypeDef disable_rc = command(CMD_WRDI);
    return (rc == HAL_OK) ? disable_rc : rc;
}
