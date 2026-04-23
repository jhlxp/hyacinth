// -*- c-basic-offset: 4; tab-width: 8; indent-tabs-mode: t -*-
#include "flat_topology.h"
#include <vector>
#include "string.h"
#include <sstream>
#include <strstream>
#include <iostream>
#include <fstream> // to read from file
#include <stdexcept>
#include "main.h"
#include "queue.h"
#include "switch.h"
#include "compositequeue.h"
#include "prioqueue.h"
#include "queue_lossless.h"
#include "queue_lossless_input.h"
#include "queue_lossless_output.h"
#include "ecnqueue.h"
#include "ecn.h"
#include "boltqueue.h"
#include "intqueue.h"
#include "output_log.h"

extern uint32_t RTT_rack;
extern uint32_t RTT_net;

string ntoa(double n);
string itoa(uint64_t n);

FlatTopology::FlatTopology(mem_b queuesize, Logfile* lg, EventList* ev,queue_type q, string topfile){
    _queuesize = queuesize;
    logfile = lg;
    eventlist = ev;
    qt = q;

    read_params(topfile);
 
    set_params();

    init_network();
}

// read the topology info from file (generated in Matlab)
void FlatTopology::read_params(string topfile) {
    /*
    _no_of_nodes = 6; // number of servers
    _ndl = 2; // number of downlinks from ToR
    _nul = 2; // number of uplinks from ToR (to other ToRs)
    _ntor = 3; // number of ToRs
    */
  _uses_compact_core_topology = false;
  _topo_total_nodes = 0;
  _server_to_core.clear();
  _adjacency.clear();
  _rts.clear();

  ifstream input(topfile);
  if (!input.is_open()) {
    throw runtime_error("cannot open topology file: " + topfile);
  }

  // read the first line of basic parameters:
  string line;
  if (!getline(input, line)) {
    throw runtime_error("empty topology file: " + topfile);
  }

  vector<int> header_vals;
  {
    stringstream stream(line);
    int v = 0;
    while (stream >> v) header_vals.push_back(v);
  }
  if (header_vals.size() < 4) {
    throw runtime_error("invalid topology header (need >=4 integers): " + topfile);
  }

  _no_of_nodes = header_vals[0];
  _ndl = header_vals[1];
  _nul = header_vals[2];
  _ntor = header_vals[3];

  if (header_vals.size() >= 5) {
    // Compact mode used by topology/*.txt:
    // header: H dl ul ntor N
    // adjacency: full N x N matrix, where the first (N-H) nodes are core nodes.
    _uses_compact_core_topology = true;
    _topo_total_nodes = header_vals[4];
    if (_topo_total_nodes <= 0 || _no_of_nodes <= 0 || _no_of_nodes >= _topo_total_nodes) {
      throw runtime_error("invalid compact topology dimensions in: " + topfile);
    }

    vector<vector<int>> full_adjacency(_topo_total_nodes, vector<int>(_topo_total_nodes, 0));
    for (int i = 0; i < _topo_total_nodes; i++) {
      for (int j = 0; j < _topo_total_nodes; j++) {
        if (!(input >> full_adjacency[i][j])) {
          throw runtime_error("failed to read compact adjacency matrix from: " + topfile);
        }
      }
    }

    _ntor = _topo_total_nodes - _no_of_nodes; // core nodes
    if (_ntor <= 0) {
      throw runtime_error("compact topology has non-positive core node count in: " + topfile);
    }

    _adjacency.assign(_ntor, vector<int>(_ntor, 0));
    for (int i = 0; i < _ntor; i++) {
      for (int j = 0; j < _ntor; j++) {
        _adjacency[i][j] = full_adjacency[i][j];
      }
    }

    _server_to_core.assign(_no_of_nodes, -1);
    int agg_base = _topo_total_nodes - _no_of_nodes;
    for (int host = 0; host < _no_of_nodes; host++) {
      int global_agg = agg_base + host;
      int parent_tor = -1;
      int cnt = 0;
      for (int tor = 0; tor < _ntor; tor++) {
        if (full_adjacency[global_agg][tor] == 1 || full_adjacency[tor][global_agg] == 1) {
          parent_tor = tor;
          cnt++;
        }
      }
      if (cnt != 1) {
        throw runtime_error(
            "invalid agg->core mapping for host " + itoa((uint64_t)host) +
            ", expected 1 parent but got " + itoa((uint64_t)cnt));
      }
      _server_to_core[host] = parent_tor;
    }
  } else {
    // Legacy mode:
    // header: H dl ul ntor
    // adjacency: ntor x ntor
    _uses_compact_core_topology = false;
    _topo_total_nodes = _ntor;
    if (_ntor <= 0 || _no_of_nodes <= 0) {
      throw runtime_error("invalid legacy topology dimensions in: " + topfile);
    }

    _adjacency.assign(_ntor, vector<int>(_ntor, 0));
    for (int i = 0; i < _ntor; i++) {
      for (int j = 0; j < _ntor; j++) {
        if (!(input >> _adjacency[i][j])) {
          throw runtime_error("failed to read legacy adjacency matrix from: " + topfile);
        }
      }
    }
  }

  // get routes (rest of file). Format: (src ToR) (dst ToR) (intermediate ToRs in order)
  _rts.resize(_ntor);
  for (int i = 0; i < _ntor; i++) {
    _rts[i].resize(_ntor);
  }

  // consume remainder of line after matrix parsing with operator>>
  getline(input, line);

  int temp = 0;
  while (getline(input, line)) {
    vector<int> vtemp;
    stringstream stream(line);
    while (stream >> temp) vtemp.push_back(temp);
    if (vtemp.size() < 2) {
      continue;
    }

    int src_tor = vtemp[0];
    int dst_tor = vtemp[1];
    if (src_tor < 0 || src_tor >= _ntor || dst_tor < 0 || dst_tor >= _ntor) {
      continue;
    }

    vector<int> route;
    route.push_back(src_tor);
    bool valid = true;
    for (size_t i = 2; i < vtemp.size(); i++) {
      if (vtemp[i] < 0 || vtemp[i] >= _ntor) {
        valid = false;
        break;
      }
      route.push_back(vtemp[i]);
    }
    if (!valid) {
      continue;
    }
    route.push_back(dst_tor);
    _rts[src_tor][dst_tor].push_back(route);
  }

  // If no explicit route list exists, at least keep one direct edge route where possible.
  for (int i = 0; i < _ntor; i++) {
    for (int j = 0; j < _ntor; j++) {
      if (i == j) {
        if (_rts[i][j].empty()) {
          _rts[i][j].push_back(vector<int>(1, i));
        }
      } else if (_rts[i][j].empty() && _adjacency[i][j] == 1) {
        vector<int> direct;
        direct.push_back(i);
        direct.push_back(j);
        _rts[i][j].push_back(direct);
      }
    }
  }
}

