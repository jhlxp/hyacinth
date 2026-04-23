// -*- c-basic-offset: 4; tab-width: 8; indent-tabs-mode: t -*-        
#ifndef HPCC_H
#define HPCC_H

/*
 * A HPCC source simply changes the congestion control algorithm.
 */

#include "tcp.h"
#include "tcppacket.h"

class HPCCSrc : public TcpSrc {
 public:
     HPCCSrc(TcpLogger* logger, TrafficLogger* pktlogger, EventList &eventlist, 
            int flow_src, int flow_dst, int max_stage, float nn);
    ~HPCCSrc(){}

    // Mechanism
#ifdef TDTCP
    virtual void deflate_window(int slice);
#else
    virtual void deflate_window();
#endif
    virtual void receivePacket(Packet& pkt);
    virtual void rtx_timer_hook(simtime_picosec now,simtime_picosec period);
    virtual void startflow();
    virtual void cleanup();
    virtual void doNextEvent();

    void measureInflight(map<string, pktINT> ints, int slice);
    void computeWnd(bool update);
    void computeAck(unsigned ackno, map<string, pktINT> ints, int slice);

 private:
    uint32_t _past_cwnd;
    uint32_t _crtwnd;
    // uint32_t _cwnd, _ssthresh;
    unsigned _last_sequpdate;
    double _alfa;
    uint32_t _pkts_seen, _pkts_marked;
    simtime_picosec _latest_ts = 0;

    map<string, pktINT> _link_ints;
    double _base_rtt;
    double _nic_rate;
    double _bdp;
    double _U;
    bool _is_new_slice;
    
    unsigned _max_stage, _inc_stage;
    unsigned _W_AI;
    float _nn;
};

#endif
