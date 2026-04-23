#ifndef FLOW_LEVEL_SIM_STRICT_QUEUE_GREEDY_SCHEDULER_H
#define FLOW_LEVEL_SIM_STRICT_QUEUE_GREEDY_SCHEDULER_H

#include <vector>

#include "scheduler.h"

namespace flsim {

class StrictQueueGreedyScheduler : public Scheduler {
public:
    void prepare(const SchedulerContext& ctx) const override;
    std::string name() const override;
    std::vector<ScheduledFlow> scheduleJob(const Job& job,
                                           const SchedulerContext& ctx) const override;

private:
    mutable const std::vector<std::vector<double>>* cachedCapacity_ = nullptr;
    mutable int cachedNumTor_ = -1;
    mutable int cachedNumEps_ = -1;
    mutable std::vector<std::vector<std::vector<CandidatePath>>> cachedPairCandidates_;
};

}  // namespace flsim

#endif