int FlatTopology::map_server_to_core(int server_id) const {
  if (server_id < 0 || server_id >= _no_of_nodes) {
    return -1;
  }
  if (_uses_compact_core_topology) {
    if ((int)_server_to_core.size() != _no_of_nodes) {
      return -1;
    }
    return _server_to_core[server_id];
  }
  if (_ndl <= 0) {
    return -1;
  }
  return server_id / _ndl;
}

// set number of possible pipes and queues
void FlatTopology::set_params() {

    pipes_tor_serv.resize(_ntor, vector<Pipe*>(_no_of_nodes)); // tors to servers
    queues_tor_serv.resize(_ntor, vector<Queue*>(_no_of_nodes));

    pipes_serv_tor.resize(_no_of_nodes, vector<Pipe*>(_ntor)); // servers to tors
    queues_serv_tor.resize(_no_of_nodes, vector<Queue*>(_ntor));

    pipes_tor_tor.resize(_ntor, vector<Pipe*>(_ntor)); // tors to tors
    queues_tor_tor.resize(_ntor, vector<Queue*>(_ntor));
}

Queue* FlatTopology::alloc_src_queue(QueueLogger* queueLogger) {
    return  new PriorityQueue(speedFromMbps((uint64_t)HOST_NIC), memFromPkt(FEEDER_BUFFER), *eventlist, queueLogger);
}

Queue* FlatTopology::alloc_queue(QueueLogger* queueLogger, mem_b queuesize) {
    return alloc_queue(queueLogger, HOST_NIC, queuesize);
}

