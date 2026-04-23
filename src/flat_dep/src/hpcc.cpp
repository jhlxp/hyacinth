// -*- c-basic-offset: 4; tab-width: 8; indent-tabs-mode: t -*-        
#include "hpcc.h"
#include "ecn.h"
#include "config.h"
#include "loggertypes.h"

string ntoa(double n);
extern unsigned total_flows;


////////////////////////////////////////////////////////////////
//  HPCC SOURCE
////////////////////////////////////////////////////////////////

HPCCSrc::HPCCSrc(TcpLogger* logger, TrafficLogger* pktlogger, EventList &eventlist, 
        int flow_src, int flow_dst, int max_stage, float nn) 
    : TcpSrc(logger, pktlogger, eventlist, flow_src, flow_dst)
{
    _pkts_seen = 0;
    _pkts_marked = 0;
    _past_cwnd = 2*Packet::data_packet_size();
    _alfa = 0;
    _rto = timeFromMs(10);    
    _is_hpcc = true;
    _U = 1; //idk? will be used for EMWA later
    _max_stage = max_stage; //from paper
    _inc_stage = 0; 
    _nn = nn; //from paper
    _last_sequpdate = 0;
    int ecf = 30; //Expected Concurrent Flows on a link
    _W_AI = (_cwnd*(1-_nn))/ecf;
    _is_new_slice = false;
}

void 
HPCCSrc::startflow() {
    total_flows++;
    //_base_rtt = 0.000005; //seconds, average base rtt
    int num_hops = 1;
    // if(_top->get_firstToR(_flow_src) != _top->get_firstToR(_flow_dst)){
    //     num_hops = _top->get_no_hops(_top->get_firstToR(_flow_src), _top->get_firstToR(_flow_dst), _top->time_to_slice(eventlist().now()), 0);
    // }
    assert(num_hops <= 5);
    _base_rtt = 0.0000003 * num_hops * 2; //prop*hops*2 = base RTT
    _nic_rate = 1E11/8; //link bw bytes/seconds 
    //_bdp = _nic_rate*_base_rtt; //bdp
    _bdp = 60000; //bdp
    _cwnd = _bdp; //hpcc init cwnd = line rate
    _W_AI = _mss/2;
    int max_links = 7; //how many hops max?
    // _crt_slice = _top->time_to_superslice(eventlist().now());
}

void
HPCCSrc::cleanup() {
    _link_ints.clear();
    return;
}

#ifdef TDTCP
//drop detected
void
HPCCSrc::deflate_window(int slice){
    _pkts_seen = 0;
    _pkts_marked = 0;
	  _ssthresh = max(_cwnd/2, (uint32_t)(2 * _mss));
    _past_cwnd = _cwnd;
}
#else
void
HPCCSrc::deflate_window(){
    _pkts_seen = 0;
    _pkts_marked = 0;
	  _ssthresh = max(_cwnd/2, (uint32_t)(2 * _mss));
    _past_cwnd = _cwnd;
}
#endif

