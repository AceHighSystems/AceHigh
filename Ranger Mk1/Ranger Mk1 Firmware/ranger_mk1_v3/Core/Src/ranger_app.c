/*
 * ranger_app.c
 *
 *  Created on: Apr 28, 2026
 *      Author: Tor Kaufmann Gjerde
 *
 *  Description:
 *  Ranger application layer.
*/
#include "main.h"
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <math.h>
#include "ranger_can.h"
#include "ranger_param.h"
#include "ranger_app.h"
#include "DRV8462.h"
#include "INA229.h"
#include "encoder.h"
#include "MRAM.h"
#include "PCAP02.h"


/* =========================
   Application state
   ========================= */
/* TIM3 CH3 generates STEP; TIM2 counts TIM3 OC3REF rising edges. */
extern TIM_HandleTypeDef htim2;
extern TIM_HandleTypeDef htim3;

static volatile bool step_move_complete = false;
static volatile bool step_move_active = false;

/* Remaining timeout is 64-bit to support long, slow moves. */
static uint64_t step_move_timeout_remaining_ms = 0U;
static uint32_t step_move_last_tick = 0U;
static uint8_t dir_old = 0U;

/* Current state of LED on PA1 (exposed via parameter interface) */
static uint8_t led_pa1_state = 0U;
/* Uptime counter in seconds */
static uint32_t uptime_s = 0U;
/* sensor measurements */
int32_t current;
/* Timing references (ms) */
static uint32_t last_uptime_ms = 0U;
static uint32_t last_heartbeat_ms = 0U;
static uint32_t last_blink_ms = 0U;
static uint32_t last_sens_ms = 0;
static uint32_t last_slow_sens_ms = 0;

/* MRAM test references */
#define MRAM_TEST_ADDRESS  0x000000UL

static uint32_t last_mram_write_ms = 0U;
static uint32_t last_mram_read_ms  = 0U;

/* Available for inspection in the debugger. */
static volatile HAL_StatusTypeDef mram_init_result  = HAL_ERROR;
static volatile HAL_StatusTypeDef mram_write_result = HAL_ERROR;
static volatile HAL_StatusTypeDef mram_read_result  = HAL_ERROR;
/* Global helper */

/* Replace the comments with all 14 measured values per array.
{sector0, ch0, ch1, ch2, ch3, ch4, ch5, sector1, ch11, ch10, ch9, ch8, ch7, ch6}
*/
static const encoder_cal_t encoder_cal =
{
    .ch_max = {
        3210449, 5337679, 4547566, 4981811,
        4102258, 4419746, 3912183, 3781551,
        4660794, 5146233, 4416821, 4767150,
        3766631, 4267547
    },

    .ch_min = {
        3196261, 5167109, 4421927, 4840197,
        3987906, 4283191, 3794032, 3759819,
        4486354, 4891741, 4217246, 4550988,
        3635845, 4128629
    }
};


/* =========================
   Internal helpers
   ========================= */
/**
 * @brief Set LED on PA1 and update internal state
 *
 * This is the only place that should directly control the LED.
 * Keeps hardware control and parameter state in sync.
 */
static void ranger_app_set_led_pa1(uint8_t state);
/**
 * @brief local application functions
 */
static void ranger_app_check_reset(void);
static void ranger_app_check_mode(void);
static void ranger_app_check_step_move(void);
static void ranger_step_move(int32_t steps);
static void ranger_app_check_step_status(void);
static void ranger_stop_step_timers(void);
/* =========================
   Implementation
   ========================= */
static void ranger_app_set_led_pa1(uint8_t state)
{
  if (state != 0U)
  {
    HAL_GPIO_WritePin(GPIOA, GPIO_PIN_1, GPIO_PIN_SET);
    led_pa1_state = 1U;
  }
  else
  {
    HAL_GPIO_WritePin(GPIOA, GPIO_PIN_1, GPIO_PIN_RESET);
    led_pa1_state = 0U;
  }
}