Queue* FlatTopology::alloc_queue(QueueLogger* queueLogger, uint64_t speed, mem_b queuesize) {
    if (qt==RANDOM)
      return new RandomQueue(speedFromMbps(speed), memFromPkt(SWITCH_BUFFER + RANDOM_BUFFER), *eventlist, queueLogger, memFromPkt(RANDOM_BUFFER));
    else if (qt==COMPOSITE)
      return new CompositeQueue(speedFromMbps(speed), queuesize, *eventlist, queueLogger);
    else if (qt==DCTCP)
      return new ECNQueue(speedFromMbps(speed), queuesize, *eventlist, queueLogger, memFromPkt(ECN_K));
    else if (qt==BOLT)
      return new BoltQueue(speedFromMbps(speed), queuesize, *eventlist, queueLogger);
    else if (qt==HPCC)
      return new INTQueue(speedFromMbps(speed), queuesize, *eventlist, queueLogger);
    assert(0);
}

// initializes all the pipes and queues in the Topology
void FlatTopology::init_network() {
  QueueLoggerSampling* queueLogger;

  // initialize pipes/queues between ToRs and servers
  for (int j = 0; j < _ntor; j++) { // sweep ToR switches
    for (int k = 0; k < _no_of_nodes; k++) { // sweep servers
      queues_tor_serv[j][k] = NULL;
      pipes_tor_serv[j][k] = NULL;
      queues_serv_tor[k][j] = NULL;
      pipes_serv_tor[k][j] = NULL;
    }
  }

  // create pipes/queues between ToRs and servers
  if (_uses_compact_core_topology) {
    for (int k = 0; k < _no_of_nodes; k++) { // sweep servers
      int j = map_server_to_core(k);
      if (j < 0 || j >= _ntor) continue;

      // Downlink: core node to server
      queueLogger = new QueueLoggerSampling(timeFromMs(1000), *eventlist);
      logfile->addLogger(*queueLogger);
      queues_tor_serv[j][k] = alloc_queue(queueLogger, _queuesize);
      pipes_tor_serv[j][k] = new Pipe(timeFromNs(RTT_rack), *eventlist);
      pipes_tor_serv[j][k]->setlongname("Pipe-TOR" + ntoa(j)  + "->DST" + ntoa(k));
      pipes_tor_serv[j][k]->set_pipe_downlink();

      // Uplink: server to core node
      queueLogger = new QueueLoggerSampling(timeFromMs(1000), *eventlist);
      logfile->addLogger(*queueLogger);
      queues_serv_tor[k][j] = alloc_src_queue(queueLogger);
      pipes_serv_tor[k][j] = new Pipe(timeFromNs(RTT_rack), *eventlist);
      pipes_serv_tor[k][j]->setlongname("Pipe-SRC" + ntoa(k) + "->TOR" + ntoa(j));
    }
  } else {
    for (int j = 0; j < _ntor; j++) { // sweep ToRs
      for (int l = 0; l < _ndl; l++) { // sweep ToR downlinks
        int k = j * _ndl + l;
        if (k < 0 || k >= _no_of_nodes) continue;

        // Downlink: ToR to server
        queueLogger = new QueueLoggerSampling(timeFromMs(1000), *eventlist);
        logfile->addLogger(*queueLogger);
        queues_tor_serv[j][k] = alloc_queue(queueLogger, _queuesize);
        //queues_tor_serv[j][k]->setName("TOR" + ntoa(j) + "->DST" +ntoa(k));
        //logfile->writeName(*(queues_tor_serv[j][k]));
        pipes_tor_serv[j][k] = new Pipe(timeFromNs(RTT_rack), *eventlist);
        pipes_tor_serv[j][k]->setlongname("Pipe-TOR" + ntoa(j)  + "->DST" + ntoa(k));
        //pipes_tor_serv[j][k]->setName("Pipe-TOR" + ntoa(j)  + "->DST" + ntoa(k));
        //logfile->writeName(*(pipes_tor_serv[j][k]));


        pipes_tor_serv[j][k]->set_pipe_downlink(); // modification - set this for the UtilMonitor


        // Uplink: server to ToR
        queueLogger = new QueueLoggerSampling(timeFromMs(1000), *eventlist);
        logfile->addLogger(*queueLogger);
        queues_serv_tor[k][j] = alloc_src_queue(queueLogger);
        //queues_serv_tor[k][j]->setName("SRC" + ntoa(k) + "->TOR" +ntoa(j));
        //logfile->writeName(*(queues_serv_tor[k][j]));
        pipes_serv_tor[k][j] = new Pipe(timeFromNs(RTT_rack), *eventlist);
        pipes_serv_tor[k][j]->setlongname("Pipe-SRC" + ntoa(k) + "->TOR" + ntoa(j));
        //pipes_serv_tor[k][j]->setName("Pipe-SRC" + ntoa(k) + "->TOR" + ntoa(j));
        //logfile->writeName(*(pipes_serv_tor[k][j]));

      }
    }
  }

  // initialize pipes/queues between ToRs
  for (int j = 0; j < _ntor; j++) // sweep "source" ToR switches
    for (int k = 0; k < _ntor; k++) { // sweep "destination" ToR switches
      queues_tor_tor[j][k] = NULL;
      pipes_tor_tor[j][k] = NULL;
    }

    int pipe_cnt = 0;
  // create pipes/queues between ToRs
  for (int j = 0; j < _ntor; j++) { // sweep "source" ToR switches
    for (int k = 0; k < _ntor; k++) { // sweep "destination" ToR switches
      
      if (_adjacency[j][k] == 1){

        // add pipe and queue
        queueLogger = new QueueLoggerSampling(timeFromMs(1000), *eventlist);
        logfile->addLogger(*queueLogger);
        queues_tor_tor[j][k] = alloc_queue(queueLogger, _queuesize);
        //queues_tor_tor[j][k]->setName("TOR" + ntoa(j) + "->TOR" +ntoa(k));
        //logfile->writeName(*(queues_tor_tor[j][k]));
        pipes_tor_tor[j][k] = new Pipe(timeFromNs(RTT_net), *eventlist);
        pipes_tor_tor[j][k]->setlongname("Pipe-TOR" + ntoa(j)  + "->ToR" + ntoa(k));
        //pipes_tor_tor[j][k]->setName("Pipe-TOR" + ntoa(j)  + "->ToR" + ntoa(k));
        //logfile->writeName(*(pipes_tor_tor[j][k]));

        //if (j == 0) {
        //if (k == 9) {
        //  pipes_tor_tor[j][k]->set_uplink_pipe_id(pipe_cnt);
        //  pipe_cnt++;
        //}

      }
    }
  }

}

