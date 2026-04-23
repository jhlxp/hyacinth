// -*- c-basic-offset: 4; tab-width: 8; indent-tabs-mode: t -*-        
#include "tcp.h"
#include "mtcp.h"
#include "ecn.h"
#include "network.h"
#include "output_log.h"
#include "dag_manager.h"
#include <iostream>
#include <algorithm>

static uint64_t id_gen;

#define KILL_THRESHOLD 5
////////////////////////////////////////////////////////////////
//  TCP SOURCE
////////////////////////////////////////////////////////////////
unsigned total_flows = 0;
TcpSrc::TcpSrc(TcpLogger* logger, TrafficLogger* pktlogger, 
	       EventList &eventlist, int flow_src, int flow_dst)
    : EventSource(eventlist,"tcp"),
      _logger(logger),
      _flow(pktlogger),
      _flow_src(flow_src),
      _flow_dst(flow_dst),
      _coflow_group_id(-1)
{
    _mss = Packet::data_packet_size();
    //_maxcwnd = 0xffffffff;//MAX_SENT*_mss;
    //_maxcwnd = 65536;
    _maxcwnd = 128000;
    _sawtooth = 0;
    _subflow_id = -1;
    _rtt_avg = timeFromMs(0);
    _rtt_cum = timeFromMs(0);
    _base_rtt = timeInf;
    _max_rtt = 0;
    _cap = 0;
    _flow_size = ((uint64_t)1)<<63;
    _highest_sent = 0;
    _packets_sent = 0;
    _app_limited = -1;
    _established = false;
    _finished = false;
    _effcwnd = 0;
    _minss = _mss;

    //_ssthresh = 30000;
    _ssthresh = 0xffffffff;

#ifdef MODEL_RECEIVE_WINDOW
    _highest_data_seq = 0;
#endif

    _last_acked = 0;
    _last_ping = timeInf;
    _dupacks = 0;
    _rtt = 0;
    _rto = timeFromMs(0.2);
    _min_rto = timeFromMs(0.2);
    _mdev = 0;
    _recoverq = 0;
    _in_fast_recovery = false;
    _mSrc = NULL;
    _drops = 0;

#ifdef PACKET_SCATTER
    _crt_path = 0;
    DUPACK_TH = 3;
    _paths = NULL;
#endif


    _old_route = NULL;
    _last_packet_with_old_route = 0;

    _rtx_timeout_pending = false;
    _RFC2988_RTO_timeout = timeInf;

    _nodename = "tcpsrc";
}

#ifdef PACKET_SCATTER
void TcpSrc::set_paths(vector<const Route*>* rt) {
    //this should only be used with route
    _paths = new vector<const Route*>();

    for (unsigned int i=0;i<rt->size();i++){
	Route* t = new Route(*(rt->at(i)));
	t->push_back(_sink);
	_paths->push_back(t);
    }
    DUPACK_TH = 3 + rt->size();
    cout << "Setting DUPACK TH to " << DUPACK_TH << endl;
}
#endif

void TcpSrc::set_app_limit(int pktps) {
    if (_app_limited==0 && pktps){
	_cwnd = _mss;
    }
    _ssthresh = 0xffffffff;
    _app_limited = pktps;
    send_packets();
}

void 
TcpSrc::startflow() {
    //cout << "startflow " << get_flowid() << endl;
    _cwnd = _init_cwnd*_mss;
    _unacked = _cwnd;

    send_packets();
}

void TcpSrc::add_to_dropped(uint64_t seqno) {
    _dropped_at_queue.push_back(seqno);
}

bool TcpSrc::was_it_dropped(uint64_t seqno, bool clear) {
    vector<uint64_t>::iterator it;
    it = find(_dropped_at_queue.begin(), _dropped_at_queue.end(), seqno);
    if (it != _dropped_at_queue.end()) {
        //cout << "DROPPED\n";
        if(clear) {
            _dropped_at_queue.erase(it);
        }
        return true;
    } else {
        return false;
    }
}
uint32_t TcpSrc::effective_window() {
    return _in_fast_recovery?_ssthresh:_cwnd;
}

void TcpSrc::cmpIdealCwnd(uint64_t ideal_mbps){
    uint32_t ideal_cwnd = ((double)ideal_mbps*1E6/8)*((long double)_rtt/1E12);
    cout << "CWND " << get_flow_src() << " " << get_flow_dst() << " " << _flow_size << 
	" ideal mbps " << (double)ideal_mbps/8 << " rtt " << (long double)_rtt/1E12 <<
        " " << " IDEAL " << ideal_cwnd << " ACTUAL " << _cwnd << endl;
}


