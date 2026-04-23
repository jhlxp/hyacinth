#include "dag_manager.h"
#include "flat_topology.h"
#include "ndp.h"
#include "tcp.h"
#include "dctcp.h"
#include "bolt.h"
#include "hpcc.h"
#include "loggers.h"
#include "route.h"
#include "compositequeue.h"

#include <unordered_set>
#include <sstream>
#include <fstream>
#include <iostream>
#include <cctype>
#include "output_log.h"

namespace {
bool parse_int_token(const std::string& token, int& value) {
    try {
        size_t pos = 0;
        long long v = std::stoll(token, &pos);
        if (pos != token.size()) return false;
        value = (int)v;
        return true;
    } catch (...) {
        return false;
    }
}

bool parse_tor_path(const std::string& token_value, std::vector<int>& tor_path, std::string& err_msg) {
    tor_path.clear();
    std::string cleaned;
    cleaned.reserve(token_value.size());
    for (char c : token_value) {
        if (std::isdigit((unsigned char)c)) cleaned.push_back(c);
        else cleaned.push_back(' ');
    }

    std::stringstream ss(cleaned);
    int tor = -1;
    while (ss >> tor) tor_path.push_back(tor);

    if (tor_path.empty()) {
        err_msg = "empty path= token";
        return false;
    }
    return true;
}
} // namespace

// ===================== Runtime Context =====================
void DagManager::set_runtime_context(EventList* ev,
                                     FlatTopology* topo,
                                     NdpRtxTimerScanner* scanner,
                                     NdpSinkLoggerSampling* sink_log,
                                     double pull_rate,
                                     int cwnd_packets,
                                     int vlb_flag) {
    eventlist_ = ev;
    top_ = topo;
    rtx_scanner_ = scanner;
    sink_logger_ = sink_log;
    pull_rate_ = pull_rate;
    cwnd_ = cwnd_packets;
    vlb_ = vlb_flag;
    transport_mode_ = TRANSPORT_NDP;
    tcp_rtx_scanner_ = nullptr;
    tcp_sink_logger_ = nullptr;
    hpcc_max_stage_ = 0;
    hpcc_eta_ = 0.95;
    ssthresh_packets_ = -1;
}

void DagManager::set_runtime_context_tcp(EventList* ev,
                                         FlatTopology* topo,
                                         TcpRtxTimerScanner* scanner,
                                         TcpSinkLoggerSampling* sink_log,
                                         int cwnd_packets,
                                         TransportMode mode,
                                         int hpcc_max_stage,
                                         double hpcc_eta,
                                         int ssthresh_packets) {
    eventlist_ = ev;
    top_ = topo;
    cwnd_ = cwnd_packets;
    transport_mode_ = mode;
    hpcc_max_stage_ = hpcc_max_stage;
    hpcc_eta_ = hpcc_eta;
    ssthresh_packets_ = ssthresh_packets;

    rtx_scanner_ = nullptr;
    sink_logger_ = nullptr;
    pull_rate_ = 1.0;
    vlb_ = 0;
    tcp_rtx_scanner_ = scanner;
    tcp_sink_logger_ = sink_log;
}

// ===================== Load DAG Files =====================
void DagManager::load_from_files(const std::vector<std::string>& files) {
    for (const auto& path : files) {
        Dag* g = new Dag();
        g->name = path;
        load_one_dag(path, *g);
        dags_.push_back(g);
    }
    assign_global_uids();
}

// ===================== Task Completion Callback =====================
void DagManager::notify_task_done(int task_uid) {
    if (task_uid < 0 || task_uid >= (int)uid2ref_.size()) {
        std::cerr << "[DagManager] WARN: notify invalid uid " << task_uid << "\n";
        return;
    }
    const TaskRef& ref = uid2ref_[task_uid];
    if (ref.dag_idx < 0 || ref.dag_idx >= (int)dags_.size()) return;

    Dag* dag = dags_[ref.dag_idx];
    if (ref.task_idx < 0 || ref.task_idx >= (int)dag->tasks.size()) return;

    const Task& t = dag->tasks[ref.task_idx];
    auto itg = dag->groups.find(t.group);
    if (itg == dag->groups.end()) return;

    Group& grp = itg->second;
    if (grp.remaining <= 0) {
        std::cerr << "[DagManager] WARN: group " << t.group
                  << " double-finish? uid=" << task_uid << "\n";
        return;
    }
    grp.remaining--;

    std::cout << "[DagManager] Task UID=" << task_uid
              << " (DAG#" << ref.dag_idx << ", group=" << t.group
              << ") done, remain=" << grp.remaining << std::endl;

    if (grp.remaining <= 3) {
        std::cout << "[DagManager] ==> Group " << t.group
                  << " finished in DAG#" << ref.dag_idx
                  << ", triggering successors..." << std::endl;
        trigger_next_groups(ref.dag_idx, t.group);
    }
}

