// -*- c-basic-offset: 4; tab-width: 8; indent-tabs-mode: t -*-        
#ifndef TCP_H
#define TCP_H

/*
 * A TCP source and sink
 */

#include <list>
#include "config.h"
#include "network.h"
#include "tcppacket.h"
#include "eventlist.h"
#include "sent_packets.h"

//#define MODEL_RECEIVE_WINDOW 1

#define timeInf 0

//#define PACKET_SCATTER 1
#define RANDOM_PATH 1

//#define MAX_SENT 10000

class TcpSink;
class MultipathTcpSrc;
class MultipathTcpSink;
class DagManager;

class TcpSrc : public PacketSink, public EventSource {
    friend class TcpSink;
 public:
    TcpSrc(TcpLogger* logger,
           TrafficLogger* pktlogger,
           EventList &eventlist,
           int flow_src = -1,
           int flow_dst = -1);
    //TcpSrc(TcpLogger* logger, TrafficLogger* pktlogger, EventList &eventlist, int flow_src, int flow_dst, FatTreeTopology* top);
    uint32_t get_id(){ return id;}
    virtual void connect(const Route& routeout, const Route& routeback, 
			 TcpSink& sink, simtime_picosec startTime);
    void startflow();
    void set_nosyn() {_established = true;}
    void set_cwnd(uint32_t cwnd) {_init_cwnd = cwnd;}
    inline void joinMultipathConnection(MultipathTcpSrc* multipathSrc) {
	_mSrc = multipathSrc;
    };

    void doNextEvent();
    virtual void receivePacket(Packet& pkt);

    void replace_route(const Route* newroute);

    void set_flowsize(uint64_t flow_size_in_bytes) {
	    assert(flow_size_in_bytes > 0);
	    _flow_size = flow_size_in_bytes;
	    if (_flow_size < _mss)
		    _pkt_size = _flow_size;
	    else
		    _pkt_size = _mss;
    }

    inline uint64_t get_flowid() {return _flow_id;}
    inline void set_flowid(uint64_t id) {_flow_id = id;}

    void set_ssthresh(uint64_t s){_ssthresh = s;}

    uint32_t effective_window();
    virtual void rtx_timer_hook(simtime_picosec now,simtime_picosec period);
    virtual const string& nodename() { return _nodename; }

    inline uint64_t get_flowsize() {return _flow_size;} // bytes
    inline int get_flow_src() {return _flow_src;}
    inline int get_flow_dst() {return _flow_dst;}
    inline void set_coflow_group_id(int gid) { _coflow_group_id = gid; }
    inline int get_coflow_group_id() const { return _coflow_group_id; }
    inline void set_start_time(simtime_picosec startTime) {_start_time = startTime;}
    inline simtime_picosec get_start_time() {return _start_time;};
    void add_to_dropped(uint64_t seqno); //signal dropped seqno
    bool was_it_dropped(uint64_t seqno, bool clear); //check if seqno was dropped. if clear, remove it from list

    TcpAck* alloc_tcp_ack();
    void cmpIdealCwnd(uint64_t ideal_mbps);
    // should really be private, but loggers want to see:
    uint64_t _highest_sent;  //seqno is in bytes
    uint64_t _packets_sent;
    uint64_t _flow_size;
    uint32_t _cwnd;
    uint32_t _init_cwnd;
    uint32_t _maxcwnd;
    uint64_t _last_acked;
    uint32_t _ssthresh;
    uint16_t _dupacks;
    uint32_t _crt_slice;
#ifdef PACKET_SCATTER
    uint16_t DUPACK_TH;
    uint16_t _crt_path;
#endif

    int32_t _app_limited;

    //round trip time estimate, needed for coupled congestion control
    simtime_picosec _rtt, _rto, _min_rto, _mdev,_base_rtt,_max_rtt;
    int _cap;
    simtime_picosec _rtt_avg, _rtt_cum;
    //simtime_picosec when[MAX_SENT];
    int _sawtooth;

    uint16_t _mss;
    uint16_t _minss;
    uint16_t _pkt_size;
    uint32_t _unacked; // an estimate of the amount of unacked data WE WANT TO HAVE in the network
    uint32_t _effcwnd; // an estimate of our current transmission rate, expressed as a cwnd
    uint64_t _recoverq;
    bool _in_fast_recovery;

    bool _established;
    bool _finished;
    
    bool _is_hpcc;
    bool _longflow;

