#ifndef FLOW_LEVEL_SIM_SCHEDULER_H
#define FLOW_LEVEL_SIM_SCHEDULER_H

#include <memory>
#include <string>
#include <vector>

#include "types.h"

namespace flsim {

struct SchedulerConfig {
    std::string name = "ocs_eps_pruned";
    int kspK = 4;
    int maxHops = 5;
    int maxCandidates = 20;
    std::string smallFlowMode = "percent";  // percent | value
    double smallFlowThreshold = 90.0;
};

struct SchedulerContext {
    const std::vector<std::vector<double>>& capacity;
    const std::vector<std::vector<double>>& currentFreeTime;
    int numTor = 0;
    int numEps = 0;
    // Optional per-edge active-load snapshot at this scheduling instant.
    // When set, schedulers can model "later coflows see current link load".
    const std::vector<std::vector<double>>* edgeBackgroundLoad = nullptr;
};

class Scheduler {
public:
    virtual ~Scheduler() = default;
    // Optional precomputation hook. Called before solve-time measurement.
    virtual void prepare(const SchedulerContext& ctx) const {
        (void)ctx;
    }
    // Whether scheduler wall time should be counted into solveTime metrics.
    virtual bool countsSolveTime() const {
        return true;
    }
    // Optional per-scheduler remap for solve-time reporting.
    // Default: report measured wall time of scheduleJob().
    virtual double reportedSolveTimeMs(double measuredWallTimeMs) const {
        return measuredWallTimeMs;
    }
    virtual std::string name() const = 0;
    virtual std::vector<ScheduledFlow> scheduleJob(const Job& job,
                                                   const SchedulerContext& ctx) const = 0;
};

std::unique_ptr<Scheduler> createScheduler(const SchedulerConfig& config);

}  // namespace flsim

#endif
