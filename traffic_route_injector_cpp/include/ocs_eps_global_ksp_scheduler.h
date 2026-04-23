#ifndef FLOW_LEVEL_SIM_OCS_EPS_GLOBAL_KSP_SCHEDULER_H
#define FLOW_LEVEL_SIM_OCS_EPS_GLOBAL_KSP_SCHEDULER_H

#include <cstdint>
#include <unordered_map>

#include "scheduler.h"

namespace flsim {

class OcsEpsGlobalKspScheduler : public Scheduler {
public:
    explicit OcsEpsGlobalKspScheduler(int kspK);
    void prepare(const SchedulerContext& ctx) const override;
    bool countsSolveTime() const override;
    std::string name() const override;
    std::vector<ScheduledFlow> scheduleJob(const Job& job,
                                           const SchedulerContext& ctx) const override;

private:
    static uint64_t pairKey(int s, int t);

    int kspK_ = 4;
    mutable const std::vector<std::vector<double>>* cachedCapacity_ = nullptr;
    mutable int cachedMaxNodeExclusive_ = -1;
    mutable std::unordered_map<uint64_t, std::vector<CandidatePath>> kspCache_;
};

}  // namespace flsim

#endif