void ranger_app_init(void)
{
  /* Ensure known GPIO states for LED */
  HAL_GPIO_WritePin(GPIOA, GPIO_PIN_0, GPIO_PIN_RESET);
  HAL_GPIO_WritePin(GPIOA, GPIO_PIN_1, GPIO_PIN_RESET);
  /* Ensure known GPIO states for stepper stepper driver IC */
  HAL_GPIO_WritePin(DIR_DRV_GPIO_Port, DIR_DRV_Pin, GPIO_PIN_RESET); // DRV8462 Set direction pin
  HAL_GPIO_WritePin(GPIOB, MODE_DRV_Pin | CS_DRV_Pin, GPIO_PIN_SET); // DRV8462 Mode pin high for SPI mode

  HAL_Delay(2);
  HAL_GPIO_WritePin(GPIOB, SLEEP_DRV_Pin, GPIO_PIN_SET); // DRV8462 nSLEEP high to disable sleep
  HAL_Delay(2);

  /* Initialize Ranger CAN with AceLight protocol */
  ranger_can_init();
  ranger_app_set_led_pa1(0U);

  /* Enable Power to the encoder board*/
  HAL_GPIO_WritePin(ENABLE_ENC_GPIO_Port, ENABLE_ENC_Pin, GPIO_PIN_RESET); // logic low turns PMOS On.
  HAL_Delay(2000);

  /* Initialize peripheral drivers*/
  drv8462_init();
  ina229_init();
  encoder_init();
  ina229_init();
  mram_init_result = MRAM_Init();


  uptime_s = 0U;
  uint32_t now = HAL_GetTick();
  last_uptime_ms = now;
  last_heartbeat_ms = now;
  last_blink_ms = now;
}


void ranger_app_tick(void)
{
  uint32_t now = HAL_GetTick();
  /* Update uptime every 1 second */
  if ((now - last_uptime_ms) >= 1000U)
  {
    last_uptime_ms += 1000U;
    uptime_s++;
  }
  /* Blink LED on PA0 as "alive" indicator */
  if ((now - last_blink_ms) >= 250U)
  {
	last_blink_ms += 250U;
    HAL_GPIO_TogglePin(GPIOA, GPIO_PIN_0);
  }

  /* Tasks scheduled to run max freq */
  ranger_app_check_reset();
  ranger_app_check_mode();
  ranger_app_check_step_status();
  ranger_app_check_step_move();


  /* Tasks scheduled to run every x miliseconds */
  if ((now - last_slow_sens_ms) >=250U)
  {
      last_slow_sens_ms = now;

      g_param.current = (int32_t)(ina229_read_current()* 1000.0f);
      g_param.voltage = (int32_t)(ina229_read_volt() * 1000.0f);
      g_param.temperature = (int32_t)ina229_read_temp();
  }

  /* Tasks scheduled to run every x miliseconds */
  if ((now - last_sens_ms) >=15U)
  {
      last_sens_ms = now;


      float angle_rad;
      uint8_t angle_sector;
      uint32_t raw_data[14];

      int32_t status = encoder_get_angle(&encoder_cal, &angle_rad, &angle_sector, raw_data);

      g_param.debug = status;
      g_param.angle = (int32_t)lroundf(angle_rad * 1000000.0f);
      g_param.sector =  angle_sector;

      g_param.ch0 = raw_data[0];
      g_param.ch1 = raw_data[1];
      g_param.ch2 = raw_data[2];
      g_param.ch3 = raw_data[3];
      g_param.ch4 = raw_data[4];
      g_param.ch5 = raw_data[5];
      g_param.ch6 = raw_data[6];
      g_param.ch7 = raw_data[7];
      g_param.ch8 = raw_data[8];
      g_param.ch9 = raw_data[9];
      g_param.ch10 = raw_data[10];
      g_param.ch11 = raw_data[11];
      g_param.ch12 = raw_data[12];
      g_param.ch13 = raw_data[13];


  }
/**

  if (mram_init_result == HAL_OK)
  {
      //Every 3 seconds: read MRAM and update the parameter.
      if ((uint32_t)(now - last_mram_read_ms) >= 3000U)
      {
          last_mram_read_ms = now;

          uint32_t value;

          mram_read_result = MRAM_Read(MRAM_TEST_ADDRESS, (uint8_t *)&value, sizeof(value));

          // Keep the existing parameter value if the SPI read fails.
          if (mram_read_result == HAL_OK)
          {
              g_param.test = value;
          }
      }
  }

  if (mram_init_result == HAL_OK)
  {
	 //Every 5 seconds: write the current parameter value to MRAM.
	 if ((uint32_t)(now - last_mram_write_ms) >= 5000U)
	 {
	     last_mram_write_ms = now;

	     uint32_t value = g_param.test;

	     mram_write_result = MRAM_Write(MRAM_TEST_ADDRESS, (const uint8_t *)&value, sizeof(value));
	    }
  }

  */
}



