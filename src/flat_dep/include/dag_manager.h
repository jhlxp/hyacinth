#ifndef DAG_MANAGER_H
#define DAG_MANAGER_H

#include <iostream>
#include <fstream>
#include <sstream>
#include <vector>
#include <unordered_map>
#include <unordered_set>
#include <string>
#include <cassert>

#include "eventlist.h"

// ---- Forward declarations to break circular dependencies ----
class NdpRtxTimerScanner;
class NdpSinkLoggerSampling;
class NdpSrc;
class NdpSink;
class NdpPullPacer;
class Route;
class FlatTopology;
class TcpRtxTimerScanner;
class TcpSinkLoggerSampling;

// ===================== Basic Data Structures =====================

struct Task {
    int src = 0, dst = 0;
    int64_t bytes = 0;        // Transfer size in bytes; <=1 and comp_us>0 means a "compute task"
    double comp_us = 0.0;     // Computation duration in microseconds
    int group = 0;            // Group ID this task belongs to
    std::vector<int> deps;    // List of predecessor group IDs
    bool has_explicit_path = false;
    std::vector<int> tor_path; // Optional explicit ToR sequence for source routing
    int uid = -1;             // Global task UID (assigned by DagManager)
};

struct Group {
    int gid = 0;
    int indegree = 0;               // Number of unfinished predecessor groups
    int remaining = 0;              // Number of unfinished tasks in this group
    std::vector<int> succ;          // List of successor group IDs
    std::vector<int> tasks;         // Indexes of tasks in Dag.tasks belonging to this group
    bool started = false;           // Prevents multiple launches
};

struct Dag {
    std::string name;
    std::vector<Task> tasks;
    std::unordered_map<int, Group> groups;
};

struct TaskRef {
    int dag_idx = -1;
    int task_idx = -1;
};

// ===================== DagManager =====================

class DagManager {
public:
    DagManager() = default;

    enum TransportMode {
        TRANSPORT_NDP = 0,
        TRANSPORT_DCTCP = 1,
        TRANSPORT_BOLT = 2,
        TRANSPORT_HPCC = 3
    };

    // Runtime context
    void set_runtime_context(EventList* ev,
                             FlatTopology* topo,
                             NdpRtxTimerScanner* scanner,
                             NdpSinkLoggerSampling* sink_log,
                             double pull_rate,
                             int cwnd_packets,
                             int vlb_flag);

    // Runtime context for TCP-family transports used in flat_dep.
    void set_runtime_context_tcp(EventList* ev,
                                 FlatTopology* topo,
                                 TcpRtxTimerScanner* scanner,
                                 TcpSinkLoggerSampling* sink_log,
                                 int cwnd_packets,
                                 TransportMode mode,
                                 int hpcc_max_stage = 0,
                                 double hpcc_eta = 0.95,
                                 int ssthresh_packets = -1);

    // Whether to handle "compute tasks" (bytes<=1 and comp_us>0) as pure events (no network); default false
    void set_compute_as_event(bool v) { compute_as_event_ = v; }

    // File format:  src dst bytes comp_us group [deps... | -] path=<tor0,tor1,...>
    void load_from_files(const std::vector<std::string>& files);

    // Notify that a task (specified by global UID) has completed
    void notify_task_done(int task_uid);

    // Start all root groups (those with indegree = 0)
    void start_all_ready();

    // External trigger for safety check
    bool has_task(int uid) const { return uid >= 0 && uid < (int)uid2ref_.size(); }

    Dag* get_dag(int dag_idx) {
        return (dag_idx >= 0 && dag_idx < (int)dags_.size()) ? dags_[dag_idx] : nullptr;
    }

    // Given a global task UID, return dag_idx, group_id, and task_id
    bool uid_to_dag_group_task(int uid, int& dag_idx, int& group_id, int& task_id) const;

private:
    // Internal state
    std::vector<Dag*> dags_;
    std::vector<TaskRef> uid2ref_;

    // Runtime context
    EventList* eventlist_ = nullptr;
    FlatTopology* top_ = nullptr;
    NdpRtxTimerScanner* rtx_scanner_ = nullptr;
    NdpSinkLoggerSampling* sink_logger_ = nullptr;
    double pull_rate_ = 1.0;
    int cwnd_ = 30;
    int vlb_ = 0;

    // TCP runtime context
    TcpRtxTimerScanner* tcp_rtx_scanner_ = nullptr;
    TcpSinkLoggerSampling* tcp_sink_logger_ = nullptr;
    TransportMode transport_mode_ = TRANSPORT_NDP;
    int hpcc_max_stage_ = 0;
    double hpcc_eta_ = 0.95;
    int ssthresh_packets_ = -1;

    // Whether pure computation is handled as an event (no network)
    bool compute_as_event_ = false;

    // Loading and graph construction
    void load_one_dag(const std::string& path, Dag& dag);
    void build_groups(Dag& dag);
    void assign_global_uids();

    // Triggering and launching
    void trigger_next_groups(int dag_idx, int finished_gid);
    void start_ready_groups(int dag_idx);
    void launch_task(int dag_idx, int task_idx);

    // Internal: callback for pure computation event completion
    class ComputeDoneEvent : public EventSource {
    public:
        ComputeDoneEvent(EventList& ev, DagManager* dm, int uid)
        : EventSource(ev, "ComputeDone"), dm_(dm), uid_(uid) {}

        void doNextEvent() override {
            if (dm_) dm_->notify_task_done(uid_);
            delete this;
        }
    private:
        DagManager* dm_;
        int uid_;
    };
};

#endif // DAG_MANAGER_H
