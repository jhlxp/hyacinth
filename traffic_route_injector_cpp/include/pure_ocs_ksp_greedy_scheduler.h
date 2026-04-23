#ifndef FLOW_LEVEL_SIM_PURE_OCS_KSP_GREEDY_SCHEDULER_H
#define FLOW_LEVEL_SIM_PURE_OCS_KSP_GREEDY_SCHEDULER_H

#include <cstdint>
#include <unordered_map>

#include "scheduler.h"

namespace flsim {

class PureOcsKspGreedyScheduler : public Scheduler {
public:
    struct CachedCandidate {
        CandidatePath path;
        std::vector<Edge> edges;
        std::vector<int> edgeIds;
    };

    explicit PureOcsKspGreedyScheduler(int kspK);
    void prepare(const SchedulerContext& ctx) const override;
    bool countsSolveTime() const override;
    double reportedSolveTimeMs(double measuredWallTimeMs) const override;
    std::string name() const override;
    std::vector<ScheduledFlow> scheduleJob(const Job& job,
                                           const SchedulerContext& ctx) const override;

private:
    static uint64_t pairKey(int s, int t);

    int kspK_ = 4;
    mutable double lastGreedySolveTimeMs_ = 0.0;
    mutable const std::vector<std::vector<double>>* cachedCapacity_ = nullptr;
    mutable int cachedNumTor_ = -1;
    mutable int cachedMaxNodeExclusive_ = -1;
    mutable int cachedNodeCount_ = -1;
    mutable std::vector<std::vector<int>> shortestHop_;
    mutable std::unordered_map<uint64_t, std::vector<CachedCandidate>> kspCache_;
};

}  // namespace flsim

#endif
