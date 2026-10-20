
/*
 *  PCAP02.h
 *
 *  Created on: Oct. 16, 2026
 *      Author: Tor Kaufmann Gjerde
 */


#ifndef PCAP02_H
#define PCAP02_H

#include <stdint.h>

int32_t pcap_init(int8_t pcap_nbr);
int32_t pcap_read_channel(int8_t pcap_nbr, int channel);

#endif /* PCAP02_H */
