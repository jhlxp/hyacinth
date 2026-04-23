// -*- c-basic-offset: 4; tab-width: 8; indent-tabs-mode: t -*-
#include "config.h"
#include <sstream>
#include <strstream>
#include <fstream>
#include <iostream>
#include <string.h>
#include <math.h>
#include <unistd.h>
#include <sys/stat.h>
#include <dirent.h>
#include <sys/types.h>
#include "network.h"
#include "pipe.h"
#include "eventlist.h"
#include "logfile.h"
#include "loggers.h"
#include "clock.h"
#include "topology.h"
#include "flat_topology.h"
#include "tcp.h"
#include "bolt.h"
#include "dag_manager.h"
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
OutputLogger OUTPUT_LOG;

std::vector<std::string> load_dep_files(const std::string& depdir);

void exit_error(char* progr) {
    cerr << "Usage " << progr
         << " -depdir <dir> -topfile <file> -outputfile <file> "
         << "[-simtime s] [-utiltime s] [-q pkts] [-cwnd pkts] [-ssthresh n]"
         << endl;
    exit(1);
}

int main(int argc, char **argv) {
    Packet::set_packet_size(DEFAULT_PACKET_SIZE - DEFAULT_HEADER_SIZE);
    mem_b queuesize = DEFAULT_QUEUE_SIZE * DEFAULT_PACKET_SIZE;

    stringstream filename(ios_base::out);
    string depdir;
    string topfile;
    string outputfile;
    double simtime = 1.0;
    double utiltime = 0.01;
    int cwnd = 30;
    int ssthresh = -1;

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
        } else if (!strcmp(argv[i], "-depdir")) {
            depdir = argv[i + 1];
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
        } else if (!strcmp(argv[i], "-cwnd")) {
            cwnd = atoi(argv[i + 1]);
            i++;
        } else if (!strcmp(argv[i], "-ssthresh")) {
            ssthresh = atoi(argv[i + 1]);
            i++;
        } else {
            exit_error(argv[0]);
        }
        i++;
    }

    if (depdir.empty() || topfile.empty() || outputfile.empty()) {
        exit_error(argv[0]);
    }

    srand(42);
    eventlist.setEndtime(timeFromSec(simtime));
    Clock c(timeFromSec(5 / 100.), eventlist);

    size_t flush_every = 10000;
    size_t buf_size = 128 * 1024 * 1024;
    OUTPUT_LOG.init(outputfile, flush_every, buf_size);

    Logfile logfile(filename.str(), eventlist);
    logfile.setStartTime(timeFromSec(100));

    TcpSinkLoggerSampling sinkLogger(timeFromUs(50.), eventlist);
    logfile.addLogger(sinkLogger);
    TcpTrafficLogger traffic_logger;
    logfile.addLogger(traffic_logger);

    TcpRtxTimerScanner tcpRtxScanner(timeFromMs(1), eventlist);
    FlatTopology* top = new FlatTopology(queuesize, &logfile, &eventlist, BOLT, topfile);

    DagManager dagman;
    dagman.set_runtime_context_tcp(&eventlist,
                                   top,
                                   &tcpRtxScanner,
                                   &sinkLogger,
                                   cwnd,
                                   DagManager::TRANSPORT_BOLT,
                                   0,
                                   0.95,
                                   ssthresh);

    std::vector<std::string> dep_files = load_dep_files(depdir);
    dagman.load_from_files(dep_files);
    dagman.start_all_ready();

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

std::vector<std::string> load_dep_files(const std::string& depdir) {
    std::vector<std::string> dep_files;

    if (depdir.empty()) {
        std::cerr << "[ERROR] Missing -depdir parameter. Please specify the DAG folder path." << std::endl;
        exit(1);
    }

    struct stat sb;
    if (stat(depdir.c_str(), &sb) != 0 || !S_ISDIR(sb.st_mode)) {
        std::cerr << "[ERROR] Dependency directory not found or invalid: " << depdir << std::endl;
        exit(1);
    }

    DIR *dir = opendir(depdir.c_str());
    if (!dir) {
        std::cerr << "[ERROR] Cannot open directory: " << depdir << std::endl;
        exit(1);
    }

    struct dirent *entry;
    while ((entry = readdir(dir)) != NULL) {
        std::string fname(entry->d_name);
        if (fname.size() > 4 && fname.substr(fname.size() - 4) == ".txt") {
            dep_files.push_back(depdir + "/" + fname);
        }
    }
    closedir(dir);

    if (dep_files.empty()) {
        std::cerr << "[ERROR] No dependency files (.txt) found in " << depdir << std::endl;
        exit(1);
    }

    std::cout << "[INFO] Loaded " << dep_files.size()
              << " DAG files from " << depdir << std::endl;
    return dep_files;
}
