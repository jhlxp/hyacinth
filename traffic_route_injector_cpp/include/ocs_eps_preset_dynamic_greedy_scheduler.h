#ifndef FLOW_LEVEL_SIM_OCS_EPS_PRESET_DYNAMIC_GREEDY_SCHEDULER_H
#define FLOW_LEVEL_SIM_OCS_EPS_PRESET_DYNAMIC_GREEDY_SCHEDULER_H

#include <cstdint>
#include <unordered_map>
#include <vector>

#include "scheduler.h"

namespace flsim {

class OcsEpsPresetDynamicGreedyScheduler : public Scheduler {
public:
    struct CachedCandidate {
        CandidatePath path;
        std::vector<Edge> edges;
        std::vector<int> edgeIds;
    };

    OcsEpsPresetDynamicGreedyScheduler(int kspK, int maxCandidates);
    void prepare(const SchedulerContext& ctx) const override;
    double reportedSolveTimeMs(double measuredWallTimeMs) const override;
    std::string name() const override;
    std::vector<ScheduledFlow> scheduleJob(const Job& job,
                                           const SchedulerContext& ctx) const override;

private:
    static uint64_t pairKey(int s, int t);

    int kspK_ = 4;
    int maxCandidates_ = 20;
    mutable double lastSortGreedySolveTimeMs_ = 0.0;

    mutable const std::vector<std::vector<double>>* cachedCapacity_ = nullptr;
    mutable int cachedNumTor_ = -1;
    mutable int cachedNumEps_ = -1;
    mutable int cachedNodeCount_ = -1;
    mutable std::vector<std::vector<int>> shortestHop_;
    mutable std::unordered_map<uint64_t, std::vector<CachedCandidate>> ocsCache_;
    mutable std::unordered_map<uint64_t, std::vector<CachedCandidate>> epsTemplateCache_;
};

}  // namespace flsim

#endif