static void ranger_app_check_reset(void)
{
	if(g_param.reset == 1)
	{
		NVIC_SystemReset();
	}
}


static void ranger_app_check_mode(void)
{
	if(g_param.mode == 0)
	{
		HAL_GPIO_WritePin(ENABLE_DRV_GPIO_Port, ENABLE_DRV_Pin, GPIO_PIN_RESET);
	}
	if(g_param.mode == 1)
	{
		HAL_GPIO_WritePin(ENABLE_DRV_GPIO_Port, ENABLE_DRV_Pin, GPIO_PIN_SET);
	}
}


static void ranger_app_check_step_move(void)
{
    int32_t requested_steps;
    /*
     * g_param.step_move acts as a one-command mailbox.
     */
    if (g_param.step_move == 0)
    {
        return;
    }
    /*
     * Leave the command in the mailbox while a move is active.
     *
     * This creates a one-command pending queue:
     * the command will start after the current move completes.
     *
     * A later CAN write before completion will overwrite the pending
     * command with the newest value.
     */
    if (step_move_active)
    {
        return;
    }
    /*
     * Copy the command before clearing the mailbox.
     */
    requested_steps = g_param.step_move;
    g_param.step_move = 0;
    /*
     * This function starts the move and returns immediately.
     */
    ranger_step_move(requested_steps);
}


/*
 * Called with interrupts masked, or from the TIM2 completion callback.
 * Freeze PWM first, so no further rising edges can be generated while
 * HAL performs its bookkeeping. If STEP froze high, hold it for at least
 * 3 us before forcing OC3REF low; this avoids truncating the final pulse.
 * The short NOP loop uses SystemCoreClock and does not depend on SysTick.
 */
static void ranger_stop_step_timers(void)
{
    CLEAR_BIT(htim3.Instance->CR1, TIM_CR1_CEN);
    __DSB();

    if (__HAL_TIM_GET_COUNTER(&htim3) <
        __HAL_TIM_GET_COMPARE(&htim3, TIM_CHANNEL_3))
    {
        uint32_t cycles = (uint32_t)
            (((uint64_t)SystemCoreClock * 3ULL + 999999ULL) / 1000000ULL);
        while (cycles != 0U)
        {
            __NOP();
            --cycles;
        }
    }

    /* CCR3 is unbuffered in the supplied MX_TIM3_Init(). */
    __HAL_TIM_SET_COMPARE(&htim3, TIM_CHANNEL_3, 0U);
    (void)HAL_TIM_PWM_Stop(&htim3, TIM_CHANNEL_3);
    (void)HAL_TIM_Base_Stop_IT(&htim2);
    __HAL_TIM_CLEAR_FLAG(&htim2, TIM_FLAG_UPDATE);
}



static void ranger_app_check_step_status(void)
{
    if (!step_move_active)
    {
        return;
    }

    if (step_move_complete)
    {
        step_move_complete = false;
        step_move_active = false;
        step_move_timeout_remaining_ms = 0U;
        return;
    }

    uint32_t now = HAL_GetTick();
    uint32_t elapsed_ms = now - step_move_last_tick;
    step_move_last_tick = now;

    if ((uint64_t)elapsed_ms >= step_move_timeout_remaining_ms)
    {
        uint32_t primask = __get_PRIMASK();
        __disable_irq();
        ranger_stop_step_timers();
        step_move_complete = false;
        step_move_active = false;
        step_move_timeout_remaining_ms = 0U;
        __set_PRIMASK(primask);
        /* Add a motion-timeout fault here if the parameter table supports it. */
    }
    else
    {
        step_move_timeout_remaining_ms -= elapsed_ms;
    }
}



