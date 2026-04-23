// -*- c-basic-offset: 4; tab-width: 8; indent-tabs-mode: t -*-        
#include "config.h"
#include <sstream>
#include <strstream>
#include <fstream> // need to read flows
#include <iostream>
#include <string.h>
#include <math.h>
#include <cctype>
#include "network.h"
#include "randomqueue.h"
#include "pipe.h"
#include "eventlist.h"
#include "logfile.h"
#include "loggers.h"
#include "clock.h"
#include "ndp.h"
#include "compositequeue.h"
#include "topology.h"
#include "flat_topology.h"
#include "output_log.h"

#include <list>

// Simulation params
#define PRINT_PATHS 0
#define PERIODIC 0
#include "main.h"

uint32_t RTT_rack = 0; // ns
uint32_t RTT_net = 500; // ns

#define DEFAULT_PACKET_SIZE 1500 // Bytes
#define DEFAULT_HEADER_SIZE 64   // Bytes
#define DEFAULT_QUEUE_SIZE 8

string ntoa(double n);
string itoa(uint64_t n);

EventList eventlist;                    
FlatTopology* top = nullptr;      
NdpRtxTimerScanner* ndpRtxScanner = nullptr; 
NdpSinkLoggerSampling* sinkLogger = nullptr; 

Logfile* lg;

OutputLogger OUTPUT_LOG;

void exit_error(char* progr){
    cout << "Usage " << progr
         << " [UNCOUPLED(DEFAULT)|COUPLED_INC|FULLY_COUPLED|COUPLED_EPSILON] [epsilon][COUPLED_SCALABLE_TCP"
         << endl;
    exit(1);
}

void print_path(std::ofstream &paths, const Route* rt){
    for (unsigned int i=1;i<rt->size()-1;i+=2){
        RandomQueue* q = (RandomQueue*)rt->at(i);
        if (q!=NULL)
            paths << q->str() << " ";
        else 
            paths << "NULL ";
    }
    paths << endl;
}

namespace {
bool parse_int64_token(const string& token, int64_t& value) {
    try {
        size_t pos = 0;
        long long v = stoll(token, &pos);
        if (pos != token.size()) return false;
        value = (int64_t)v;
        return true;
    } catch (...) {
        return false;
    }
}

bool parse_double_token(const string& token, double& value) {
    try {
        size_t pos = 0;
        double v = stod(token, &pos);
        if (pos != token.size()) return false;
        value = v;
        return true;
    } catch (...) {
        return false;
    }
}

bool parse_tor_path(const string& token_value, vector<int>& tor_path, string& err_msg) {
    tor_path.clear();
    string cleaned;
    cleaned.reserve(token_value.size());
    for (char c : token_value) {
        if (isdigit((unsigned char)c)) cleaned.push_back(c);
        else cleaned.push_back(' ');
    }

    stringstream ss(cleaned);
    int tor = -1;
    while (ss >> tor) tor_path.push_back(tor);

    if (tor_path.empty()) {
        err_msg = "empty path= token";
        return false;
    }
    return true;
}

bool is_comma_int_list(const string& token) {
    if (token.empty()) return false;
    bool has_comma = false;
    for (char c : token) {
        if (c == ',') {
            has_comma = true;
            continue;
        }
        if (!isdigit((unsigned char)c)) return false;
    }
    return has_comma;
}
} // namespace