void check_non_null(Route* rt){
  int fail = 0;
  for (unsigned int i=1; i<rt->size()-1; i+=2)
    if (rt->at(i)==NULL){
      fail = 1;
      break;
    }
  
  if (fail){
    //    cout <<"Null queue in route"<<endl;
    for (unsigned int i=1; i<rt->size()-1; i+=2)
      printf("%p ",rt->at(i));

    cout<<endl;
    assert(0);
  }
}

int FlatTopology::get_num_shortest_paths(int src, int dest) {
  int srcrack = map_server_to_core(src); // index of source core node
  int destrack = map_server_to_core(dest); // index of destination core node
  if (srcrack < 0 || destrack < 0 || srcrack >= _ntor || destrack >= _ntor) {
    return 0;
  }
  if (srcrack == destrack)
    return 1;
  else if (!_rts.empty() && !_rts[srcrack][destrack].empty())
    return _rts[srcrack][destrack].size();
  else if (_adjacency[srcrack][destrack] == 1)
    return 1;
  else
    return 0;
}

bool FlatTopology::get_single_path_from_tors(int src,
                                             int dest,
                                             const vector<int>& tor_path,
                                             vector<const Route*>*& paths,
                                             string* err_msg) {
  paths = nullptr;

  int srcrack = map_server_to_core(src);
  int destrack = map_server_to_core(dest);
  if (srcrack < 0 || srcrack >= _ntor || destrack < 0 || destrack >= _ntor) {
    if (err_msg) {
      *err_msg = "source/destination server id out of range or unmapped";
    }
    return false;
  }

  vector<int> tor_seq = tor_path;
  if (tor_seq.empty()) {
    tor_seq.push_back(srcrack);
    if (srcrack != destrack) {
      tor_seq.push_back(destrack);
    }
  } else {
    if (tor_seq.front() != srcrack) {
      tor_seq.insert(tor_seq.begin(), srcrack);
    }
    if (tor_seq.back() != destrack) {
      tor_seq.push_back(destrack);
    }
  }

  for (size_t i = 0; i < tor_seq.size(); ++i) {
    int tor = tor_seq[i];
    if (tor < 0 || tor >= _ntor) {
      if (err_msg) {
        *err_msg = "ToR id out of range: " + itoa((uint64_t)tor);
      }
      return false;
    }
  }

  if (srcrack == destrack) {
    if (tor_seq.size() != 1 || tor_seq[0] != srcrack) {
      if (err_msg) {
        *err_msg = "same-rack flow expects empty path or single ToR id";
      }
      return false;
    }
  } else if (tor_seq.size() < 2) {
    if (err_msg) {
      *err_msg = "cross-rack flow path is too short";
    }
    return false;
  }

  for (size_t i = 0; i + 1 < tor_seq.size(); ++i) {
    int a = tor_seq[i];
    int b = tor_seq[i + 1];
    if (a == b) {
      if (err_msg) {
        *err_msg = "consecutive ToR ids must differ";
      }
      return false;
    }
    if (_adjacency[a][b] != 1) {
      if (err_msg) {
        *err_msg = "invalid ToR hop " + itoa((uint64_t)a) + "->" + itoa((uint64_t)b);
      }
      return false;
    }
    if (queues_tor_tor[a][b] == NULL || pipes_tor_tor[a][b] == NULL) {
      if (err_msg) {
        *err_msg = "missing queue/pipe for ToR hop " + itoa((uint64_t)a) + "->" + itoa((uint64_t)b);
      }
      return false;
    }
  }

  if (queues_serv_tor[src][srcrack] == NULL || pipes_serv_tor[src][srcrack] == NULL) {
    if (err_msg) {
      *err_msg = "missing server uplink " + itoa((uint64_t)src) + "->" + itoa((uint64_t)srcrack);
    }
    return false;
  }
  if (queues_tor_serv[destrack][dest] == NULL || pipes_tor_serv[destrack][dest] == NULL) {
    if (err_msg) {
      *err_msg = "missing server downlink " + itoa((uint64_t)destrack) + "->" + itoa((uint64_t)dest);
    }
    return false;
  }

  Route* routeout = new Route();
  routeout->push_back(queues_serv_tor[src][srcrack]);
  routeout->push_back(pipes_serv_tor[src][srcrack]);

  for (size_t i = 0; i + 1 < tor_seq.size(); ++i) {
    int a = tor_seq[i];
    int b = tor_seq[i + 1];
    routeout->push_back(queues_tor_tor[a][b]);
    routeout->push_back(pipes_tor_tor[a][b]);
  }

  routeout->push_back(queues_tor_serv[destrack][dest]);
  routeout->push_back(pipes_tor_serv[destrack][dest]);

  Route* routeback = new Route();
  routeback->push_back(queues_serv_tor[dest][destrack]);
  routeback->push_back(pipes_serv_tor[dest][destrack]);

  for (int i = (int)tor_seq.size() - 1; i > 0; --i) {
    int a = tor_seq[i];
    int b = tor_seq[i - 1];
    routeback->push_back(queues_tor_tor[a][b]);
    routeback->push_back(pipes_tor_tor[a][b]);
  }

  routeback->push_back(queues_tor_serv[srcrack][src]);
  routeback->push_back(pipes_tor_serv[srcrack][src]);

  routeout->set_reverse(routeback);
  routeback->set_reverse(routeout);

  check_non_null(routeout);
  check_non_null(routeback);

  paths = new vector<const Route*>();
  paths->push_back(routeout);
  return true;
}