// ===================== Start All Root Groups =====================
void DagManager::start_all_ready() {
    for (int d = 0; d < (int)dags_.size(); ++d)
        start_ready_groups(d);

    if (eventlist_) {
        std::cout << "[Debug] After start_all_ready: pending events = "
                  << eventlist_->debug_pending_size() << std::endl;
    }
}

// ===================== Load a Single DAG File =====================
void DagManager::load_one_dag(const std::string& path, Dag& dag) {
    std::ifstream fin(path);
    if (!fin.is_open()) {
        std::cerr << "[DagManager] ERROR: cannot open " << path << std::endl;
        return;
    }

    std::string line;
    int line_idx = 0;
    int task_count = 0;
    while (std::getline(fin, line)) {
        line_idx++;

        // --- Trim whitespace and ignore comment lines ---
        line.erase(0, line.find_first_not_of(" \t\r"));
        if (line.empty() || line[0] == '#')
            continue;

        size_t comment_pos = line.find('#');
        if (comment_pos != std::string::npos)
            line = line.substr(0, comment_pos);

        std::stringstream ss(line);
        std::vector<std::string> tokens;
        std::string token;
        while (ss >> token) tokens.push_back(token);
        if (tokens.empty()) continue;

        if (tokens.size() < 5) {
            std::cerr << "[DagManager] Warning: malformed line " << line_idx
                      << " in " << path << ": expected at least 5 columns" << std::endl;
            continue;
        }

        Task t;
        int src = 0, dst = 0, gid = 0;
        if (!parse_int_token(tokens[0], src) ||
            !parse_int_token(tokens[1], dst) ||
            !parse_int_token(tokens[4], gid)) {
            std::cerr << "[DagManager] Warning: malformed integer fields at line "
                      << line_idx << " in " << path << std::endl;
            continue;
        }

        try {
            size_t pos_bytes = 0;
            size_t pos_comp = 0;
            t.bytes = std::stoll(tokens[2], &pos_bytes);
            t.comp_us = std::stod(tokens[3], &pos_comp);
            if (pos_bytes != tokens[2].size() || pos_comp != tokens[3].size()) {
                throw std::invalid_argument("trailing chars");
            }
        } catch (...) {
            std::cerr << "[DagManager] Warning: malformed bytes/comp at line "
                      << line_idx << " in " << path << std::endl;
            continue;
        }
        t.src = src;
        t.dst = dst;
        t.group = gid;

        for (size_t i = 5; i < tokens.size(); ++i) {
            const std::string& dep = tokens[i];
            if (dep == "-") continue;

            if (dep.rfind("path=", 0) == 0) {
                std::string err_msg;
                std::string path_str = dep.substr(5);
                if (!parse_tor_path(path_str, t.tor_path, err_msg)) {
                    std::cerr << "[DagManager] Warning: invalid path token '" << dep
                              << "' at line " << line_idx << " in " << path
                              << " (" << err_msg << ")" << std::endl;
                    t.has_explicit_path = false;
                    t.tor_path.clear();
                    continue;
                }
                t.has_explicit_path = true;
                continue;
            }

            try {
                int g = std::stoi(dep);
                if (g == t.group) {
                    std::cerr << "[DagManager] Warning: self-dependency in group "
                              << g << " ignored." << std::endl;
                    continue;
                }
                t.deps.push_back(g);
            } catch (const std::invalid_argument&) {
                std::cerr << "[DagManager] Warning: invalid dependency token '"
                          << dep << "' (ignored) in line " << line_idx
                          << " of " << path << std::endl;
                break;
            }
        }

        if (t.bytes > 0 && !t.has_explicit_path) {
            std::cerr << "[DagManager] Warning: line " << line_idx
                      << " has bytes>0 but no path= token; task skipped." << std::endl;
            continue;
        }

        dag.tasks.push_back(t);
        task_count++;
    }

    build_groups(dag);
    std::cout << "[DagManager] Loaded " << task_count
              << " tasks from " << path
              << " with " << dag.groups.size() << " groups" << std::endl;
}