int main(int argc, char **argv) {
    
    Packet::set_packet_size(DEFAULT_PACKET_SIZE - DEFAULT_HEADER_SIZE);
    mem_b queuesize = DEFAULT_QUEUE_SIZE * DEFAULT_PACKET_SIZE;

    stringstream filename(ios_base::out);
    string flowfile; // so we can read the flows from a specified file
    string topfile; // so we can read the topology from a specified file
    string outputfile;
    double pull_rate = 1.0; // so we can set the pull rate from the command line
    double simtime = 1.0; // seconds
    double utiltime = .01; // seconds
    int cwnd = 30;
    
    int i = 1;
    filename << "logout.dat";
    RouteStrategy route_strategy = NOT_SET;

    // parse the command line flags:
    while (i<argc) {
        if (!strcmp(argv[i],"-o")){
            filename.str(std::string());
            filename << argv[i+1];
            i++;
        } else if (!strcmp(argv[i],"-cwnd")){
            cwnd = atoi(argv[i+1]);
            i++;
        } else if (!strcmp(argv[i],"-q")){
            queuesize = atoi(argv[i+1]) * DEFAULT_PACKET_SIZE;
            i++;
        } else if (!strcmp(argv[i],"-strat")){
            if (!strcmp(argv[i+1], "perm")) {
                route_strategy = SCATTER_PERMUTE;
            } else if (!strcmp(argv[i+1], "rand")) {
                route_strategy = SCATTER_RANDOM;
            } else if (!strcmp(argv[i+1], "pull")) {
                route_strategy = PULL_BASED;
            } else if (!strcmp(argv[i+1], "single")) {
                route_strategy = SINGLE_PATH;
            }
            i++;
        } else if (!strcmp(argv[i],"-flowfile")) {
            flowfile = argv[i+1];
            i++;
        } else if (!strcmp(argv[i],"-topfile")) {
            topfile = argv[i+1];
            i++;
        } else if (!strcmp(argv[i],"-outputfile")) {
            outputfile = argv[i+1];
            i++;
        } else if (!strcmp(argv[i],"-pullrate")) {
            pull_rate = atof(argv[i+1]);
            i++;
        } else if (!strcmp(argv[i],"-simtime")) {
            simtime = atof(argv[i+1]);
            i++;
        } else if (!strcmp(argv[i],"-utiltime")) {
            utiltime = atof(argv[i+1]);
            i++;
        } else {
            exit_error(argv[0]);
        }
        i++;
    }
    srand(13);

    size_t flush_every = 1; // write each log line immediately
    size_t buf_size = 1 * 1024 * 1024; // 1MB staging buffer
    OUTPUT_LOG.init(outputfile, flush_every, buf_size);


    eventlist.setEndtime(timeFromSec(simtime));
    Clock c(timeFromSec(5 / 100.), eventlist);

    if (route_strategy == NOT_SET) {
        route_strategy = SINGLE_PATH;
    }

    Logfile logfile(filename.str(), eventlist);

#if PRINT_PATHS
    filename << ".paths";
    cout << "Logging path choices to " << filename.str() << endl;
    std::ofstream paths(filename.str().c_str());
    if (!paths){
	cout << "Can't open for writing paths file!"<<endl;
	exit(1);
    }
#endif

    lg = &logfile;
    logfile.setStartTime(timeFromSec(100));
    
    sinkLogger = new NdpSinkLoggerSampling(timeFromUs(50.), eventlist);
    logfile.addLogger(*sinkLogger);

    NdpTrafficLogger* traffic_logger = new NdpTrafficLogger();
    logfile.addLogger(*traffic_logger);

    ndpRtxScanner = new NdpRtxTimerScanner(timeFromMs(1), eventlist);

#ifdef FLAT
    top = new FlatTopology(queuesize, &logfile, &eventlist, COMPOSITE, topfile);
#endif

    NdpSrc::setMinRTO(1000);
    NdpSrc::setRouteStrategy(route_strategy);
    NdpSink::setRouteStrategy(route_strategy);

    ifstream input(flowfile);
    if (input.is_open()){
        string line;
        int line_no = 0;
        // get flows. Format:
        //   required: src dst bytes starttime_ns
        //   optional extras: group / deps / path=<tor0,tor1,...>
        while(getline(input, line)){
            line_no++;
            size_t first_non_ws = line.find_first_not_of(" \t\r");
            if (first_non_ws == string::npos || line[first_non_ws] == '#')
                continue;
            size_t comment_pos = line.find('#');
            if (comment_pos != string::npos)
                line = line.substr(0, comment_pos);

            vector<string> tokens;
            stringstream stream(line);
            string token;
            while (stream >> token) tokens.push_back(token);
            if (tokens.empty()) continue;
            if (tokens.size() < 4) {
                cerr << "[flat] Skip malformed flow line " << line_no
                     << ": need at least 4 columns, got " << tokens.size() << endl;
                continue;
            }

            int64_t flow_src64 = 0, flow_dst64 = 0, flow_bytes = 0;
            double flow_start_us_f = 0.0;
            if (!parse_int64_token(tokens[0], flow_src64) ||
                !parse_int64_token(tokens[1], flow_dst64) ||
                !parse_int64_token(tokens[2], flow_bytes) ||
                !parse_double_token(tokens[3], flow_start_us_f)) {
                cerr << "[flat] Skip malformed numeric fields at line " << line_no << endl;
                continue;
            }
            if (flow_start_us_f < 0.0) {
                cerr << "[flat] Skip malformed flow line " << line_no
                     << ": start time must be >= 0" << endl;
                continue;
            }
            int64_t flow_start_us = (int64_t) llround(flow_start_us_f);
            
            // source and destination hosts for this flow
            int flow_src = (int)flow_src64;
            int flow_dst = (int)flow_dst64;

            bool has_explicit_path = false;
            vector<int> explicit_tor_path;
            int flow_group_id = -1;
            for (size_t tok_idx = 4; tok_idx < tokens.size(); ++tok_idx) {
                const string& extra = tokens[tok_idx];
                if (extra == "-") continue;
                // Optional raw numeric group-id token, e.g., "... start_ns 37".
                int64_t maybe_group = 0;
                if (parse_int64_token(extra, maybe_group)) {
                    flow_group_id = (int)maybe_group;
                    continue;
                }
                // Optional named group-id token, e.g., "group=37".
                if (extra.rfind("group=", 0) == 0) {
                    int64_t gid = 0;
                    if (!parse_int64_token(extra.substr(6), gid)) {
                        cerr << "[flat] Ignore malformed group token at line " << line_no
                             << ": " << extra << endl;
                    } else {
                        flow_group_id = (int)gid;
                    }
                    continue;
                }
                // Optional dependency token, e.g., "1,3,5" or "deps=1,3,5".
                if (extra.rfind("deps=", 0) == 0) continue;
                if (is_comma_int_list(extra)) continue;
                if (extra.rfind("path=", 0) == 0) {
                    string err;
                    string path_str = extra.substr(5);
                    if (!parse_tor_path(path_str, explicit_tor_path, err)) {
                        cerr << "[flat] Invalid path token at line " << line_no
                             << ": " << err << endl;
                        has_explicit_path = false;
                        explicit_tor_path.clear();
                        continue;
                    }
                    has_explicit_path = true;
                    continue;
                }
                cerr << "[flat] Ignore unknown token at line " << line_no
                     << ": " << extra << endl;
            }

            NdpSrc* flowSrc = new NdpSrc(NULL, NULL, eventlist, flow_src, flow_dst);
            flowSrc->set_coflow_group_id(flow_group_id);
            flowSrc->setCwnd(cwnd*Packet::data_packet_size());
            flowSrc->set_flowsize(flow_bytes); // bytes
            NdpPullPacer* flowpacer = new NdpPullPacer(eventlist, pull_rate); // 1 = pull at line rate   
            NdpSink* flowSnk = new NdpSink(flowpacer);
            ndpRtxScanner->registerNdp(*flowSrc);
            Route* routeout, *routein;
            if (!has_explicit_path) {
                cerr << "[flat] Skip malformed flow line " << line_no
                     << ": network flow must provide path=..." << endl;
                continue;
            }

            vector<const Route*>* srcpaths = nullptr;
            vector<const Route*>* dstpaths = nullptr;
            string err_msg;
            if (!top->get_single_path_from_tors(flow_src, flow_dst, explicit_tor_path, srcpaths, &err_msg)) {
                cerr << "[flat] Skip flow at line " << line_no
                     << ", invalid explicit path (src->dst): " << err_msg << endl;
                continue;
            }
            vector<int> reverse_tor_path(explicit_tor_path.rbegin(), explicit_tor_path.rend());
            if (!top->get_single_path_from_tors(flow_dst, flow_src, reverse_tor_path, dstpaths, &err_msg)) {
                cerr << "[flat] Skip flow at line " << line_no
                     << ", invalid explicit path (dst->src): " << err_msg << endl;
                continue;
            }

            if (!srcpaths || srcpaths->empty() || !dstpaths || dstpaths->empty()) {
                cerr << "[flat] Skip flow at line " << line_no
                     << ", no path available from " << flow_src << " to " << flow_dst << endl;
                continue;
            }

            flowSrc->setvlb(false);
            routeout = new Route(*(srcpaths->at(0)));
            routeout->push_back(flowSnk);
            routein = new Route(*(dstpaths->at(0)));
            routein->push_back(flowSrc);
            // We appended endpoints, so rebuild reverse linkage to keep
            // forward/backward hop counts consistent for bounce handling.
            routeout->set_reverse(routein);
            routein->set_reverse(routeout);
            if (route_strategy == SINGLE_PATH) {
                routeout->set_path_id(0, 1);
                routein->set_path_id(0, 1);
            }

            flowSrc->connect(*routeout, *routein, *flowSnk, timeFromNs(flow_start_us/1.));

            flowSrc->set_num_shortest_paths(1);
            flowSnk->set_num_shortest_paths(1);

            if (route_strategy != SINGLE_PATH) {
                flowSrc->set_paths(srcpaths);
                flowSnk->set_paths(dstpaths);
            }
            sinkLogger->monitorSink(flowSnk);

        }
    } else {
        cerr << "[flat] ERROR: cannot open flowfile: " << flowfile << endl;
        return 1;
    }


    UtilMonitor* UM = new UtilMonitor(top, eventlist);
    UM->start(timeFromSec(utiltime));


    logfile.write("# pktsize=" + ntoa(Packet::data_packet_size()) + " bytes");
    logfile.write("# hostnicrate = " + ntoa(HOST_NIC) + " pkt/sec");
    logfile.write("# corelinkrate = " + ntoa(HOST_NIC * CORE_TO_HOST) + " pkt/sec");

    while (eventlist.doNextEvent()) {}
    OUTPUT_LOG.finalFlush();
}


// =====================================================

string ntoa(double n) {
    stringstream s;
    s << n;
    return s.str();
}

string itoa(uint64_t n) {
    stringstream s;
    s << n;
    return s.str();
}