// defines the routes between `src` and `dest` servers
vector<const Route*>* FlatTopology::get_paths(int src, int dest, bool vlb) {
  
  vector<const Route*>* paths = new vector<const Route*>();
  route_t *routeout, *routeback;

  int srcrack = map_server_to_core(src); // index of source core node
  int destrack = map_server_to_core(dest); // index of destination core node
  if (srcrack < 0 || srcrack >= _ntor || destrack < 0 || destrack >= _ntor) {
    return paths;
  }
  
  // if `src` and `dest` are in the same rack:
  if (srcrack == destrack) {

    // forward path
    routeout = new Route();
    routeout->push_back(queues_serv_tor[src][srcrack]);
    routeout->push_back(pipes_serv_tor[src][srcrack]);

    routeout->push_back(queues_tor_serv[srcrack][dest]);
    routeout->push_back(pipes_tor_serv[srcrack][dest]);

    // reverse path for RTS packets
    routeback = new Route();
    routeback->push_back(queues_serv_tor[dest][srcrack]);
    routeback->push_back(pipes_serv_tor[dest][srcrack]);

    routeback->push_back(queues_tor_serv[srcrack][src]);
    routeback->push_back(pipes_tor_serv[srcrack][src]);

    routeout->set_reverse(routeback);
    routeback->set_reverse(routeout);

    //print_route(*routeout);
    paths->push_back(routeout);
    check_non_null(routeout);

    return paths;
  }
  else { // `src` and `dest` are in different racks
    
    // all paths (previously read from file)

    // first, get the k shortest paths:

    int npaths = _rts[srcrack][destrack].size();

    for (int i = 0; i < npaths; i++) {
      
      // forward path
      routeout = new Route();
      routeout->push_back(queues_serv_tor[src][srcrack]);
      routeout->push_back(pipes_serv_tor[src][srcrack]);

      int nhops = _rts[srcrack][destrack][i].size();

      for (int j = 0; j < nhops-1; j++){
        routeout->push_back(queues_tor_tor[_rts[srcrack][destrack][i][j]][_rts[srcrack][destrack][i][j+1]]);
        routeout->push_back(pipes_tor_tor[_rts[srcrack][destrack][i][j]][_rts[srcrack][destrack][i][j+1]]);
      }

      routeout->push_back(queues_tor_serv[destrack][dest]);
      routeout->push_back(pipes_tor_serv[destrack][dest]);

      // reverse path for RTS packets
      routeback = new Route();
      routeback->push_back(queues_serv_tor[dest][destrack]);
      routeback->push_back(pipes_serv_tor[dest][destrack]);

      for (int j = nhops-1; j > 0; j--){
        routeback->push_back(queues_tor_tor[_rts[srcrack][destrack][i][j]][_rts[srcrack][destrack][i][j-1]]);
        routeback->push_back(pipes_tor_tor[_rts[srcrack][destrack][i][j]][_rts[srcrack][destrack][i][j-1]]);
      }
      
      routeback->push_back(queues_tor_serv[srcrack][src]);
      routeback->push_back(pipes_tor_serv[srcrack][src]);

      routeout->set_reverse(routeback);
      routeback->set_reverse(routeout);

      paths->push_back(routeout);
      check_non_null(routeout);
    }

    if (vlb) {

    // next, get the VLB routes:

    int NVLB = 20;

    for (int imrack_ind = 0; imrack_ind < NVLB; imrack_ind++) { // sweep NVLB possible intermediate ToRs 

    	int imrack = rand() % _ntor; // pick NVLB intermediate ToRs randomly

      if (imrack != srcrack && imrack != destrack) {

        int npaths1 = _rts[srcrack][imrack].size();

        for (int i = 0; i < npaths1; i++) {
          
          // forward path
          routeout = new Route();
          routeout->push_back(queues_serv_tor[src][srcrack]);
          routeout->push_back(pipes_serv_tor[src][srcrack]);

          int nhops = _rts[srcrack][imrack][i].size();
          for (int j = 0; j < nhops-1; j++){
            routeout->push_back(queues_tor_tor[_rts[srcrack][imrack][i][j]][_rts[srcrack][imrack][i][j+1]]);
            routeout->push_back(pipes_tor_tor[_rts[srcrack][imrack][i][j]][_rts[srcrack][imrack][i][j+1]]);
          }

          // we're at the intermediate ToR, now fill in the path from here to the destination
          // !!! note - hardcoding only one path for now !!!

          //int pathchoice = 0;

          // 3/15/19 - modification to increase path diversity:
          int npaths2 = _rts[imrack][destrack].size();
          int pathchoice = random() % npaths2; // randomize the path selection from intermediate ToR to dest ToR.

          
          nhops = _rts[imrack][destrack][pathchoice].size();
          for (int j = 0; j < nhops-1; j++){
            routeout->push_back(queues_tor_tor[_rts[imrack][destrack][pathchoice][j]][_rts[imrack][destrack][pathchoice][j+1]]);
            routeout->push_back(pipes_tor_tor[_rts[imrack][destrack][pathchoice][j]][_rts[imrack][destrack][pathchoice][j+1]]);
          }

          routeout->push_back(queues_tor_serv[destrack][dest]);
          routeout->push_back(pipes_tor_serv[destrack][dest]);

          // -------------------------

          // reverse path for RTS packets
          routeback = new Route();
          routeback->push_back(queues_serv_tor[dest][destrack]);
          routeback->push_back(pipes_serv_tor[dest][destrack]);

          nhops = _rts[imrack][destrack][pathchoice].size();
          for (int j = nhops-1; j > 0; j--){
            routeback->push_back(queues_tor_tor[_rts[imrack][destrack][pathchoice][j]][_rts[imrack][destrack][pathchoice][j-1]]);
            routeback->push_back(pipes_tor_tor[_rts[imrack][destrack][pathchoice][j]][_rts[imrack][destrack][pathchoice][j-1]]);
          }

          // we're at the intermediate ToR

          nhops = _rts[srcrack][imrack][i].size();
          for (int j = nhops-1; j > 0; j--){
            routeback->push_back(queues_tor_tor[_rts[srcrack][imrack][i][j]][_rts[srcrack][imrack][i][j-1]]);
            routeback->push_back(pipes_tor_tor[_rts[srcrack][imrack][i][j]][_rts[srcrack][imrack][i][j-1]]);
          }
      
          routeback->push_back(queues_tor_serv[srcrack][src]);
          routeback->push_back(pipes_tor_serv[srcrack][src]);

          routeout->set_reverse(routeback);
          routeback->set_reverse(routeout);

          paths->push_back(routeout);
          check_non_null(routeout);
        }
      }
    }
    }
    return paths;
  }
}