static void ranger_set_step_dir(uint8_t dir)
{
    /*
     * Normalize any nonzero value to one.
     */
    dir = (dir != 0U) ? 1U : 0U;
    if (dir == dir_old)
    {
        return;
    }
    if (dir == 0U)
    {
        HAL_GPIO_WritePin(DIR_DRV_GPIO_Port, DIR_DRV_Pin, GPIO_PIN_RESET);
    }
    else
    {
        HAL_GPIO_WritePin(DIR_DRV_GPIO_Port, DIR_DRV_Pin, GPIO_PIN_SET);
    }
    dir_old = dir;
}
/**
 * Start a non-blocking finite move, using the supplied CubeMX configuration:
 *
 *   TIM3 CH3: PWM1, active high, TRGO = OC3REF, internal clock.
 *   TIM2:    external clock mode 1, ITR2 = TIM3 TRGO, prescaler = 0.
 *
 * TIM2 counts the complete command without pulse chunking. It must have
 * its NVIC interrupt enabled, and TIM2_IRQHandler() must call
 * HAL_TIM_IRQHandler(&htim2). This file owns HAL_TIM_PeriodElapsedCallback.
 *
 * Stopping is interrupt-driven, not hardware-gated. Exact finite counts
 * require worst-case TIM2 interrupt latency to be shorter than one STEP
 * period. Validate at the intended speed under CAN/sensor interrupt load.
 */
