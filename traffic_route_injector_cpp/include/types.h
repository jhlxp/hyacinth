#ifndef FLOW_LEVEL_SIM_TYPES_H
#define FLOW_LEVEL_SIM_TYPES_H

#include <utility>
#include <vector>

namespace flsim {

struct TopologyInput {
    int H = 0;
    int dl = 0;
    int ul = 0;
    int ntorHdr = 0;
    int N = 0;
    std::vector<std::vector<int>> adj;
};

struct TrafficEntry {
    int jobId = -1;
    int flowId = -1;
    int aggSrc = -1;
    int aggDst = -1;
    double bytes = 0.0;
    double startTime = 0.0;
    int modelId = -1;
    int roundId = -1;
    int groupId = -1;
    double compUs = 0.0;
    std::vector<int> deps;
};

struct Flow {
    int jobId = -1;
    int flowId = -1;
    int aggSrc = -1;
    int aggDst = -1;
    int torSrc = -1;
    int torDst = -1;
    double bytes = 0.0;
    double startTime = 0.0;
};

struct Job {
    int jobId = -1;
    double startTime = 0.0;
    std::vector<Flow> flows;
    int modelId = -1;
    int roundId = -1;
    int groupId = -1;
    double computeTime = 0.0;  // seconds
    std::vector<int> deps;
};

struct CandidatePath {
    std::vector<int> nodes;
};

struct ScheduledFlow {
    Flow flow;
    std::vector<int> corePath;
    bool sameTorBypass = false;
    double serviceStartTime = 0.0;
    double finishTime = 0.0;
    double bottleneckRate = 0.0;
};

struct SimulationResult {
    std::vector<ScheduledFlow> scheduledFlows;
    std::vector<std::vector<double>> finalFreeTime;
    struct SolveCallStat {
        int jobId = -1;
        int numFlows = 0;
        double solveTimeMs = 0.0;
    };
    struct JobStat {
        int jobId = -1;
        int numFlows = 0;
        double startTime = 0.0;
        double finishTime = 0.0;
        double duration = 0.0;
        int modelId = -1;
        int roundId = -1;
        int groupId = -1;
    };
    struct CoflowTimelineStat {
        int modelId = -1;
        int roundId = -1;
        int groupId = -1;
        int jobId = -1;
        double readyTime = 0.0;
        double schedStartTime = 0.0;
        double schedEndTime = 0.0;
        double schedTime = 0.0;
        double txStartTime = 0.0;
        double txEndTime = 0.0;
        double txTime = 0.0;
        double bytesTotal = 0.0;
        int numFlows = 0;
    };
    std::vector<SolveCallStat> solveCalls;
    std::vector<JobStat> jobStats;
    std::vector<CoflowTimelineStat> coflowTimelineStats;
    // makespan is defined as sum of per-job (all2allv) durations:
    // sum_j (jobFinishTime_j - jobStartTime_j)
    double makespan = 0.0;
    // max finish timestamp across all flows (legacy meaning of makespan)
    double maxFinishTime = 0.0;
};

using Edge = std::pair<int, int>;

}  // namespace flsim

#endif