void FlatTopology::count_queue(Queue* queue){
  if (_link_usage.find(queue)==_link_usage.end()){
    _link_usage[queue] = 0;
  }

  _link_usage[queue] = _link_usage[queue] + 1;
}




//////////////////////////////////////////////
//      Aggregate utilization monitor       //
//////////////////////////////////////////////


UtilMonitor::UtilMonitor(FlatTopology* top, EventList &eventlist)
  : EventSource(eventlist,"utilmonitor"), _top(top)
{

    _H = _top->get_no_of_nodes(); // number of hosts
    _N = _top->get_ntor(); // racks
    _hpr = _top->get_ndl(); // hosts per rack
    uint64_t rate = 10000000000 / 8; // bytes / second
    rate = rate * _H;

    _max_agg_Bps = rate;

    // debug:
    //cout << "max bytes per second = " << rate << endl;

}

void UtilMonitor::start(simtime_picosec period) {
    _period = period;
    _max_B_in_period = _max_agg_Bps * timeAsSec(_period);

    // debug:
    //cout << "_max_pkts_in_period = " << _max_pkts_in_period << endl;

    eventlist().sourceIsPending(*this, _period);
}

void UtilMonitor::doNextEvent() {
    printAggUtil();
}

void UtilMonitor::printAggUtil() {

    uint64_t B_sum = 0;

    for (int tor = 0; tor < _N; tor++) {
        for (int host = 0; host < _H; host++) {
            Pipe* pipe = _top->get_downlink(tor, host);
            if (pipe != NULL) {
                B_sum = B_sum + pipe->reportBytes();
            }
        }
    }

    // debug:
    //cout << "B_sum = " << B_sum << endl;
    //cout << "_max_B_in_period = " << _max_B_in_period << endl;

    double util = (double)B_sum / (double)_max_B_in_period;

    // cout << "Util " << fixed << util << " " << timeAsMs(eventlist().now()) << endl;
    OUTPUT_LOG << "Util " << fixed << util << " " << timeAsMs(eventlist().now()) << "\n";

    //if (eventlist().now() + _period < eventlist().getEndtime())
    eventlist().sourceIsPendingRel(*this, _period);

}
