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


// Global event list that drives all scheduled simulation events.
EventList eventlist;

// Pointer to the global network topology instance.
FlatTopology* top = nullptr;

// Global retransmission timer scanner used by NDP sources.
NdpRtxTimerScanner* ndpRtxScanner = nullptr;

// Global sink logger for sampling receiver statistics.
NdpSinkLoggerSampling* sinkLogger = nullptr;

Logfile* lg;

OutputLogger OUTPUT_LOG;

std::vector<std::string> load_dep_files(const std::string& depdir);

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

int main(int argc, char **argv) {
    
    Packet::set_packet_size(DEFAULT_PACKET_SIZE - DEFAULT_HEADER_SIZE);
    mem_b queuesize = DEFAULT_QUEUE_SIZE * DEFAULT_PACKET_SIZE;

    stringstream filename(ios_base::out);

    string depdir;

    // Path to the input file that defines all flow configurations.
    string flowfile;

    // Path to the input file that defines the network topology.
    string topfile;

    string outputfile;

    // Pull rate for NDP connections, configurable from the command line.
    double pull_rate = 1.0;

    // Total simulation duration in seconds.
    double simtime = 1.0;

    // Interval for utilization monitoring, in seconds.
    double utiltime = 0.01;

    // Flag to enable or disable VLB (Valiant Load Balancing) routing for large flows.
    int VLB = 0;

    // Initial congestion window size (in packets).
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
    } else if (!strcmp(argv[i],"-VLB")) {
        VLB = atoi(argv[i+1]);
        i++;
    } else if (!strcmp(argv[i],"-simtime")) {
        simtime = atof(argv[i+1]);
        i++;
    } else if (!strcmp(argv[i],"-utiltime")) {
        utiltime = atof(argv[i+1]);
        i++;
	} else if (!strcmp(argv[i], "-depdir")) {
        depdir = argv[i+1];
        i++;
    }
     else {
	    exit_error(argv[0]);
	}
	i++;
    }
    srand(42);
    
    size_t flush_every = 10000; // flush lines 
    size_t buf_size = 128 * 1024 * 1024; // 128MB
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

    // Initialize the DAG manager and set the runtime context.
    DagManager dagman;
    dagman.set_runtime_context(&eventlist, top, ndpRtxScanner, sinkLogger,
                               pull_rate, cwnd, VLB);

    // Load task dependency graphs (DAG definitions) from files.
    std::vector<std::string> dep_files = load_dep_files(depdir);
    dagman.load_from_files(dep_files);

    // Start all root groups (with indegree = 0) in the DAG.
    dagman.start_all_ready();

    // Initialize the utilization monitor to record link usage statistics.
    UtilMonitor* UM = new UtilMonitor(top, eventlist);
    UM->start(timeFromSec(utiltime));

    // Log basic simulation parameters and start the main event loop.
    logfile.write("# pktsize=" + ntoa(Packet::data_packet_size()) + " bytes");
    logfile.write("# hostnicrate = " + ntoa(HOST_NIC) + " pkt/sec");
    logfile.write("# corelinkrate = " + ntoa(HOST_NIC * CORE_TO_HOST) + " pkt/sec");
    std::cout << "[INFO] HOST_NIC : " << HOST_NIC << std::endl;

    while (eventlist.doNextEvent()) {}
    OUTPUT_LOG.finalFlush();
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

    // === Parameter validation ===
    if (depdir.empty()) {
        std::cerr << "[ERROR] Missing -depdir parameter. Please specify the DAG folder path." << std::endl;
        exit(1);
    }

    // === Check if the directory exists ===
    struct stat sb;
    if (stat(depdir.c_str(), &sb) != 0 || !S_ISDIR(sb.st_mode)) {
        std::cerr << "[ERROR] Dependency directory not found or invalid: " << depdir << std::endl;
        exit(1);
    }

    // === Traverse all .txt files in the directory ===
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

    // === If no files are found, terminate with an error ===
    if (dep_files.empty()) {
        std::cerr << "[ERROR] No dependency files (.txt) found in " << depdir << std::endl;
        exit(1);
    }

    std::cout << "[INFO] Loaded " << dep_files.size()
              << " DAG files from " << depdir << std::endl;

    return dep_files;
}