    uint32_t _drops;

    TcpSink* _sink;
    MultipathTcpSrc* _mSrc;
    simtime_picosec _RFC2988_RTO_timeout;
    bool _rtx_timeout_pending;

    void set_app_limit(int pktps);

    const Route* _route;
    simtime_picosec _last_ping;
#ifdef PACKET_SCATTER
    vector<const Route*>* _paths;

    void set_paths(vector<const Route*>* rt);
#endif
    void send_packets();

	
#ifdef MODEL_RECEIVE_WINDOW
    SentPackets _sent_packets;
    uint64_t _highest_data_seq;
#endif
    int _subflow_id;

    // FatTreeTopology *_top;

    virtual void inflate_window();
    virtual void deflate_window();

    simtime_picosec _start_time;
    uint64_t _flow_id;
    int _flow_src; // the sender (source) for this flow
    int _flow_dst; // the receiver (sink) for this flow
    int _coflow_group_id;
    int rag_id = -1;
    class DagManager* dep_dagman = nullptr;

 private:
    const Route* _old_route;
    uint64_t _last_packet_with_old_route;
    vector<uint64_t> _dropped_at_queue;

    // Housekeeping
    TcpLogger* _logger;
    //TrafficLogger* _pktlogger;

    // Connectivity
    PacketFlow _flow;
    uint32_t _found_retransmit = 0;

    // Mechanism
    void clear_timer(uint64_t start,uint64_t end);

    void retransmit_packet();
    //simtime_picosec _last_sent_time;
    simtime_picosec last_ts = 0;
    uint32_t _found_reorder = 0;

    //void clearWhen(TcpAck::seq_t from, TcpAck::seq_t to);
    //void showWhen (int from, int to);
    string _nodename;
};

class TcpSink : public PacketSink, public DataReceiver, public Logged {
    friend class TcpSrc;
 public:
    TcpSink();

    inline void joinMultipathConnection(MultipathTcpSink* multipathSink){
	_mSink = multipathSink;
    };

    void receivePacket(Packet& pkt);
    TcpAck::seq_t _cumulative_ack; // the packet we have cumulatively acked
    uint64_t _packets;
    uint32_t _drops;
    uint64_t cumulative_ack(){ return _cumulative_ack + _received.size()*1000;}
    uint32_t drops(){ return _src->_drops;}
    uint32_t get_id(){ return id;}
    virtual const string& nodename() { return _nodename; }

    //track tp
    uint64_t _recvd_data;
    simtime_picosec _last_tp_sample_t;

    MultipathTcpSink* _mSink;
    list<TcpAck::seq_t> _received; /* list of packets above a hole, that 
				      we've received */

#ifdef PACKET_SCATTER
    vector<const Route*>* _paths;

    void set_paths(vector<const Route*>* rt);
#endif

    TcpSrc* _src;
 private:
    // Connectivity
    uint16_t _crt_path;
    bool waiting_for_seq = false;
    unsigned out_of_seq_n = 0;
    simtime_picosec out_of_seq_fts = 0;
    simtime_picosec out_of_seq_rxts = 0;

    void connect(TcpSrc& src, const Route& route);
    const Route* _route;

    // Mechanism
    void send_ack(simtime_picosec ts,bool marked, map<string, pktINT> ints, bool bolt_inc);

    string _nodename;
};

class TcpRtxTimerScanner : public EventSource {
 public:
    TcpRtxTimerScanner(simtime_picosec scanPeriod, EventList& eventlist);
    void doNextEvent();
    void registerTcp(TcpSrc &tcpsrc);
 private:
    simtime_picosec _scanPeriod;
    typedef list<TcpSrc*> tcps_t;
    tcps_t _tcps;
};


class RTTSampler : public PacketSink, public EventSource {
 public:
    RTTSampler(EventList &eventlist, TrafficLogger *logger, simtime_picosec sample, int src, int dst);
    void doNextEvent();
    void set_route(Route* out, Route* in) { _routeout = out; _routein = in; }
    void startSampling();
    virtual void receivePacket(Packet &pkt);
    virtual const string& nodename() { return _nodename; }
 private:
    void srcSend();
    void srcRecv(Packet* pkt);
    void dstRecv(Packet* pkt);
    Route *_routeout, *_routein;
    PacketFlow _flow;
    int _src, _dst;
    simtime_picosec _sample;
    string _nodename;
};

#endif
