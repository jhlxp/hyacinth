// -*- c-basic-offset: 4; tab-width: 8; indent-tabs-mode: t -*-
#include "config.h"
#include <sstream>
#include <strstream>
#include <fstream>
#include <iostream>
#include <string.h>
#include <math.h>
#include <cctype>
#include "network.h"
#include "pipe.h"
#include "eventlist.h"
#include "logfile.h"
#include "loggers.h"
#include "clock.h"
#include "topology.h"
#include "flat_topology.h"
#include "tcp.h"
#include "dctcp.h"
#include "output_log.h"

#include <list>

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
uint64_t flow_id_gen = 0;
OutputLogger OUTPUT_LOG;

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

void exit_error(char* progr) {
    cerr << "Usage " << progr
         << " -flowfile <file> -topfile <file> -outputfile <file> "
         << "[-simtime s] [-utiltime s] [-q pkts] [-cwnd pkts] [-ssthresh n]"
         << endl;
    exit(1);
}

int main(int argc, char **argv) {
    Packet::set_packet_size(DEFAULT_PACKET_SIZE - DEFAULT_HEADER_SIZE);
    mem_b queuesize = DEFAULT_QUEUE_SIZE * DEFAULT_PACKET_SIZE;

    stringstream filename(ios_base::out);
    string flowfile;
    string topfile;
    string outputfile;
    double simtime = 1.0;
    double utiltime = .01;
    int ssthresh = -1;
    unsigned cwnd = 30;

    int i = 1;
    filename << "logout.dat";
    while (i < argc) {
        if (!strcmp(argv[i], "-o")) {
            filename.str(std::string());
            filename << argv[i + 1];
            i++;
        } else if (!strcmp(argv[i], "-q")) {
            queuesize = atoi(argv[i + 1]) * DEFAULT_PACKET_SIZE;
            i++;
        } else if (!strcmp(argv[i], "-flowfile")) {
            flowfile = argv[i + 1];
            i++;
        } else if (!strcmp(argv[i], "-topfile")) {
            topfile = argv[i + 1];
            i++;
        } else if (!strcmp(argv[i], "-outputfile")) {
            outputfile = argv[i + 1];
            i++;
        } else if (!strcmp(argv[i], "-simtime")) {
            simtime = atof(argv[i + 1]);
            i++;
        } else if (!strcmp(argv[i], "-utiltime")) {
            utiltime = atof(argv[i + 1]);
            i++;
        } else if (!strcmp(argv[i], "-ssthresh")) {
            ssthresh = atoi(argv[i + 1]);
            i++;
        } else if (!strcmp(argv[i], "-cwnd")) {
            cwnd = atoi(argv[i + 1]);
            i++;
        } else {
            exit_error(argv[0]);
        }
        i++;
    }

    if (flowfile.empty() || topfile.empty()) {
        cerr << "[dctcp_flat] ERROR: -flowfile and -topfile are required." << endl;
        return 1;
    }
    if (outputfile.empty()) {
        cerr << "[dctcp_flat] ERROR: -outputfile is required." << endl;
        return 1;
    }

    srand(13);
    eventlist.setEndtime(timeFromSec(simtime));
    Clock c(timeFromSec(5 / 100.), eventlist);

    Logfile logfile(filename.str(), eventlist);
    logfile.setStartTime(timeFromSec(100));

    size_t flush_every = 1;
    size_t buf_size = 1 * 1024 * 1024;
    OUTPUT_LOG.init(outputfile, flush_every, buf_size);

    TcpSinkLoggerSampling sinkLogger(timeFromUs(50.), eventlist);
    logfile.addLogger(sinkLogger);
    TcpTrafficLogger traffic_logger;
    logfile.addLogger(traffic_logger);

    TcpRtxTimerScanner tcpRtxScanner(timeFromMs(1), eventlist);
    FlatTopology* top = new FlatTopology(queuesize, &logfile, &eventlist, DCTCP, topfile);

    ifstream input(flowfile);
    if (!input.is_open()) {
        cerr << "[dctcp_flat] ERROR: cannot open flowfile: " << flowfile << endl;
        return 1;
    }

    string line;
    int line_no = 0;
    while (getline(input, line)) {
        line_no++;
        size_t first_non_ws = line.find_first_not_of(" \t\r");
        if (first_non_ws == string::npos || line[first_non_ws] == '#') continue;
        size_t comment_pos = line.find('#');
        if (comment_pos != string::npos) line = line.substr(0, comment_pos);

        vector<string> tokens;
        stringstream stream(line);
        string token;
        while (stream >> token) tokens.push_back(token);
        if (tokens.empty()) continue;
        if (tokens.size() < 4) {
            cerr << "[dctcp_flat] Skip malformed flow line " << line_no
                 << ": need at least 4 columns, got " << tokens.size() << endl;
            continue;
        }

        int64_t flow_src64 = 0, flow_dst64 = 0, flow_bytes = 0;
        double flow_start_ns_f = 0.0;
        if (!parse_int64_token(tokens[0], flow_src64) ||
            !parse_int64_token(tokens[1], flow_dst64) ||
            !parse_int64_token(tokens[2], flow_bytes) ||
            !parse_double_token(tokens[3], flow_start_ns_f)) {
            cerr << "[dctcp_flat] Skip malformed numeric fields at line " << line_no << endl;
            continue;
        }
        if (flow_start_ns_f < 0.0) {
            cerr << "[dctcp_flat] Skip malformed flow line " << line_no
                 << ": start time must be >= 0" << endl;
            continue;
        }
        int64_t flow_start_ns = (int64_t)llround(flow_start_ns_f);
        int flow_src = (int)flow_src64;
        int flow_dst = (int)flow_dst64;

        bool has_explicit_path = false;
        vector<int> explicit_tor_path;
        int flow_group_id = -1;
        for (size_t tok_idx = 4; tok_idx < tokens.size(); ++tok_idx) {
            const string& extra = tokens[tok_idx];
            if (extra == "-") continue;

            int64_t maybe_group = 0;
            if (parse_int64_token(extra, maybe_group)) {
                flow_group_id = (int)maybe_group;
                continue;
            }
            if (extra.rfind("group=", 0) == 0) {
                int64_t gid = 0;
                if (parse_int64_token(extra.substr(6), gid)) flow_group_id = (int)gid;
                continue;
            }
            if (extra.rfind("deps=", 0) == 0) continue;
            if (is_comma_int_list(extra)) continue;
            if (extra.rfind("path=", 0) == 0) {
                string err;
                if (!parse_tor_path(extra.substr(5), explicit_tor_path, err)) {
                    cerr << "[dctcp_flat] Invalid path token at line " << line_no
                         << ": " << err << endl;
                    has_explicit_path = false;
                    explicit_tor_path.clear();
                    continue;
                }
                has_explicit_path = true;
                continue;
            }
        }

        if (!has_explicit_path) {
            cerr << "[dctcp_flat] Skip flow line " << line_no
                 << ": missing path= token" << endl;
            continue;
        }

        vector<const Route*>* srcpaths = nullptr;
        vector<const Route*>* dstpaths = nullptr;
        string err_msg;
        if (!top->get_single_path_from_tors(flow_src, flow_dst, explicit_tor_path, srcpaths, &err_msg)) {
            cerr << "[dctcp_flat] Skip flow line " << line_no
                 << ", invalid src->dst path: " << err_msg << endl;
            continue;
        }
        vector<int> reverse_tor_path(explicit_tor_path.rbegin(), explicit_tor_path.rend());
        if (!top->get_single_path_from_tors(flow_dst, flow_src, reverse_tor_path, dstpaths, &err_msg)) {
            cerr << "[dctcp_flat] Skip flow line " << line_no
                 << ", invalid dst->src path: " << err_msg << endl;
            continue;
        }

        if (!srcpaths || srcpaths->empty() || !dstpaths || dstpaths->empty()) {
            cerr << "[dctcp_flat] Skip flow line " << line_no
                 << ": no available route object" << endl;
            continue;
        }

        TcpSrc* flowSrc = new DCTCPSrc(NULL, NULL, eventlist, flow_src, flow_dst);
        TcpSink* flowSnk = new TcpSink();
        flowSrc->set_coflow_group_id(flow_group_id);
        flowSrc->set_flowsize((uint64_t)flow_bytes);
        flowSrc->set_flowid(flow_id_gen++);
        flowSrc->set_cwnd(cwnd);
        flowSrc->_rto = timeFromMs(1);
        if (ssthresh > 0) {
            flowSrc->set_ssthresh((uint64_t)ssthresh * Packet::data_packet_size());
        }
        tcpRtxScanner.registerTcp(*flowSrc);

        Route* routeout = new Route(*(srcpaths->at(0)));
        routeout->push_back(flowSnk);
        Route* routein = new Route(*(dstpaths->at(0)));
        routein->push_back(flowSrc);
        routeout->set_reverse(routein);
        routein->set_reverse(routeout);

        flowSrc->connect(*routeout, *routein, *flowSnk, timeFromNs(flow_start_ns / 1.));
        sinkLogger.monitorSink(flowSnk);
    }

    UtilMonitor* UM = new UtilMonitor(top, eventlist);
    UM->start(timeFromSec(utiltime));

    logfile.write("# pktsize=" + ntoa(Packet::data_packet_size()) + " bytes");
    logfile.write("# hostnicrate = " + ntoa(HOST_NIC) + " pkt/sec");
    logfile.write("# corelinkrate = " + ntoa(HOST_NIC * CORE_TO_HOST) + " pkt/sec");

    while (eventlist.doNextEvent()) {}
    OUTPUT_LOG.finalFlush();
    return 0;
}

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
