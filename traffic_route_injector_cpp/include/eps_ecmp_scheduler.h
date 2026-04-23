#ifndef FLOW_LEVEL_SIM_EPS_ECMP_SCHEDULER_H
#define FLOW_LEVEL_SIM_EPS_ECMP_SCHEDULER_H

#include <cstdint>
#include <unordered_map>
#include <vector>

#include "scheduler.h"

namespace flsim {

class EpsEcmpScheduler : public Scheduler {
public:
    EpsEcmpScheduler() = default;
    void prepare(const SchedulerContext& ctx) const override;
    bool countsSolveTime() const override;
    std::string name() const override;
    std::vector<ScheduledFlow> scheduleJob(const Job& job,
                                           const SchedulerContext& ctx) const override;

private:
    static uint64_t pairKey(int s, int t);

    mutable const std::vector<std::vector<double>>* cachedCapacity_ = nullptr;
    mutable int cachedNumTor_ = -1;
    mutable int cachedNumEps_ = -1;
    mutable std::unordered_map<uint64_t, std::vector<CandidatePath>> ecmpCache_;
};

}  // namespace flsim

#endif
