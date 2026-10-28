/*
 * ranger_app.h
 *
 *  Created on: Apr 28, 2026
 *      Author: Tor Kaufmann Gjerde
 *
 *  Description:
 *  Public interface for the Ranger application layer.
 */

#ifndef INC_RANGER_APP_H_
#define INC_RANGER_APP_H_

#include "main.h"

/**
 * @brief Initialize Ranger application state.
 */
void ranger_app_init(void);

/**
 * @brief Run periodic Ranger application tasks.
 *
 * Called continuously from main loop.
 */
void ranger_app_tick(void);


#endif /* INC_RANGER_APP_H_ */
