#ifndef FLOW_LEVEL_SIM_SIMULATOR_H
#define FLOW_LEVEL_SIM_SIMULATOR_H

#include <memory>
#include <vector>

#include "scheduler.h"
#include "types.h"

namespace flsim {

class FlowLevelSimulator {
public:
    FlowLevelSimulator(std::vector<std::vector<double>> capacity,
                       int numTor,
                       int numEps,
                       std::unique_ptr<Scheduler> scheduler);

    SimulationResult run(const std::vector<Job>& jobs) const;

private:
    std::vector<std::vector<double>> capacity_;
    int numTor_ = 0;
    int numEps_ = 0;
    std::unique_ptr<Scheduler> scheduler_;
};

}  // namespace flsim

#endif
