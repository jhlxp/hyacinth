#ifndef TCPPACKET_H
#define TCPPACKET_H

#include <list>
#include "network.h"

class TcpSrc;
class TcpSink;

#define MTU_SIZE 1500

enum BoltType {SRC, PRU, SM};

// TcpPacket and TcpAck are subclasses of Packet.
// They incorporate a packet database, to reuse packet objects that are no longer needed.
// Note: you never construct a new TcpPacket or TcpAck directly; 
// rather you use the static method newpkt() which knows to reuse old packets from the database.

class TcpPacket : public Packet {
public:
	typedef uint64_t seq_t;

	inline static TcpPacket* newpkt(PacketFlow &flow, const Route &route, 
					 TcpSrc *tcp_src, TcpSink *tcp_sink, seq_t seqno, seq_t dataseqno,int size) {
	    TcpPacket* p = _packetdb.allocPacket();
	    assert(size > 0);
        p->_tcp_src = tcp_src;
        p->_tcp_sink = tcp_sink;
	    p->set_route(flow,route,size+64,seqno+size-1-64); // The TCP sequence number is the first byte of the packet; I will ID the packet by its last byte.
	    p->_type = TCP;
	    p->_seqno = seqno;
	    p->_data_seqno=dataseqno;
	    p->_syn = false;
      p->_pkt_ints.clear();
      p->_early_fb = false;
      p->_flags = 0;
      p->_last_wnd = false;
      p->_first_wnd = false;
      p->_bolt_inc = false;
	    return p;
	}

	inline static TcpPacket* newpkt(PacketFlow &flow, const Route &route, 
					 TcpSrc *tcp_src, TcpSink *tcp_sink, seq_t seqno, int size) {
		return newpkt(flow,route,tcp_src,tcp_sink,seqno,0,size);
	}

	inline static TcpPacket* new_syn_pkt(PacketFlow &flow, const Route &route, 
					 TcpSrc *tcp_src, TcpSink *tcp_sink, seq_t seqno, int size) {
		TcpPacket* p = newpkt(flow,route,tcp_src,tcp_sink,seqno,0,size);
		p->_syn = true;
		return p;
	}

	// Backward-compatible constructors used by legacy flat code.
	inline static TcpPacket* newpkt(PacketFlow &flow, const Route &route, 
					seq_t seqno, seq_t dataseqno, int size) {
		return newpkt(flow, route, nullptr, nullptr, seqno, dataseqno, size);
	}

	inline static TcpPacket* newpkt(PacketFlow &flow, const Route &route, 
					seq_t seqno, int size) {
		return newpkt(flow, route, nullptr, nullptr, seqno, 0, size);
	}

	inline static TcpPacket* new_syn_pkt(PacketFlow &flow, const Route &route, 
					     seq_t seqno, int size) {
		return new_syn_pkt(flow, route, nullptr, nullptr, seqno, size);
	}

	void free() {_packetdb.freePacket(this);}
	virtual ~TcpPacket(){}
	inline seq_t seqno() const {return _seqno;}
	inline seq_t data_seqno() const {return _data_seqno;}
	inline simtime_picosec ts() const {return _ts;}
	inline void set_ts(simtime_picosec ts) {_ts = ts;}
    virtual inline TcpSrc* get_tcpsrc(){return _tcp_src;}
    virtual inline TcpSink* get_tcpsink(){return _tcp_sink;}
	
	inline bool last() {return _last_wnd;}
	inline void set_last(bool last) {_last_wnd = last;}
	inline bool first() {return _first_wnd;}
	inline void set_first(bool first) {_first_wnd = first;}
	void set_bolt_inc(bool inc) {_bolt_inc = inc;}
	bool bolt_inc() {return _bolt_inc;}
protected:
	seq_t _seqno,_data_seqno;
    TcpSrc *_tcp_src;
    TcpSink *_tcp_sink;
	bool _syn;
	simtime_picosec _ts;
	bool _last_wnd, _first_wnd;
    bool _bolt_inc;
	static PacketDB<TcpPacket> _packetdb;
};

class TcpAck : public Packet {
public:
	typedef TcpPacket::seq_t seq_t;

	inline static TcpAck* newpkt(PacketFlow &flow, const Route &route, 
				     seq_t seqno, seq_t ackno,seq_t dackno) {
	    TcpAck* p = _packetdb.allocPacket();
	    p->set_route(flow,route,_ACKSIZE,ackno);
	    p->_type = TCPACK;
	    p->_seqno = seqno;
	    p->_ackno = ackno;
	    p->_data_ackno = dackno;
      p->_pkt_ints.clear();
      p->_early_fb = false;
      p->_flags = 0;
	    return p;
	}

	inline static TcpAck* newpkt(PacketFlow &flow, const Route &route, 
					seq_t seqno, seq_t ackno) {
		return newpkt(flow,route,seqno,ackno,0);
	}

	void free() {_packetdb.freePacket(this);}
	inline seq_t seqno() const {return _seqno;}
	inline seq_t ackno() const {return _ackno;}
	inline seq_t data_ackno() const {return _data_ackno;}
	inline simtime_picosec ts() const {return _ts;}
	inline void set_ts(simtime_picosec ts) {_ts = ts;}
	inline void set_tcp_slice(int slice) {_tcp_slice = slice;}
  	inline int get_tcp_slice() {return _tcp_slice;}
	void set_bolt_type(BoltType type) {_bolt_type = type;}
	BoltType get_bolt_type() {return _bolt_type;}
	void set_bolt_inc(bool inc) {_bolt_inc = inc;}
	bool bolt_inc() {return _bolt_inc;}
	void set_pck_int(pktINT p) {_pck_int = p;}

	virtual ~TcpAck(){}
	const static int _ACKSIZE=64;
protected:
	seq_t _seqno;
	seq_t _ackno, _data_ackno;
	simtime_picosec _ts;
	static PacketDB<TcpAck> _packetdb;
	BoltType _bolt_type;
	int _tcp_slice;	
  	bool _bolt_inc;
	pktINT _pck_int;
};

class RTTSampler;
class SamplePacket : public Packet {
 public:
    inline static SamplePacket* newpkt(PacketFlow &flow, int flow_src, int flow_dst, int size, Route& route) {
        SamplePacket* p = _packetdb.allocPacket();
        p->set_src(flow_src);
        p->set_dst(flow_dst);
	p->set_route(flow,route,size,0);
        p->_type = SAMPLE;
        p->_size = size;
        return p;
    }
    void set_ts(simtime_picosec ts) {_ts = ts;}
    void set_dst(int dst) {_dst = dst;}
    void set_src(int src) {_src = src;}
    int get_src() {return _src;}
    int get_dst() {return _dst;}
    simtime_picosec ts() {return _ts;}
 private:
    int _src, _dst;
    simtime_picosec _ts;
    static PacketDB<SamplePacket> _packetdb;
};

#endif