void TcpSrc::replace_route(const Route* newroute) {
    _old_route = _route;
    _route = newroute;
    _last_packet_with_old_route = _highest_sent;
    _last_ping = timeInf;

    //  Printf("Wiating for ack %d to delete\n",_last_packet_with_old_route);
}

void 
TcpSrc::connect(const Route& routeout, const Route& routeback, TcpSink& sink, 
		simtime_picosec starttime) {
    _route = &routeout;

    assert(_route);
    _sink = &sink;
    _flow.id = id; // identify the packet flow with the TCP source that generated it
    _sink->connect(*this, routeback);

    set_start_time(starttime); // record the start time in _start_time

    //printf("Tcp %x msrc %x\n",this,_mSrc);
    eventlist().sourceIsPending(*this,starttime);
}

#define ABS(X) ((X)>0?(X):-(X))

void
TcpSrc::receivePacket(Packet& pkt) 
{
    simtime_picosec ts,fts;
    TcpAck *p = (TcpAck*)(&pkt);
    TcpAck::seq_t seqno = p->ackno();
    //cout << "RECEIVE ACK ackno " << seqno << " flowsize " << get_flowsize() << endl;

#ifdef MODEL_RECEIVE_WINDOW
    if (_mSrc)
	_mSrc->receivePacket(pkt);
#endif

    //pkt.flow().logTraffic(pkt,*this,TrafficLogger::PKT_RCVDESTROY);
  
    ts = p->ts();
    fts = p->get_fabricts();
    p->free();

    if(last_ts > fts) {
        _found_reorder++;
    }
    last_ts = fts;

    if (_finished || seqno < _last_acked) {
		//cout << "O seqno" << seqno << " last acked "<< _last_acked;
		return;
    }

    if (seqno==1){
    	// debug:
    	//cout << "established" << endl;
		//assert(!_established);
		_established = true;
    }
    else if (seqno>1 && !_established) {
		_established = true;
    }

    //assert(seqno >= _last_acked);  // no dups or reordering allowed in this simple simulator

    //compute rtt
    uint64_t m = eventlist().now()-fts;

    if (m!=0){
	        _max_rtt = m > _max_rtt ? m : _max_rtt;
		if (_rtt>0){
		    uint64_t abs;
		    if (m>_rtt)
			abs = m - _rtt;
		    else
			abs = _rtt - m;

		    _mdev = 3 * _mdev / 4 + abs/4;
		    _rtt = 7*_rtt/8 + m/8;
		    _rto = _rtt + 4*_mdev;
		} else {
		    _rtt = m;
		    _mdev = m/2;
		    _rto = _rtt + 4*_mdev;
		}
		if (_base_rtt==timeInf || _base_rtt > m)
		    _base_rtt = m;
    }
    //  cout << "Base "<<timeAsMs(_base_rtt)<< " RTT " << timeAsMs(_rtt)<< " Queued " << queued_packets << endl;

    if (_rto<timeFromMs(1))
		_rto = timeFromMs(1);

	// debug:
	//cout << "seqno = " << seqno << ", _flow_size = " <<  _flow_size << ", _mss = " << _mss << endl;

    if (seqno >= _flow_size){
        double fct_ms = timeAsMs(eventlist().now() - get_start_time());
        double start_ms = timeAsMs(get_start_time());

        if (dep_dagman && rag_id >= 0) {
            int dag_idx = -1, group_id = -1, task_id = -1;
            bool ok = dep_dagman->uid_to_dag_group_task(rag_id, dag_idx, group_id, task_id);
            if (ok) {
                OUTPUT_LOG << dag_idx << " "
                    << group_id << " "
                    << task_id << " "
                    << "FCT " << get_flow_src() << " " << get_flow_dst() << " " << get_flowsize()
                    << " " << fct_ms
                    << " " << start_ms << "\n";
            } else {
                OUTPUT_LOG << get_coflow_group_id() << " "
                    << "FCT " << get_flow_src() << " " << get_flow_dst() << " " << get_flowsize()
                    << " " << fct_ms
                    << " " << start_ms << "\n";
            }
            dep_dagman->notify_task_done(rag_id);
        } else {
            OUTPUT_LOG << get_coflow_group_id() << " "
                << "FCT " << get_flow_src() << " " << get_flow_dst() << " " << get_flowsize()
                << " " << fct_ms
                << " " << start_ms << "\n";
        }
	_finished = true;
	return;
    }
  
    if (seqno > _last_acked) { // a brand new ack
		if (_old_route){
	    	if (seqno >= _last_packet_with_old_route) {
			//delete _old_route;
			_old_route = NULL;
			//printf("Deleted old route\n");
	    	}
		}
		_RFC2988_RTO_timeout = eventlist().now() + _rto;// RFC 2988 5.3
		_last_ping = eventlist().now();
    
		if (seqno >= _highest_sent) {
		    _highest_sent = seqno;
		    _RFC2988_RTO_timeout = timeInf;// RFC 2988 5.2
		    _last_ping = timeInf;
		}

#ifdef MODEL_RECEIVE_WINDOW
	int cnt;

	_sent_packets.ack_packet(seqno);

	//if ((cnt = _sent_packets.ack_packet(seqno)) > 2)
	//  cout << "ACK "<<cnt<<" packets on " << _flow.id << " " << _highest_sent+1 << " packets in flight " << _sent_packets.crt_count << " diff " << (_highest_sent+_mss-_last_acked)/1000 << " last_acked " << _last_acked << " at " << timeAsMs(eventlist().now()) << endl;
#endif

		if (!_in_fast_recovery) { // best behaviour: proper ack of a new packet, when we were expecting it
		    //clear timers
	      
		    _last_acked = seqno;
		    _dupacks = 0;
		    inflate_window();

		    if (_cwnd>_maxcwnd) {
			_cwnd = _maxcwnd;
		    }

		    _unacked = _cwnd;
		    _effcwnd = _cwnd;
		    if (_logger) 
			_logger->logTcp(*this, TcpLogger::TCP_RCV);
		    send_packets();
		    return;
		}
		// We're in fast recovery, i.e. one packet has been
		// dropped but we're pretending it's not serious
		if (seqno >= _recoverq) { 
		    // got ACKs for all the "recovery window": resume
		    // normal service
		    uint32_t flightsize = _highest_sent - seqno;
		    _cwnd = min(_ssthresh, flightsize + _mss);
		    _unacked = _cwnd;
		    _effcwnd = _cwnd;
		    _last_acked = seqno;
		    _dupacks = 0;
		    _in_fast_recovery = false;

		    if (_logger) 
			_logger->logTcp(*this, TcpLogger::TCP_RCV_FR_END);
		    send_packets();
		    return;
		}
		// In fast recovery, and still getting ACKs for the
		// "recovery window"
		// This is dangerous. It means that several packets
		// got lost, not just the one that triggered FR.
		uint32_t new_data = seqno - _last_acked;
		_last_acked = seqno;
		if (new_data < _cwnd) 
	    	_cwnd -= new_data; 
		else 
	    	_cwnd = 0;
		_cwnd += _mss;
		if (_logger) 
	    	_logger->logTcp(*this, TcpLogger::TCP_RCV_FR);
		retransmit_packet();
		send_packets();
		return;
    }
    // It's a dup ack
    if (_in_fast_recovery) { // still in fast recovery; hopefully the prodigal ACK is on it's way 
	_cwnd += _mss;
	if (_cwnd>_maxcwnd) {
	    _cwnd = _maxcwnd;
	}
	// When we restart, the window will be set to
	// min(_ssthresh, flightsize+_mss), so keep track of
	// this
	_unacked = min(_ssthresh, (uint32_t)(_highest_sent-_recoverq+_mss)); 
	if (_last_acked+_cwnd >= _highest_sent+_mss) 
	    _effcwnd=_unacked; // starting to send packets again
	if (_logger) 
	    _logger->logTcp(*this, TcpLogger::TCP_RCV_DUP_FR);
	send_packets();
	return;
    }
    // Not yet in fast recovery. What should we do instead?
    _dupacks++;

#ifdef PACKET_SCATTER
    if (_dupacks!=DUPACK_TH) 
#else
	if (_dupacks!=3) 
#endif
	    { // not yet serious worry
		if (_logger) 
		    _logger->logTcp(*this, TcpLogger::TCP_RCV_DUP);
		send_packets();
		return;
	    }
    // _dupacks==3
    if (_last_acked < _recoverq) {  
        /* See RFC 3782: if we haven't recovered from timeouts
	   etc. don't do fast recovery */
	if (_logger) 
	    _logger->logTcp(*this, TcpLogger::TCP_RCV_3DUPNOFR);
	return;
    }
  
    // begin fast recovery
  
    //only count drops in CA state
    _drops++;
    //print if retransmission is due to reordered packet (was not dropped)
    //also as we're retransmitting it, clear the seqno from the dropped list
    if (!was_it_dropped(_last_acked+1, true)) {
        _found_retransmit++;
    }
  
    deflate_window();
  
    if (_sawtooth>0)
	_rtt_avg = _rtt_cum/_sawtooth;
    else
	_rtt_avg = timeFromMs(0);
  
    _sawtooth = 0;
    _rtt_cum = timeFromMs(0);
  
    retransmit_packet();
    _cwnd = _ssthresh + 3 * _mss;
    _unacked = _ssthresh;
    _effcwnd = 0;
    _in_fast_recovery = true;
    _recoverq = _highest_sent; // _recoverq is the value of the
    // first ACK that tells us things
    // are back on track
    if (_logger) 
	_logger->logTcp(*this, TcpLogger::TCP_RCV_DUP_FASTXMIT);
}

