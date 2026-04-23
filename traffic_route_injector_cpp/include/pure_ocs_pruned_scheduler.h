#ifndef FLOW_LEVEL_SIM_PURE_OCS_PRUNED_SCHEDULER_H
#define FLOW_LEVEL_SIM_PURE_OCS_PRUNED_SCHEDULER_H

#include <vector>

#include "scheduler.h"

namespace flsim {

class PureOcsPrunedScheduler : public Scheduler {
public:
    PureOcsPrunedScheduler(int maxHops, int maxCandidates);
    void prepare(const SchedulerContext& ctx) const override;
    std::string name() const override;
    std::vector<ScheduledFlow> scheduleJob(const Job& job,
                                           const SchedulerContext& ctx) const override;

private:
    int maxHops_ = 5;
    int maxCandidates_ = 20;
    mutable const std::vector<std::vector<double>>* cachedCapacity_ = nullptr;
    mutable int cachedNumTor_ = -1;
    mutable int cachedTorDiameter_ = -1;
    mutable int cachedEffectiveMaxHops_ = -1;
    mutable std::vector<std::vector<std::vector<CandidatePath>>> cachedPairCandidates_;
};

}  // namespace flsim

#endif
