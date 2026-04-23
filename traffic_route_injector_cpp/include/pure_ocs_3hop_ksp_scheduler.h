#ifndef FLOW_LEVEL_SIM_PURE_OCS_3HOP_KSP_SCHEDULER_H
#define FLOW_LEVEL_SIM_PURE_OCS_3HOP_KSP_SCHEDULER_H

#include <cstdint>
#include <unordered_map>
#include <vector>

#include "scheduler.h"

namespace flsim {

class PureOcs3HopKspScheduler : public Scheduler {
public:
    PureOcs3HopKspScheduler(int kspK, int maxCandidates);
    void prepare(const SchedulerContext& ctx) const override;
    std::string name() const override;
    std::vector<ScheduledFlow> scheduleJob(const Job& job,
                                           const SchedulerContext& ctx) const override;

private:
    static uint64_t pairKey(int s, int t);

    int kspK_ = 4;
    int maxCandidates_ = 20;
    mutable const std::vector<std::vector<double>>* cachedCapacity_ = nullptr;
    mutable int cachedNumTor_ = -1;
    mutable int cachedTorDiameter_ = -1;
    mutable int cachedEffectiveMaxHops_ = -1;
    mutable std::vector<std::vector<int>> shortestHop_;
    mutable std::vector<std::vector<std::vector<CandidatePath>>> cachedTemplateCandidates_;
    mutable std::unordered_map<uint64_t, CandidatePath> fallbackKspPath_;
};

}  // namespace flsim

#endif