void
HPCCSrc::measureInflight(map<string, pktINT> ints, int slice) {
    //bool debugme = get_flowid() == 0;
    bool debugme = false;
    if(debugme) cout << "================\n";
    if(debugme) cout << "MEASURE\n";
    double max_u = -1;
    simtime_picosec T = (500*1000)*ints.size()*2; //base_rtt = prop_delay*hops*2
    if(T <= 1) T = 1;
    simtime_picosec t;
    unsigned ints_size = ints.size() < _link_ints.size() ? ints.size() : _link_ints.size();
    if(debugme) cout << "HOPS N: " << ints_size << endl;
    map<string, pktINT>::iterator it;
    for(it = ints.begin(); it != ints.end(); ++it) {
        string key = it->first;
        //pktINT val = it->second;
        if(_link_ints.count(key) <= 0) continue;
        //assert(ints[i].ts >= _link_ints[i].ts);
        double txRate = (ints[key].txBytes - _link_ints[key].txBytes) / 
            ((ints[key].ts - _link_ints[key].ts)/1E12); //ts is in picosec, we want bytes/s
        uint64_t minq = ints[key].qLen > _link_ints[key].qLen?
            _link_ints[key].qLen : ints[key].qLen;
        double u = (minq/_bdp) + (txRate/_nic_rate);
        if(u > max_u) {
            max_u = u;
            t = ints[key].ts - _link_ints[key].ts;
        }
        if(debugme) cout << "HOPS N: " << ints_size << endl;
        if(debugme) cout << "\tLINK N: " << key << endl;
        if(debugme) cout << "\tTXRATE: " << txRate << " " << ints[key].txBytes - _link_ints[key].txBytes << endl;
        if(debugme) cout << "\tMINQ: " << minq << endl; 
        if(debugme) cout << "\tU': " << u << endl; 
    }
    t = T < t? T : t;
    if(debugme) cout << "BEFORE U:" << _U << " u:" << max_u << endl;
    //max_u is < 0 if no matching queues from previous sample
    if(max_u >= 0) {
        // if(1 || get_flowid() == 0 || get_flowid() == 1) {
        //     cout << "HPCCWND " << get_flowid() << " " << _cwnd << " " << max_u << " " << _U << 
        //         " " << slice << " " << eventlist().now() << endl;
        // }
        _U = (1 - (long double)t/T) * _U + ((long double)t/T) * max_u;
    } else {
        //cout << "NOUPDATE " << eventlist().now() << endl;
    }
    if(debugme) cout << "AFTER U:" << _U << " u:" << max_u << endl;
    if(debugme) cout << "measureInflight " << _U << " " << t << " " << T << endl;
    if(debugme) cout << "================\n";
}

void
HPCCSrc::computeWnd(bool update) {
/*
    if(get_flowid() == 0)
        cout << "CRTCWND " << _cwnd << " " << eventlist().now() << " " << total_flows << endl;
*/
    if(_U >= _nn || _inc_stage >= _max_stage) {
        _crtwnd = _cwnd/(_U/_nn) + _W_AI;  
        if(update) {
            _inc_stage = 0;
            _cwnd = _crtwnd;
        }
    } else {
        _crtwnd = _cwnd + _W_AI;
        if(update) {
            _inc_stage++;
            _cwnd = _crtwnd;
        }
    }   
    /*
    if(get_flowid() == 0 && update){
        cout << "HPCCWND UPDATE " << _cwnd << endl;
    }
    */
}

void
HPCCSrc::computeAck(unsigned ackno, map<string, pktINT> ints, int slice){
    if(get_flowid() == 0) {
    }
    measureInflight(ints, slice);
    if(ackno > _last_sequpdate){
        computeWnd(true); 
        _last_sequpdate = _highest_sent+1;
    } else {
        computeWnd(false);
    }
    _link_ints = ints;
}

void
HPCCSrc::receivePacket(Packet& pkt) 
{
    TcpAck *p = (TcpAck*)(&pkt);
    int slice = p->get_tcp_slice();
    //TEST don't do anything with the packet
    if(pkt.early_fb()) {
        assert(0);
        return TcpSrc::receivePacket(pkt);
    }
    if(_finished) {
        cleanup();
        return TcpSrc::receivePacket(pkt);
    }
    _pkts_seen++;
    
    //do not update cwnd using INT if slice changed
    // int crt_slice = _top->time_to_superslice(eventlist().now());
    //if(p->get_topology()->time_to_superslice(eventlist().now()) != slice){
    // if(0 && _crt_slice != crt_slice){
    //     _crt_slice = crt_slice;
    //     _link_ints = p->get_int();
    //     //TEST start flow with diff cwnd at slice change
    //     _cwnd = 5*_mss;
    //     _crtwnd = _cwnd;
    // } else 
    if(p->ts() > _latest_ts) {
        _latest_ts = p->ts();
        computeAck(p->ackno(), p->get_int(), slice);
    }

    if (_cwnd<_minss)
        _cwnd = _minss;
    if (_cwnd > _maxcwnd)
        _cwnd = _maxcwnd;

    _ssthresh = _cwnd;
    TcpSrc::receivePacket(pkt);
    //cout << ntoa(timeAsMs(eventlist().now())) << " ATCPID " << str() << " CWND " << _cwnd << " alfa " << ntoa(_alfa)<< endl;
}

void 
HPCCSrc::rtx_timer_hook(simtime_picosec now,simtime_picosec period){
    TcpSrc::rtx_timer_hook(now,period);
};

void HPCCSrc::doNextEvent() {
    if(!_rtx_timeout_pending) {
        startflow();
    }
    TcpSrc::doNextEvent();
}