static void ranger_step_move(int32_t steps)
{
    const uint32_t nominal_counter_hz = 1000000U;
    const uint32_t max_step_hz = 500000U;
    uint32_t pulse_count;
    uint32_t pulse_frequency_hz;
    uint32_t timer_clock_hz;
    uint32_t prescaler_div;
    uint32_t period_ticks;
    uint32_t high_ticks;
    uint64_t divisor;
    uint64_t move_cycles;
    uint64_t expected_move_ms;
    uint32_t primask;
    HAL_StatusTypeDef status;

    if ((steps == 0) || step_move_active)
    {
        return;
    }

    pulse_frequency_hz = g_param.profile_velocity;
    if (pulse_frequency_hz == 0U)
    {
        return;
    }
    if (pulse_frequency_hz > max_step_hz)
    {
        pulse_frequency_hz = max_step_hz;
    }

    /* TIM3 is on APB1: timer clock doubles when APB1 is prescaled.
     * Supplied clock tree: PCLK1 = TIM3 clock = 170 MHz.
     */
    timer_clock_hz = HAL_RCC_GetPCLK1Freq();
    if ((RCC->CFGR & RCC_CFGR_PPRE1) != 0U)
    {
        timer_clock_hz *= 2U;
    }
    if (timer_clock_hz == 0U)
    {
        return;
    }

    /* Normally PSC = 169 gives a 1 MHz tick. Increase the divider for
     * slow moves so that TIM3's 16-bit ARR cannot overflow. Frequency
     * commands are integer pulses/second; this supports down to 1 Hz.
     */
    prescaler_div = (uint32_t)(((uint64_t)timer_clock_hz + nominal_counter_hz - 1ULL) / nominal_counter_hz);
    divisor = (uint64_t)pulse_frequency_hz * 65536ULL;
    uint32_t slow_div = (uint32_t)(((uint64_t)timer_clock_hz + divisor - 1ULL) / divisor);

    if (slow_div > prescaler_div)
    {
        prescaler_div = slow_div;
    }
    if ((prescaler_div == 0U) || (prescaler_div > 65536U))
    {
        return;
    }

    divisor = (uint64_t)prescaler_div * pulse_frequency_hz;
    period_ticks = (uint32_t)(((uint64_t)timer_clock_hz + divisor / 2ULL) / divisor);

    if (period_ticks < 2U)
    {
        period_ticks = 2U;
    }
    if (period_ticks > 65536U)
    {
        return;
    }

    /* Nominal 3 us high time, rounded up to a timer tick. At high rates,
     * shorten it to half the period, preserving at least one low tick.
     */
    divisor = (uint64_t)prescaler_div * 1000000ULL;
    high_ticks = (uint32_t)(((uint64_t)timer_clock_hz * 3ULL + divisor - 1ULL) / divisor);

    if (high_ticks >= period_ticks)
    {
        high_ticks = period_ticks / 2U;
    }
    if (high_ticks == 0U)
    {
        high_ticks = 1U;
    }

    /* Unsigned subtraction safely handles INT32_MIN. */
    pulse_count = (steps > 0) ? (uint32_t)steps : 0U - (uint32_t)steps;

    /* Use actual divider and period for timing. Divide before multiplying
     * by 1000 to avoid overflow for long moves at very low frequencies.
     */
    move_cycles = (uint64_t)pulse_count * period_ticks * prescaler_div;
    expected_move_ms = (move_cycles / timer_clock_hz) * 1000ULL;
    expected_move_ms += (((move_cycles % timer_clock_hz) * 1000ULL) + timer_clock_hz - 1ULL) / timer_clock_hz;

    primask = __get_PRIMASK();
    __disable_irq();
    ranger_stop_step_timers();
    ranger_set_step_dir((steps > 0) ? 1U : 0U);

    /* Keep OC3REF low throughout setup. TIM2 remains stopped until all
     * software update events and PWM register changes are complete.
     */
    __HAL_TIM_SET_PRESCALER(&htim3, prescaler_div - 1U);
    __HAL_TIM_SET_AUTORELOAD(&htim3, period_ticks - 1U);
    __HAL_TIM_SET_COMPARE(&htim3, TIM_CHANNEL_3, 0U);
    htim3.Instance->EGR = TIM_EGR_UG;

    /* Start in the LOW part of PWM1. The first real rising edge occurs
     * at the next rollover, after both counters and the output are armed.
     */
    __HAL_TIM_SET_COUNTER(&htim3, high_ticks);
    __HAL_TIM_SET_COMPARE(&htim3, TIM_CHANNEL_3, high_ticks);
    __HAL_TIM_CLEAR_FLAG(&htim3, TIM_FLAG_UPDATE | TIM_FLAG_CC3);

    /* ARR = N and CNT = 1 overflow on the Nth input edge. Unlike
     * ARR = N-1, this also handles N = 1 without writing ARR = 0,
     * which blocks the STM32 timer counter.
     */
    __HAL_TIM_SET_AUTORELOAD(&htim2, pulse_count);
    htim2.Instance->EGR = TIM_EGR_UG;
    __HAL_TIM_SET_COUNTER(&htim2, 1U);
    __HAL_TIM_CLEAR_FLAG(&htim2, TIM_FLAG_UPDATE);
    HAL_NVIC_ClearPendingIRQ(TIM2_IRQn);

    step_move_complete = false;
    step_move_active = true;
    step_move_timeout_remaining_ms = expected_move_ms + 100ULL;
    step_move_last_tick = HAL_GetTick();

    status = HAL_TIM_Base_Start_IT(&htim2);

    if (status == HAL_OK)
    {
        status = HAL_TIM_PWM_Start(&htim3, TIM_CHANNEL_3);
    }
    if (status != HAL_OK)
    {
        ranger_stop_step_timers();
        step_move_complete = false;
        step_move_active = false;
        step_move_timeout_remaining_ms = 0U;
    }

    /* Do not allow a one-pulse completion ISR to run halfway through
     * HAL_TIM_PWM_Start() and race its state bookkeeping.
     */
    __set_PRIMASK(primask);
}

void HAL_TIM_PeriodElapsedCallback(TIM_HandleTypeDef *htim)
{
    if ((htim == NULL) || (htim->Instance != TIM2))
    {
        return;
    }
    if (!step_move_active || step_move_complete)
    {
        return;
    }

    ranger_stop_step_timers();
    step_move_complete = true;
    /* Foreground task clears step_move_active before accepting a new move. */
}
