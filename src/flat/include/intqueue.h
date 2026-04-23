// -*- c-basic-offset: 4; tab-width: 8; indent-tabs-mode: t -*-        
#ifndef INT_QUEUE_H
#define INT_QUEUE_H
#include "queue.h"
/*
 * A simple ECN queue that marks on dequeue as soon as the packet occupancy exceeds the set threshold. 
 */

#include <list>
#include "config.h"
#include "eventlist.h"
#include "network.h"
#include "loggertypes.h"

//#define PRIO_ECNQUEUE

class INTQueue : public Queue {
 public:
    INTQueue(linkspeed_bps bitrate, mem_b maxsize, EventList &eventlist, 
		QueueLogger* logger);
    void receivePacket(Packet & pkt);
    void beginService();
    void completeService();
    virtual mem_b queuesize();
 private:
    int _state_send;
    typedef enum {Q_LO, Q_HI, Q_NONE} queue_priority_t;
    #ifdef PRIO_ECNQUEUE
    list <Packet*> _enqueued[Q_NONE];
    mem_b _queuesize[Q_NONE];
    queue_priority_t _servicing; 
    #endif
};

#endif