void TcpSrc::deflate_window(){
    if(_is_hpcc)
		return;
	if (_mSrc==NULL)
	_ssthresh = max(_cwnd/2, (uint32_t)(2 * _mss));
    else
	_ssthresh = _mSrc->deflate_window(_cwnd,_mss);
}

void
TcpSrc::inflate_window() {
	if(_is_hpcc)
		return;
    int newly_acked = (_last_acked + _cwnd) - _highest_sent;
    // be very conservative - possibly not the best we can do, but
    // the alternative has bad side effects.
    if (newly_acked > _mss) newly_acked = _mss; 
    if (newly_acked < 0)
	return;
    if (_cwnd < _ssthresh) { //slow start
	int increase = min(_ssthresh - _cwnd, (uint32_t)newly_acked);
	_cwnd += increase;
	newly_acked -= increase;
    } else {
	// additive increase
	uint32_t pkts = _cwnd/_mss;

	double queued_fraction = 1 - ((double)_base_rtt/_rtt);

	if (queued_fraction>=0.5&&_mSrc&&_cap)
	    return;
  
	if (_mSrc==NULL){
	    //int tt = (newly_acked * _mss) % _cwnd;
	    _cwnd += (newly_acked * _mss) / _cwnd;  //XXX beware large windows, when this increase gets to be very small

	    //if (rand()%_cwnd < tt)
	    //_cwnd++;
	} else {
	    _cwnd = _mSrc->inflate_window(_cwnd,newly_acked,_mss);
	}

	if (pkts!=_cwnd/_mss) {
	    _rtt_cum += _rtt;
	    _sawtooth ++;
	}
    }
}