// ===================== Build Group Dependencies =====================
void DagManager::build_groups(Dag& dag) {
    for (int i = 0; i < (int)dag.tasks.size(); ++i) {
        int gid = dag.tasks[i].group;
        Group& g = dag.groups[gid];
        g.gid = gid;
        g.tasks.push_back(i);
    }

    for (const auto& t : dag.tasks) {
        for (int dep_gid : t.deps) {
            if (!dag.groups.count(dep_gid)) continue;
            dag.groups[dep_gid].succ.push_back(t.group);
        }
    }

    for (auto& kv : dag.groups) {
        auto& g = kv.second;
        std::unordered_set<int> uniq(g.succ.begin(), g.succ.end());
        g.succ.assign(uniq.begin(), uniq.end());
        g.indegree = 0;
        g.remaining = (int)g.tasks.size();
        g.started = false;
    }
    for (auto& kv : dag.groups) {
        auto& g = kv.second;
        for (int s : g.succ)
            dag.groups[s].indegree++;
    }
}

// ===================== Assign Global UIDs =====================
void DagManager::assign_global_uids() {
    uid2ref_.clear();
    for (int d = 0; d < (int)dags_.size(); ++d) {
        Dag* dag = dags_[d];
        for (int i = 0; i < (int)dag->tasks.size(); ++i) {
            int uid = (int)uid2ref_.size();
            dag->tasks[i].uid = uid;
            uid2ref_.push_back(TaskRef{d, i});
        }
    }
    std::cout << "[DagManager] Global tasks = " << uid2ref_.size() << std::endl;
}

// ===================== Trigger Successor Groups =====================
void DagManager::trigger_next_groups(int dag_idx, int finished_gid) {
    Dag& dag = *dags_[dag_idx];
    Group& g = dag.groups[finished_gid];

    size_t pending_before = eventlist_->debug_pending_size();

    std::vector<int> ready_groups;
    for (int succ_gid : g.succ) {
        Group& nxt = dag.groups[succ_gid];
        nxt.indegree--;

        if (nxt.indegree == 0 && !nxt.started) {
            nxt.started = true;

            std::cout << "[DagManager] ==> Group " << succ_gid
                      << " in DAG#" << dag_idx << " is READY" << std::endl;

            ready_groups.push_back(succ_gid);
        }
    }

    for (int rgid : ready_groups) {
        Group& rg = dag.groups[rgid];
        for (int tid : rg.tasks)
            launch_task(dag_idx, tid);
    }

    size_t pending_after = eventlist_->debug_pending_size();
    size_t added = pending_after - pending_before;

    std::cout << "[Debug] Group " << finished_gid
              << " triggered, pending: before=" << pending_before
              << " after=" << pending_after
              << " added=" << added << std::endl;
}

// ===================== Start Root Group Tasks =====================
void DagManager::start_ready_groups(int dag_idx) {
    Dag& dag = *dags_[dag_idx];
    for (auto& kv : dag.groups) {
        auto& g = kv.second;
        if (g.indegree == 0 && !g.started) {
            g.started = true;
            std::cout << "[DagManager] ==> Group " << g.gid
                      << " in DAG#" << dag_idx << " is READY (root)" << std::endl;
            for (int tid : g.tasks)
                launch_task(dag_idx, tid);
        }
    }
}

