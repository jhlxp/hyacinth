// -*- c-basic-offset: 4; tab-width: 8; indent-tabs-mode: t -*-        
#include "bolt.h"
#include "ecn.h"
#include "config.h"
#include "loggertypes.h"
#include "network.h"

string ntoa(double n);
extern unsigned total_flows;


////////////////////////////////////////////////////////////////
//  Bolt SOURCE
////////////////////////////////////////////////////////////////

BoltSrc::BoltSrc(TcpLogger* logger, TrafficLogger* pktlogger, EventList &eventlist, 
        int flow_src, int flow_dst, bool longflow) 
    : TcpSrc(logger, pktlogger, eventlist, flow_src, flow_dst)
{
    // _top = top;
    _longflow = longflow;
    _past_cwnd = 2*Packet::data_packet_size();
    _rto = timeFromMs(0.2);    
    _is_hpcc = true;
    _U = 1; //idk? will be used for EMWA later
    _last_sequpdate = 0;
    _last_seq_ai = 0;
    _is_new_slice = false;
}

void 
BoltSrc::startflow() {
    total_flows++;
    _nic_rate = 1E11/8; //link bw bytes/seconds 
    //_bdp = _nic_rate*_base_rtt; //bdp
    _bdp = _mss*40; //bdp
    //_cwnd = _bdp; //hpcc init cwnd = line rate
    _cwnd = _init_cwnd*_mss;
    _rtt = timeFromUs(8.0);
    // _crt_slice = _top->time_to_superslice(eventlist().now());
}

void
BoltSrc::cleanup() {
    return;
}

//drop detected
void
#ifdef TDTCP
BoltSrc::deflate_window(int slice){
#else
BoltSrc::deflate_window(){
#endif
	  _ssthresh = max(_cwnd/2, (uint32_t)(2 * _mss));
    _past_cwnd = _cwnd;
}

void
BoltSrc::handleSRC(TcpAck *pkt) {
  double queuesize = pkt->get_int()["bolt"].qLen/1500.0; //queuesize in pkts
  simtime_picosec rtt_src = eventlist().now() - pkt->ts();
  uint64_t crt_rate = _cwnd / ((double)_rtt * 1E-12); //bytes/s
  //cout << "handleSRC cwnd " << _cwnd << " rtt " << _rtt << " crt_rate " << crt_rate << endl;
  double react_factor = min(crt_rate/_nic_rate, 1.0);
  double target_q = react_factor*queuesize; //in pkts
  //cout << "cwnd before " << _cwnd << '\n';
  if ((rtt_src/target_q) < (eventlist().now() - _last_dec_t)) {

    _cwnd = _cwnd >= _mss ? _cwnd - _mss : 0;
    _last_dec_t = eventlist().now();
  }
  //cout << "cwnd after " << _cwnd << '\n';
  //cout << "handleSRC crt_rate " << crt_rate <<  " queuesize " << queuesize << " target_q " << target_q << endl;
}

void
BoltSrc::handleAck(TcpAck *pkt) {
  //cout << "ACK ackno" << pkt->ackno() << " _last_seq_ai " << _last_seq_ai << " inc " << pkt->bolt_inc() << endl; 
  if(pkt->bolt_inc()) {
    _cwnd += _mss;
    //cout << "handleAck INC cwnd" << _cwnd << endl;
  }
  if (pkt->ackno() >= _last_seq_ai) {
    _cwnd += _mss;
    _last_seq_ai = _highest_sent+1;
    //cout << "handleAck AI cwnd " << _cwnd << endl;
  }
}

void
BoltSrc::receivePacket(Packet& pkt) 
{
    assert(pkt.type() == TCPACK);
    TcpAck *p = (TcpAck*)(&pkt);
    if(_finished) {
        cleanup();
        return TcpSrc::receivePacket(pkt);
    }
    
    if(pkt.early_fb()) {
      handleSRC(p); //SRC packet (sent back via early feedback)
      p->free();
      return;
    } else {
      handleAck(p); //ACK packet (can contain PRU/SM information)
    }

    if (_cwnd<_minss)
        _cwnd = _minss;
    if (_cwnd > _maxcwnd)
        _cwnd = _maxcwnd;

    _ssthresh = _cwnd;
    //cout << "Bolt receivePacket cwnd " << _cwnd << endl;
    TcpSrc::_cwnd = _cwnd;
    TcpSrc::receivePacket(pkt);
    //cout << ntoa(timeAsMs(eventlist().now())) << " ATCPID " << str() << " CWND " << _cwnd << " alfa " << ntoa(_alfa)<< endl;
}

void 
BoltSrc::rtx_timer_hook(simtime_picosec now,simtime_picosec period){
    TcpSrc::rtx_timer_hook(now,period);
};

void BoltSrc::doNextEvent() {
    if(!_rtx_timeout_pending) {
        startflow();
    }
    TcpSrc::doNextEvent();
}