// Note: the data sequence number is the number of Byte1 of the packet, not the last byte.
void 
TcpSrc::send_packets() {
    uint32_t c = _cwnd;
    //cout << "send_packets cwnd" << _cwnd << endl;

    if (!_established){
		//send SYN packet and wait for SYN/ACK
		Packet * p  = TcpPacket::new_syn_pkt(_flow, *_route, this, _sink, 1, 1);
		_highest_sent = 1;

		p->sendOn();

		if(_RFC2988_RTO_timeout == timeInf) {// RFC2988 5.1
		    _RFC2988_RTO_timeout = eventlist().now() + _rto;
		}	
		//cout << "Sending SYN, waiting for SYN/ACK" << endl;
		return;
    }

    bool last_cwnd = (_highest_sent+c >= _flow_size);
    bool first_cwnd = (_highest_sent < _mss);
    //cout << c << " " << _last_acked << " " << _highest_sent << " " << _mss << " " << _flow_size << endl;
    while ((_last_acked + c >= _highest_sent + _mss) 
            && (_highest_sent < _flow_size)){
    //while ((_last_acked + c >= _highest_sent + _mss) && (_highest_sent+_mss <= _flow_size+_mss+1)) {
	uint64_t data_seq = 0;
	uint16_t size = _highest_sent+_mss <= _flow_size ? _mss : _flow_size-_highest_sent+1;
	assert(size > 0);
#ifdef PACKET_SCATTER
	TcpPacket* p;

	if (_paths){

#ifdef RANDOM_PATH
	    _crt_path = random()%_paths->size();
#endif

	    p = TcpPacket::newpkt(_flow, *(_paths->at(_crt_path)), this, _sink, _highest_sent+1, 
			    data_seq, _pkt_size);
	    _crt_path = (_crt_path + 1) % _paths->size();
	} else {
	    p  = TcpPacket::newpkt(_flow, *_route, this, _sink, _highest_sent+1, data_seq, _pkt_size);
	}
#else
	TcpPacket* p = TcpPacket::newpkt(_flow, *_route, this, _sink, _highest_sent+1, data_seq, _pkt_size);
#endif
	p->flow().logTraffic(*p,*this,TrafficLogger::PKT_CREATESEND);
	p->set_ts(eventlist().now());
    p->set_first(first_cwnd);
    p->set_last(last_cwnd);

    if(!last_cwnd) {
        p->set_bolt_inc(true);
    } else {
        p->set_bolt_inc(false);
    }
    
    
	_highest_sent += _mss;  //XX beware wrapping
	_packets_sent += _mss;

    //cout << "sending pkt " << p->seqno() << " cwnd " << _cwnd << endl;
	p->sendOn();

	if(_RFC2988_RTO_timeout == timeInf) {// RFC2988 5.1
	    _RFC2988_RTO_timeout = eventlist().now() + _rto;
	}
    }
}

