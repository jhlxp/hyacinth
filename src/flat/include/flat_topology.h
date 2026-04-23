#ifndef FLAT
#define FLAT
#include "main.h"
#include "randomqueue.h"
#include "pipe.h"
#include "config.h"
#include "loggers.h"
#include "network.h"
//#include "firstfit.h" // don't need this
#include "topology.h"
#include "logfile.h"
#include "eventlist.h"
//#include "switch.h" // don't need this unless we do lossless protocol
#include <ostream>

#ifndef QT
#define QT
typedef enum {RANDOM, COMPOSITE, DCTCP, BOLT, HPCC} queue_type;
#endif

class FlatTopology: public Topology{
  public:

  // basic topology elements: pipes and queues

  vector<vector<Pipe*>> pipes_serv_tor;
  vector<vector<Queue*>> queues_serv_tor;

  vector<vector<Pipe*>> pipes_tor_tor;
  vector<vector<Queue*>> queues_tor_tor;

  vector<vector<Pipe*>> pipes_tor_serv;
  vector<vector<Queue*>> queues_tor_serv;

  Pipe* get_downlink(int tor, int host) {return pipes_tor_serv[tor][host];} // for Util monitoring


  Logfile* logfile;
  EventList* eventlist;
  int failed_links;
  queue_type qt;

  FlatTopology(mem_b queuesize, Logfile* log, EventList* ev, queue_type q, string topfile);

  void init_network();
  virtual vector<const Route*>* get_paths(int src, int dest, bool vlb);
  bool get_single_path_from_tors(int src,
                                 int dest,
                                 const vector<int>& tor_path,
                                 vector<const Route*>*& paths,
                                 string* err_msg = nullptr);

  int get_num_shortest_paths(int src, int dest);

  Queue* alloc_src_queue(QueueLogger* q);
  Queue* alloc_queue(QueueLogger* q, mem_b queuesize);
  Queue* alloc_queue(QueueLogger* q, uint64_t speed, mem_b queuesize);

  void count_queue(Queue*);
  vector<int>* get_neighbours(int src) {return NULL;};
  int no_of_nodes() const {return _no_of_nodes;}

  int get_ntor() {return _ntor;}
  int get_ndl() {return _ndl;}
  int get_no_of_nodes() {return _no_of_nodes;}

 private:
  map<Queue*,int> _link_usage;
  void read_params(string topfile);
  int map_server_to_core(int server_id) const;
  vector<vector<int>> _adjacency; // Tor-to-Tor adjacency matrix
  vector<vector<vector<vector<int>>>> _rts; // routes allowed in Flat topology
  vector<int> _server_to_core; // optional mapping: server(local agg id) -> core node id
  void set_params();
  int _ndl, _nul, _ntor, _no_of_nodes; // number down links, number uplinks, number ToRs, number servers
  int _topo_total_nodes; // only used by compact core+agg topology mode
  bool _uses_compact_core_topology;
  mem_b _queuesize; // queue sizes
};


class UtilMonitor : public EventSource {
 public:

    UtilMonitor(FlatTopology* top, EventList &eventlist);

    void start(simtime_picosec period);
    void doNextEvent();
    void printAggUtil();

    FlatTopology* _top;
    simtime_picosec _period; // picoseconds between utilization reports
    uint64_t _max_agg_Bps; // Bytes delivered to endhosts, across the whole network
    uint64_t _max_B_in_period; // Bytes deliverable in period
    int _H; // number of hosts
    int _N; // number of racks
    int _hpr; // number of hosts / rack
};


#endif