// ===================== Launch a Single Task =====================
void DagManager::launch_task(int dag_idx, int task_idx) {
    assert(eventlist_ && top_ && "DagManager runtime context is not set!");
    if (transport_mode_ == TRANSPORT_NDP) {
        assert(rtx_scanner_ && sink_logger_ &&
               "DagManager NDP runtime context is not set!");
    } else {
        assert(tcp_rtx_scanner_ && tcp_sink_logger_ &&
               "DagManager TCP runtime context is not set!");
    }

    Dag& dag = *dags_[dag_idx];
    Task& t = dag.tasks[task_idx];

    double now_s = (double)timeAsUs(eventlist_->now()) / 1e6;
    std::cout << "[DagTask] Launch UID=" << t.uid
              << " (DAG#" << dag_idx << ", group=" << t.group << ")"
              << " src=" << t.src << " dst=" << t.dst
              << " bytes=" << t.bytes
              << " comp=" << t.comp_us << "us"
              << " at t=" << now_s << "s"
              << std::endl;

    // ===== Branch for Pure Computation Tasks (No Network Involved) =====
    if (t.comp_us > 0 && t.bytes <= 0) {
        simtime_picosec start_at = eventlist_->now();
        simtime_picosec finish_at = start_at + timeFromUs(t.comp_us);

        double cct_ms   = timeAsMs(finish_at - start_at);
        double start_ms = timeAsMs(start_at);

        // CCT output for computation
        // Format: dag_id group_id task_id CCT src dst bytes cct_ms timestarted_ms
        OUTPUT_LOG << dag_idx << " "
            << t.group << " "
            << t.uid << " "
            << "CCT "
            << t.src << " "
            << t.dst << " "
            << t.bytes << " "
            << cct_ms << " "
            << start_ms
            << "\n";

        // Register a completion event to trigger notify_task_done.
        auto* ev = new ComputeDoneEvent(*eventlist_, this, t.uid);
        eventlist_->sourceIsPending(*ev, finish_at);
        return;
    }

    // ===== Normal Branch for Network Transmission =====
    // 1) Configure routing paths and establish connections.
    if (!t.has_explicit_path) {
        std::cerr << "[DagManager] ERROR: network task UID=" << t.uid
                  << " has no path= token; mark as done to avoid deadlock.\n";
        notify_task_done(t.uid);
        return;
    }

    vector<const Route*>* srcpaths = nullptr;
    vector<const Route*>* dstpaths = nullptr;
    std::string err_msg;
    if (!top_->get_single_path_from_tors(t.src, t.dst, t.tor_path, srcpaths, &err_msg)) {
        std::cerr << "[DagManager] ERROR: invalid explicit path for UID=" << t.uid
                  << " src=" << t.src << " dst=" << t.dst
                  << " reason=" << err_msg
                  << " ; mark as done to avoid deadlock.\n";
        notify_task_done(t.uid);
        return;
    }
    std::vector<int> reverse_tor_path(t.tor_path.rbegin(), t.tor_path.rend());
    if (!top_->get_single_path_from_tors(t.dst, t.src, reverse_tor_path, dstpaths, &err_msg)) {
        std::cerr << "[DagManager] ERROR: invalid reverse explicit path for UID=" << t.uid
                  << " src=" << t.src << " dst=" << t.dst
                  << " reason=" << err_msg
                  << " ; mark as done to avoid deadlock.\n";
        notify_task_done(t.uid);
        return;
    }

    if (!srcpaths || srcpaths->empty() || !dstpaths || dstpaths->empty()) {
        std::cerr << "[DagManager] ERROR: no path " << t.src << "->" << t.dst
                  << " ; mark as done to avoid deadlock.\n";
        // Mark the task as completed directly to prevent DAG deadlock.
        notify_task_done(t.uid);
        return;
    }

    // 2) If the task involves computation before transmission, delay by comp_us microseconds before starting the transfer.
    simtime_picosec start_at = eventlist_->now();
    if (t.comp_us > 0 && t.bytes <= 1)
        start_at += timeFromUs(t.comp_us);

    if (transport_mode_ == TRANSPORT_NDP) {
        NdpSrc* src = new NdpSrc(nullptr, nullptr, *eventlist_, t.src, t.dst);
        src->setCwnd(cwnd_ * Packet::data_packet_size());
        src->set_flowsize(t.bytes > 0 ? t.bytes : 1);
        src->set_coflow_group_id(t.group);

        // Set dependency context for completion callback.
        src->dep_top = top_;
        src->dep_ndpRtxScanner = rtx_scanner_;
        src->dep_sinkLogger = sink_logger_;
        src->dep_pull_rate = pull_rate_;
        src->dep_cwnd = cwnd_;
        src->dep_VLB = vlb_;
        src->dep_dagman = this;
        src->rag_id = t.uid;

        NdpPullPacer* pacer = new NdpPullPacer(*eventlist_, pull_rate_);
        NdpSink* snk = new NdpSink(pacer);
        snk->dep_dagman = this;
        snk->rag_id = t.uid;

        rtx_scanner_->registerNdp(*src);
        src->setvlb(false);

        Route* r_out = new Route(*(srcpaths->at(0)));
        r_out->push_back(snk);
        Route* r_in = new Route(*(dstpaths->at(0)));
        r_in->push_back(src);

        if (NdpSrc::_route_strategy == SINGLE_PATH) {
            r_out->set_path_id(0, 1);
            r_in->set_path_id(0, 1);
        }

        src->connect(*r_out, *r_in, *snk, start_at);

        src->set_num_shortest_paths(1);
        snk->set_num_shortest_paths(1);
        if (NdpSrc::_route_strategy != SINGLE_PATH) {
            src->set_paths(srcpaths);
            snk->set_paths(dstpaths);
        }
        sink_logger_->monitorSink(snk);
    } else {
        TcpSrc* src = nullptr;
        if (transport_mode_ == TRANSPORT_DCTCP) {
            src = new DCTCPSrc(nullptr, nullptr, *eventlist_, t.src, t.dst);
        } else if (transport_mode_ == TRANSPORT_BOLT) {
            src = new BoltSrc(nullptr, nullptr, *eventlist_, t.src, t.dst, false);
        } else if (transport_mode_ == TRANSPORT_HPCC) {
            src = new HPCCSrc(nullptr, nullptr, *eventlist_, t.src, t.dst,
                              hpcc_max_stage_, (float)hpcc_eta_);
        } else {
            std::cerr << "[DagManager] ERROR: unknown transport mode\n";
            notify_task_done(t.uid);
            return;
        }

        TcpSink* snk = new TcpSink();
        src->set_flowsize(t.bytes > 0 ? (uint64_t)t.bytes : 1);
        src->set_flowid((uint64_t)t.uid);
        src->set_coflow_group_id(t.group);
        src->rag_id = t.uid;
        src->dep_dagman = this;
        src->set_cwnd(cwnd_);
        if (ssthresh_packets_ > 0) {
            src->set_ssthresh((uint64_t)ssthresh_packets_ * Packet::data_packet_size());
        }
        if (transport_mode_ == TRANSPORT_BOLT) {
            src->set_nosyn();
        }
        tcp_rtx_scanner_->registerTcp(*src);

        Route* r_out = new Route(*(srcpaths->at(0)));
        r_out->push_back(snk);
        Route* r_in = new Route(*(dstpaths->at(0)));
        r_in->push_back(src);
        r_out->set_reverse(r_in);
        r_in->set_reverse(r_out);

        src->connect(*r_out, *r_in, *snk, start_at);
        tcp_sink_logger_->monitorSink(snk);
    }

    {
        static std::unordered_map<long long,int> cnt;
        long long key = ((long long)dag_idx << 32) | (long long)t.group;

        cnt[key]++;

        std::cout << "[CONNECT] DAG#" << dag_idx
                << " group=" << t.group
                << " count=" << cnt[key]
                << " (UID=" << t.uid << ")"
                << " start_at=" << start_at
                << std::endl;
    }

    // 3) Route+endpoint registration completed.
}


bool DagManager::uid_to_dag_group_task(int uid, int& dag_idx, int& group_id, int& task_id) const {
    dag_idx = -1;
    group_id = -1;
    task_id = -1;

    if (uid < 0 || uid >= (int)uid2ref_.size())
        return false;

    const TaskRef& ref = uid2ref_[uid];
    dag_idx  = ref.dag_idx;
    task_id  = ref.task_idx;

    if (ref.dag_idx < 0 || ref.dag_idx >= (int)dags_.size())
        return false;

    const Dag* dag = dags_[ref.dag_idx];
    if (ref.task_idx < 0 || ref.task_idx >= (int)dag->tasks.size())
        return false;

    group_id = dag->tasks[ref.task_idx].group;

    return true;
}