void 
TcpSrc::retransmit_packet() {
    if (!_established){
	assert(_highest_sent == 1);

	Packet* p  = TcpPacket::new_syn_pkt(_flow, *_route, this, _sink, 1, 1);
	p->sendOn();
	return;	
    }

    uint64_t data_seq = 0;

#ifdef MODEL_RECEIVE_WINDOW
    if (! _sent_packets.get_data_seq(_last_acked+1, &data_seq)){
	assert(NULL);
    }
    //  else
    //  cout << "Retransmit packet on " << _flow.id << " " << _last_acked+1 << " " << data_seq << endl;
#endif


#ifdef PACKET_SCATTER
    TcpPacket* p;
    if (_paths) {

#ifdef RANDOM_PATH
	_crt_path = random()%_paths->size();
#endif

	p = TcpPacket::newpkt(_flow, *(_paths->at(_crt_path)), this, _sink, _last_acked+1, data_seq, _pkt_size);
	_crt_path = (_crt_path + 1) % _paths->size();
    } else {
	p = TcpPacket::newpkt(_flow, *_route, this, _sink, _last_acked+1, _pkt_size);
    }
#else
    TcpPacket* p = TcpPacket::newpkt(_flow, *_route, this, _sink, _last_acked+1, data_seq, _pkt_size);
#endif

    p->flow().logTraffic(*p,*this,TrafficLogger::PKT_CREATESEND);
    p->set_ts(eventlist().now());
    p->set_bolt_inc(false);
    p->sendOn();

    _packets_sent += _mss;

    if(_RFC2988_RTO_timeout == timeInf) {// RFC2988 5.1
	_RFC2988_RTO_timeout = eventlist().now() + _rto;
    }
}

void TcpSrc::rtx_timer_hook(simtime_picosec now, simtime_picosec period) {
    if (now <= _RFC2988_RTO_timeout || _RFC2988_RTO_timeout==timeInf) 
	return;

    if (_finished)
        return;

    if (_highest_sent == 0) 
	return;

    // here we can run into phase effects because the timer is checked
    // only periodically for ALL flows but if we keep the difference
    // between scanning time and real timeout time when restarting the
    // flows we should minimize them !
    if(!_rtx_timeout_pending) {
	_rtx_timeout_pending = true;

	// check the timer difference between the event and the real value
	simtime_picosec too_late = now - (_RFC2988_RTO_timeout);
 
	// careful: we might calculate a negative value if _rto suddenly drops very much
	// to prevent overflow but keep randomness we just divide until we are within the limit
	while(too_late > period) too_late >>= 1;

	// carry over the difference for restarting
	simtime_picosec rtx_off = (period - too_late)/200;
 
	eventlist().sourceIsPendingRel(*this, rtx_off);

	//reset our rtx timerRFC 2988 5.5 & 5.6

	_rto *= 2;
	//if (_rto > timeFromMs(1000))
	//  _rto = timeFromMs(1000);
	_RFC2988_RTO_timeout = now + _rto;
    }
}

