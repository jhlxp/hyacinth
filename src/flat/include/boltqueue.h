// -*- c-basic-offset: 4; tab-width: 8; indent-tabs-mode: t -*-        
#ifndef BOLT_QUEUE_H
#define BOLT_QUEUE_H
#include "queue.h"
/*
 * A reimplementation of the queue used for the Bolt paper following their algorithms
 */

#include <list>
#include "config.h"
#include "eventlist.h"
#include "network.h"
#include "loggertypes.h"

#define PRIO_QUEUE

class BoltQueue : public Queue {
 public:
    BoltQueue(linkspeed_bps bitrate, mem_b maxsize, EventList &eventlist, 
		QueueLogger* logger);
    void receivePacket(Packet & pkt);
    void beginService();
    void completeService();
    virtual mem_b queuesize();
 private:
    typedef enum {Q_LO, Q_HI, Q_NONE} queue_priority_t;
    #ifdef PRIO_QUEUE
    list <Packet*> _enqueued[Q_NONE];
    mem_b _queuesize[Q_NONE];
    queue_priority_t _servicing; 
    #endif
    mem_b _CCthresh;
    int _pru_token, _sm_token;
    simtime_picosec _last_sm_t;

    void updateSupply(Packet &pkt);
};

#endif