void TcpSrc::doNextEvent() {
    if(_rtx_timeout_pending) {
	_rtx_timeout_pending = false;

	if (_logger) 
	    _logger->logTcp(*this, TcpLogger::TCP_TIMEOUT);

	if (_in_fast_recovery) {
	    uint32_t flightsize = _highest_sent - _last_acked;
	    _cwnd = min(_ssthresh, flightsize + _mss);
	}

	deflate_window();

	_cwnd = _mss;

	_unacked = _cwnd;
	_effcwnd = _cwnd;
	_in_fast_recovery = false;
	_recoverq = _highest_sent;

	if (_established)
	    _highest_sent = _last_acked + _mss;

	_dupacks = 0;

	retransmit_packet();

	if (_sawtooth>0)
	    _rtt_avg = _rtt_cum/_sawtooth;
	else
	    _rtt_avg = timeFromMs(0);

	_sawtooth = 0;
	_rtt_cum = timeFromMs(0);

	if (_mSrc)
	    _mSrc->window_changed();
    } else {
	//cout << "Starting flow" << endl;
	startflow();
    }
}

////////////////////////////////////////////////////////////////
//  TCP SINK
////////////////////////////////////////////////////////////////

TcpSink::TcpSink() 
    : Logged("sink"), _cumulative_ack(0) , _packets(0), _mSink(0), _crt_path(0)
{
    _nodename = "tcpsink";
    _last_tp_sample_t = 0;
    _recvd_data = 0;
}

void 
TcpSink::connect(TcpSrc& src, const Route& route) {
    _src = &src;
    _route = &route;
    _cumulative_ack = 0;
    _drops = 0;
}

// Note: _cumulative_ack is the last byte we've ACKed.
// seqno is the first byte of the new packet.
void
TcpSink::receivePacket(Packet& pkt) {
    TcpPacket *p = (TcpPacket*)(&pkt);
    TcpPacket::seq_t seqno = p->seqno();
    simtime_picosec ts = p->get_fabricts();
    simtime_picosec fts = p->get_fabricts();
    map<string,pktINT> ints = p->get_int();
    bool bolt_inc = p->bolt_inc();
    _recvd_data += p->size()-64;
    if(_src->eventlist().now() - _last_tp_sample_t > 2E9) {
      //cout << "TP " << _src->_flow_id << " " << _recvd_data*8/1E6 << " " << _src->eventlist().now() << endl;  
      _recvd_data = 0;
      _last_tp_sample_t += 1E9;
    }

    //randomly sample packets for queueing
    if(random()%100 == 0){
        //cout << "PKT " << p->get_queueing() << " " << p->get_last_queueing() << endl;
    }

    bool marked = p->flags()&ECN_CE;

    if (_mSink!=NULL){
	_mSink->receivePacket(pkt);
    }

    int size = p->size()-64; 
    pkt.flow().logTraffic(pkt,*this,TrafficLogger::PKT_RCVDESTROY);
    p->free();

    _packets+= p->size();

    //cout << "Sink: received seqno " << seqno << " size " << size << endl;

    if (seqno == _cumulative_ack+1) { // it's the next expected seq no
		_cumulative_ack = seqno + size - 1;
		//cout << "New cumulative ack is " << _cumulative_ack << endl;
		// are there any additional received packets we can now ack?
		while (!_received.empty() && (_received.front() == _cumulative_ack+1) ) {
		    _received.pop_front();
		    _cumulative_ack+= size;
		}
    if (waiting_for_seq) {
            waiting_for_seq = false;
            out_of_seq_n = 0;
    }
    } else if (seqno < _cumulative_ack+1) {
    } else { // it's not the next expected sequence number
        //check whether the expected seqno was dropped. if not, it's a reorder
        if(!_src->was_it_dropped(_cumulative_ack+1, false)) {
            if(!waiting_for_seq) {
                waiting_for_seq = true;
                out_of_seq_fts = fts;
                out_of_seq_rxts = _src->eventlist().now();
            }
            out_of_seq_n++;
        } else if(waiting_for_seq) {
            //it could have been dropped while arriving late...
            waiting_for_seq = false;
            out_of_seq_n = 0;
        }
		if (_received.empty()) {
		    _received.push_front(seqno);
		    //it's a drop in this simulator there are no reorderings.
		    _drops += (1000 + seqno-_cumulative_ack-1)/1000;
		} else if (seqno > _received.back()) { // likely case
		    _received.push_back(seqno);
		} else { // uncommon case - it fills a hole
		    list<uint64_t>::iterator i;
		    for (i = _received.begin(); i != _received.end(); i++) {
			if (seqno == *i) break; // it's a bad retransmit
			if (seqno < (*i)) {
			    _received.insert(i, seqno);
			    break;
			}
		    }
		}
    }
    send_ack(ts,marked,ints, bolt_inc);
}

void 
TcpSink::send_ack(simtime_picosec ts,bool marked,map<string, pktINT> ints, bool bolt_inc) {

	// debug:
	//cout << "Sink: sending an ACK" << endl;

    const Route* rt = _route;
    
#ifdef PACKET_SCATTER
    if (_paths){
#ifdef RANDOM_PATH
	_crt_path = random()%_paths->size();
#endif
	
	rt = _paths->at(_crt_path);
	_crt_path = (_crt_path+1)%_paths->size();
    }
#endif
    
    TcpAck *ack = TcpAck::newpkt(_src->_flow, *rt, 0, _cumulative_ack, 
				 _mSink!=NULL?_mSink->data_ack():0);

    ack->flow().logTraffic(*ack,*this,TrafficLogger::PKT_CREATESEND);
    ack->set_ts(ts);
    ack->set_int(ints);
    if (marked) {
	    ack->set_flags(ECN_ECHO);
    } else {
	    ack->set_flags(0);
    }

    ack->set_bolt_inc(bolt_inc);
    ack->sendOn();
}

#ifdef PACKET_SCATTER
void TcpSink::set_paths(vector<const Route*>* rt) {
    //this should only be used with route
    _paths = new vector<const Route*>();

    for (unsigned int i=0;i<rt->size();i++){
	Route* t = new Route(*(rt->at(i)));
	t->push_back(_src);
	_paths->push_back(t);
    }
}
#endif

////////////////////////////////////////////////////////////////
//  TCP RETRANSMISSION TIMER
////////////////////////////////////////////////////////////////

TcpRtxTimerScanner::TcpRtxTimerScanner(simtime_picosec scanPeriod, EventList& eventlist)
    : EventSource(eventlist,"RtxScanner"), _scanPeriod(scanPeriod) {
    eventlist.sourceIsPendingRel(*this, _scanPeriod);
}

void 
TcpRtxTimerScanner::registerTcp(TcpSrc &tcpsrc) {
    _tcps.push_back(&tcpsrc);
}

void TcpRtxTimerScanner::doNextEvent() {
    simtime_picosec now = eventlist().now();
    tcps_t::iterator i;
    for (i = _tcps.begin(); i!=_tcps.end(); i++) {
	(*i)->rtx_timer_hook(now,_scanPeriod);
    }
    eventlist().sourceIsPendingRel(*this, _scanPeriod);
}

RTTSampler::RTTSampler(EventList &eventlist, TrafficLogger* logger, simtime_picosec sample, int src, int dst) 
	: EventSource(eventlist,"rttsampler"), _flow(logger)
{
    _src = src;
    _dst = dst;
    _sample = sample; 
    _nodename = "rttsampler";
}

void
RTTSampler::startSampling() {
    eventlist().sourceIsPendingRel(*this, _sample);
}

void 
RTTSampler::doNextEvent() {
    srcSend(); 
    eventlist().sourceIsPendingRel(*this, _sample);
}

void 
RTTSampler::srcSend() {
    SamplePacket* p = SamplePacket::newpkt(_flow, _src, _dst, 1436, *_routeout);
    p->sendOn();
}

void
RTTSampler::receivePacket(Packet &p){
    SamplePacket *sp = (SamplePacket*)&p;
    if(sp->get_src() == _src) {
        dstRecv(&p);
    } else {
        srcRecv(&p);
    }
}

void
RTTSampler::dstRecv(Packet* p) {
    simtime_picosec ts = p->get_fabricts();
    p->free();
    p = SamplePacket::newpkt(_flow, _dst, _src, 1, *_routein);
    ((SamplePacket*)p)->set_ts(ts);
    p->sendOn();
}

void
RTTSampler::srcRecv(Packet* p) {
    simtime_picosec ts = ((SamplePacket*)p)->ts();
    p->free();
    //cout << "RTT " << eventlist().now()-ts << " " << eventlist().now() << endl;
}

